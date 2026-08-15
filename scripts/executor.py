#!/usr/bin/env python3
"""
executor.py — 字段语义状态机执行器（机械化执行的强制者）

状态机由字段名驱动（编排者装配，协议由模块推导）：
  generate_N            → 生成式产出：产物落盘 + schema 验证 → passed → 推进
  discriminate_N_xxx    → 判别式判断：判断项值 ∈ routing keys → 路由到目标字段/stop

职责：
  1. 状态转移的唯一入口：转移表硬编码，非法转移拒绝（agent 不能手改状态）
  2. 前置门禁：依赖字段未 passed 不允许执行（依赖从 inputs 连线 + routing 推导）
  3. 后置门禁：产物未通过检查不允许标记 passed（generate 验 schema / discriminate 验判断值）
  4. 判别路由：discriminate 的判断值决定下一步方向（分支点，op-table condition 语义的继承）
  5. 失败轨迹：记录 failure_log；同一字段 3 次同类失败自动标记 needs_reorchestration
  6. 断点续跑：状态唯一真相源 = steps.json 文件，原子写回
  7. mind 具象化：mind 的 enforce 四层 + module 协议合并进 T3 派发；check 机械执行证据门禁

命令：
  python executor.py materialize <task_dir>      # 设计收敛 → 执行态：复制 draft/ 到任务根
  python executor.py status <task_dir>           # 显示状态机全景
  python executor.py ready <task_dir>            # 列出可执行字段（前置满足 + pending）
  python executor.py t3      <task_dir> <field>  # 生成字段 T3 六件套（派发唯一依据）
  python executor.py check   <task_dir> <field>  # 后置门禁：验证产物并推进/路由
  python executor.py retry   <task_dir> <field>  # failed → pending（重试）
  python executor.py reset   <task_dir> <field>  # needs_reorchestration → pending

退出码：0=正常, 1=检查失败/非法操作, 2=用法错误
"""
import csv
import json
import os
import re
import sys
import tempfile
from collections import deque

# ---- 字段名语义 ----
GEN_FIELD = re.compile(r"^generate_(\d+)$")
DIS_FIELD = re.compile(r"^discriminate_(\d+)_([a-z][a-z0-9_]*)$")

# ---- 转移表：状态机的唯一合法转换集合 ----
VALID_TRANSITIONS = {
    "pending": ["running"],
    "running": ["passed", "failed", "needs_reorchestration"],
    "failed": ["pending"],
    "needs_reorchestration": ["pending"],
    "passed": [],
    "skipped": [],
}

MAX_FAILURES = 3

STEP_FILE = "steps.json"
MODULES_FILE = "modules.json"
STATE_FILE = "state.csv"
OP_TABLE_FILE = "op-table.json"
MODULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modules")


# ---------- 文件 IO ----------

def load_json(path, required=False):
    if not os.path.exists(path):
        if required:
            sys.exit(f"缺少 {path}")
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def load_steps(task_dir):
    data = load_json(os.path.join(task_dir, STEP_FILE), required=True)
    return data


def load_modules(task_dir):
    """任务级 modules/ 优先，回退到 skill 内置 modules/。"""
    local = os.path.join(task_dir, MODULES_FILE)
    if os.path.exists(local):
        data = load_json(local, required=True)
        return {m["id"]: m for m in data.get("modules", [])}
    builtin = os.path.join(MODULES_DIR, MODULES_FILE)
    data = load_json(builtin, required=True)
    return {m["id"]: m for m in data.get("modules", [])}


def save_steps(task_dir, data):
    path = os.path.join(task_dir, STEP_FILE)
    fd, tmp = tempfile.mkstemp(dir=task_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def get_field(fields, fid):
    for f in fields:
        if f["field"] == fid:
            return f
    return None


# ---------- state.csv（字段驱动列，显式快照，最后一行=当前状态） ----------
#
# 列 = 装配表全部字段（generate_N / discriminate_N_xxx）+ _ts + _note。
# **每行 = 一步**：只填当前步产出的字段（generate 填状态 / discriminate 填判断值），
# 其他列留空——无继承。最后一行 = 当前步，op-table 只读最后一行判定下一步。
# 字段完成性 = 产物文件存在（artifacts/<field>.json），不依赖 state 行历史。

def state_columns(fields):
    """列 = 装配表全字段名 + _ts + _note。"""
    return [f["field"] for f in fields] + ["_ts", "_note"]


def load_state(task_dir):
    """读 state.csv 最后一行 → {field: 值}（当前步产出，非空字段）。无文件/空 → {}。"""
    path = os.path.join(task_dir, STATE_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except (csv.Error, OSError) as e:
        sys.exit(f"state.csv 读取失败: {e}")
    if not rows:
        return {}
    last = rows[-1]
    return {k: v for k, v in last.items() if not k.startswith("_") and v}


def append_state(task_dir, fields, fid, value, note="", parallel_group=None):
    """追加/填充一行：串行字段新开一行；并行组字段填入组所在行。

    并行语义：组内字段写在同一行（state.csv 同行填充多字段），
    组全部完成（op-table 多条件 AND 匹配）才推进。若最后一行已是
    本并行组所在行（含组内其他字段），则填充该行；否则新开一行。
    """
    path = os.path.join(task_dir, STATE_FILE)
    import datetime
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    cols = state_columns(fields)
    is_new = not os.path.exists(path)

    # 并行组：定位组所在行（最后一行若已含组内其他字段则复用）
    row = {c: "" for c in cols}
    if not is_new and parallel_group:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            if rows:
                last = rows[-1]
                group_done = [g for g in parallel_group if g != fid and last.get(g)]
                if group_done:
                    # 复用最后一行（组内已有其他字段），填充本字段
                    row = {c: (last.get(c) or "") for c in cols}
                    row[fid] = value
                    row["_ts"] = ts
                    row["_note"] = note
                    # 重写最后一行（去掉旧最后一行再追加）
                    with open(path, "r", encoding="utf-8-sig") as f:
                        all_lines = f.readlines()
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        f.writelines(all_lines[:-1])
                    with open(path, "a", encoding="utf-8", newline="") as f:
                        csv.writer(f).writerow([row.get(c, "") for c in cols])
                    return
        except (csv.Error, OSError):
            pass

    # 新行：只填当前字段
    row[fid] = value
    row["_ts"] = ts
    row["_note"] = note
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(cols)
        writer.writerow([row.get(c, "") for c in cols])


def state_status(task_dir, fid):
    return load_state(task_dir).get(fid, "")


def field_parallel_group(fields, fid):
    """字段声明的并行组（parallel 数组），无则 None。"""
    f = get_field(fields, fid)
    if f is None:
        return None
    p = f.get("parallel")
    return p if isinstance(p, list) and p else None


def field_produce(fid):
    """由字段名推导状态语义。返回 'generate' 或 'discriminate'。"""
    if GEN_FIELD.match(fid):
        return "generate"
    if DIS_FIELD.match(fid):
        return "discriminate"
    return None


def record_failure(f, reason, cls):
    rt = f.setdefault("runtime", {})
    rt["failures"] = rt.get("failures", 0) + 1
    log = rt.setdefault("failure_log", [])
    log.append({"at": reason, "reason": reason, "class": cls})


# ---------- 依赖推导（inputs 连线 + 判别路由，状态来自 state.csv） ----------

def field_inputs(field):
    """字段依赖：inputs 连线中的前序字段名（字符串或数组值都解析）。

    支持 {source: "generate_01"}、{premises: ["generate_01", ...]}、
    {target: ["generate_03", "generate_04"]} 等形态。
    """
    deps = set()
    for v in (field.get("inputs") or {}).values():
        if isinstance(v, str):
            if GEN_FIELD.match(v) or DIS_FIELD.match(v):
                deps.add(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str) and (GEN_FIELD.match(item) or DIS_FIELD.match(item)):
                    deps.add(item)
    return deps


def routing_targets(field):
    """判别式字段的路由目标（routing 值的字段部分；对象形态取 to）。"""
    targets = set()
    for v in (field.get("routing") or {}).values():
        if isinstance(v, dict):
            v = v.get("to", "stop")
        if v == "stop":
            continue
        targets.add(v)
    return targets


def prerequisites_met(task_dir, fields, field):
    """前置门禁：依赖字段的产物文件必须已物化（artifacts/<dep>.json 存在）。

    字段完成性 = 产物文件存在，不依赖 state.csv 行历史（cataclysm 物化语义）。
    判别式依赖 = 其输入字段产物存在。
    """
    deps = field_inputs(field)
    for dep in deps:
        dep_file = os.path.join(task_dir, f"artifacts/{dep}.json")
        if not os.path.exists(dep_file):
            return False, f"依赖字段 {dep} 产物未物化: artifacts/{dep}.json"
    return True, ""


def next_runnable_generate(fields, state, fid):
    """generate_N 的线性推进：同属 generate 序列的后续字段（产物未物化）。"""
    m = GEN_FIELD.match(fid)
    if not m:
        return None
    cur = int(m.group(1))
    for f in fields:
        fm = GEN_FIELD.match(f.get("field", ""))
        if fm and int(fm.group(1)) > cur and not state.get(f["field"]):
            return f["field"]
    return None


# ---------- 产物检查（后置门禁） ----------

def check_artifacts(task_dir, field, module):
    """返回 (ok, issues[])。

    generate：产物 JSON 存在 + output_schema.required 字段齐全；
    discriminate：产物 JSON 存在 + 判断项字段 ∈ routing keys（或模块 routing keys）。
    """
    out_file = f"artifacts/{field['field']}.json"
    fpath = os.path.join(task_dir, out_file)
    issues = []
    if not os.path.exists(fpath):
        return False, [f"产物缺失 {out_file}"]
    try:
        with open(fpath, "r", encoding="utf-8-sig") as f:
            content = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return False, [f"产物 {out_file} 不是合法 JSON: {e}"]

    required = (module.get("output_schema") or {}).get("required", [])
    for field_name in required:
        if field_name not in content:
            issues.append(f"产物 {out_file} 缺少字段 {field_name}")

    # discriminate：判断项值必须 ∈ routing keys（路由合法性）
    # 只校验判断项字段（第一个 required 字符串字段），其余 required 字段（如 basis 证据）
    # 是支撑内容不是路由值，不得参与路由合法域校验。
    if field_produce(field["field"]) == "discriminate":
        routing = field.get("routing") or module.get("routing") or {}
        if not routing:
            issues.append(f"判别字段 {field['field']} 无 routing（模块与装配表均未定义）")
        verdict_field = verdict_field_name(content, module)
        if routing and verdict_field:
            verdict = content.get(verdict_field)
            if verdict not in routing:
                issues.append(
                    f"产物 {out_file} 判断项 {verdict_field}={verdict} 不在路由合法域 {sorted(routing.keys())}"
                )
    return (len(issues) == 0), issues


def verdict_field_name(content, module):
    """判别式判断项字段名 = 第一个 required 且已存在的字符串字段。

    cmd_check 与 check_artifacts 共用同一提取规则，保证校验对象与路由取值一致。
    """
    for item in (module.get("output_schema") or {}).get("required", []):
        if item in content and isinstance(content[item], str):
            return item
    return None


def collect_field_values(node, field):
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == field:
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            found.append(item)
                        elif isinstance(item, dict) and isinstance(item.get("text"), str):
                            found.append(item["text"])
                elif isinstance(v, str):
                    found.append(v)
            else:
                found.extend(collect_field_values(v, field))
    elif isinstance(node, list):
        for item in node:
            found.extend(collect_field_values(item, field))
    return found


def normalize_text(s):
    return " ".join(s.split())


def check_mind_gates(task_dir, field, mind):
    """mind.enforce.check 机械门禁（evidence_in_source 原文验证）。"""
    out_file = f"artifacts/{field['field']}.json"
    fpath = os.path.join(task_dir, out_file)
    if not os.path.exists(fpath):
        return True, []
    if not mind:
        return True, []
    check = (mind.get("enforce") or {}).get("check")
    if not check or check.get("type") != "evidence_in_source":
        return True, []
    try:
        with open(fpath, "r", encoding="utf-8-sig") as f:
            content = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return True, []

    src_path = os.path.join(task_dir, check["source"])
    if not os.path.exists(src_path):
        return False, [f"mind 门禁 {check['type']}: 证据来源文件缺失 {check['source']}"]
    with open(src_path, "r", encoding="utf-8-sig") as f:
        src_norm = normalize_text(f.read())

    values = collect_field_values(content, check["field"])
    issues = []
    for v in values:
        if not v.strip():
            issues.append(f"mind 门禁 {check['type']}: {check['field']} 存在空值")
        elif normalize_text(v) not in src_norm:
            issues.append(f"mind 门禁 {check['type']}: {check['field']} 值不在来源文件中: {v[:60]}")
    return (len(issues) == 0), issues


def load_minds(task_dir):
    data = load_json(os.path.join(task_dir, "minds.json"))
    if not data:
        return {}
    return {m["id"]: m for m in data.get("minds", [])}


# ---------- 命令实现 ----------

def topological_order(fields):
    """全局拓扑序（Kahn）：依赖先于被依赖者。返回 field 列表。"""
    from collections import deque
    field_ids = [f["field"] for f in fields]
    adj = {fid: [] for fid in field_ids}
    indeg = {fid: 0 for fid in field_ids}
    for f in fields:
        fid = f["field"]
        for dep in field_inputs(f):
            if dep in adj:
                adj[dep].append(fid)
                indeg[fid] += 1
    q = deque([fid for fid in field_ids if indeg[fid] == 0])
    order = []
    while q:
        cur = q.popleft()
        order.append(cur)
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    return order


def dependency_depth(fields, fid):
    """字段的依赖深度（递归沿 inputs 连线上溯）。入度 0 字段深度 = 0。"""
    f = get_field(fields, fid)
    if f is None:
        return 0
    deps = field_inputs(f)
    if not deps:
        return 0
    return 1 + max(dependency_depth(fields, d) for d in deps)


def entry_fields(fields):
    """入度 0 字段（无 inputs 依赖）——状态机入口。"""
    return [f["field"] for f in fields if not field_inputs(f)]


def generate_op_table(fields, modules):
    """从编排者设计生成 op-table.json（条件路由表，排它）。

    op-table 完全由编排者的显式声明展开（executor 零推导）：
      generate 字段：
        {"next": "generate_04"} → {condition: "<field>=passed", dispatch: "<next>"}
          串行推进：本字段完成后 → next。
        {"parallel": ["generate_01","generate_02","generate_03"], "next": "generate_04"}
          → {condition: "generate_01=passed,generate_02=passed,generate_03=passed", dispatch: "<next>"}
          并行组：组内字段同行填充（state.csv 一行多字段），全部完成（多条件 AND）→ next。
        parallel 组内每个字段各自声明该组（组 ID 相同），组完成条件由组的字段集合推导。
      discriminate 字段：{"routing": {...}} → 判别点路由展开（见下）。

    并行语义（用户定义）：并行字段写在同一行（state.csv 同行填充），op-table 用多条件
    AND 表达"组完成才推进"；串行字段各占一行。形态完全由编排者声明决定。
    """
    operations = []

    def collect_next_rules():
        """收集 generate 字段的 next/parallel 声明，去重生成推进规则。

        返回 {(group_fields_tuple, next_target): {fields, next}}。
        parallel 组：组内所有字段都声明同一 parallel 数组；取第一字段的 parallel 作为组。
        """
        rules = {}
        for f in fields:
            fid = f["field"]
            produce = field_produce(fid)
            if produce != "generate":
                continue
            parallel = f.get("parallel")
            nxt = f.get("next")
            if not nxt:
                continue
            if parallel:
                # 并行组：组 = 排序后的 parallel 字段元组
                group = tuple(sorted(parallel))
                rules.setdefault(("PARALLEL", group), {"fields": set(group), "next": nxt, "kind": "parallel"})
            else:
                # 串行
                rules.setdefault(("SEQ", fid), {"fields": {fid}, "next": nxt, "kind": "seq"})
        return rules

    for (kind, key), rule in sorted(collect_next_rules().items(), key=lambda kv: (str(kv[0][1]), kv[0][0])):
        fields_in = sorted(rule["fields"])
        if rule["kind"] == "parallel":
            cond = ",".join(f"{fid}=passed" for fid in fields_in)
        else:
            cond = f"{key}=passed"
        operations.append({
            "condition": cond,
            "dispatch": rule["next"],
            "side_effect": None,
        })

    # discriminate：判别点路由展开（编排者设计每个判别点怎么路由）
    for f in fields:
        fid = f["field"]
        produce = field_produce(fid)
        module = modules.get(f["module"], {})
        if produce != "discriminate":
            continue
        routing = f.get("routing") or module.get("routing") or {}
        for verdict, target in routing.items():
            if isinstance(target, str):
                operations.append({
                    "condition": f"{fid}={verdict}",
                    "dispatch": target,
                    "side_effect": None,
                })
            elif isinstance(target, dict):
                to = target.get("to", "stop")
                cnt = target.get("counter", f"{fid}_count")
                limit = target.get("limit")
                escalate = target.get("escalate")
                mind = target.get("mind")
                if limit is not None and escalate:
                    operations.append({
                        "condition": f"{fid}={verdict},{cnt}>={limit}",
                        "dispatch": escalate,
                        "side_effect": None,
                    })
                op = {
                    "condition": f"{fid}={verdict}",
                    "dispatch": to,
                    "side_effect": f"{cnt}+1" if limit is not None else None,
                }
                if mind:
                    op["mind"] = mind
                operations.append(op)
    return operations


def condition_matches(condition, last_state, extra_state=None):
    """条件匹配（排它）：逗号分隔的多条件 AND。

    每项 <field>=<value>：字段存在且值相等。
    last_state = state.csv 最后一行非空字段；extra_state = 外部状态（主 agent 提供的计数/轮次，
    如 {"S": 2}——插件版轮次活在主 agent 上下文，不落 csv）。
    """
    combined = {}
    combined.update(last_state or {})
    combined.update(extra_state or {})
    if not condition or not combined:
        return False, None
    parts = [p.strip() for p in condition.split(",") if p.strip()]
    matched_field = None
    for part in parts:
        # 比较运算符：>= <= > < 优先于 =
        op_match = None
        for op_sym in (">=", "<=", ">", "<"):
            if op_sym in part:
                op_match = op_sym
                break
        if op_match:
            c_field, c_val = part.split(op_match, 1)
            actual = combined.get(c_field)
            try:
                a, b = float(actual), float(c_val)
                ok = {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op_match]
            except (TypeError, ValueError):
                ok = False
            if not ok:
                return False, None
            matched_field = c_field
        elif "=" in part:
            c_field, c_val = part.split("=", 1)
            if str(combined.get(c_field)) == c_val:
                matched_field = c_field
            else:
                return False, None
    return matched_field is not None, matched_field


def next_field_by_op_table(op_table, last_state, extra_state=None):
    """op-table 匹配最后一行（+外部计数状态）→ 下一步（排它：条件互斥，顺序第一个命中）。

    last_state = state.csv 最后一行非空字段；extra_state = 主 agent 提供的计数（轮次/次数）。
    返回 {dispatch, mind} 或 None。
    """
    if not last_state and not extra_state:
        return None
    for op in op_table:
        matched, _ = condition_matches(op.get("condition", ""), last_state, extra_state)
        if matched:
            result = {"dispatch": op.get("dispatch")}
            if op.get("mind"):
                result["mind"] = op["mind"]
            return result
    return None


def cmd_materialize(task_dir):
    """设计收敛 → 执行态：复制 draft/steps.json + draft/minds.json 到任务根，
    并从装配表生成 op-table.json（条件路由表派生物）。

    物化后装配表是定稿，executor 读任务根的 steps.json。draft/ 保留作设计痕迹。
    """
    draft_steps = os.path.join(task_dir, "draft", "steps.json")
    draft_minds = os.path.join(task_dir, "draft", "minds.json")
    if not os.path.exists(draft_steps):
        sys.exit(f"缺少 {draft_steps}（先完成设计收敛：编排 + 校验 + 审计通过）")
    for name in ("steps.json", "minds.json"):
        src = os.path.join(task_dir, "draft", name)
        dst = os.path.join(task_dir, name)
        if os.path.exists(src):
            with open(src, "r", encoding="utf-8-sig") as f:
                content = f.read()
            with open(dst, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"物化: draft/{name} → {name}")
    # 生成 op-table.json（路由层派生物）
    data = load_steps(task_dir)
    modules = load_modules(task_dir)
    operations = generate_op_table(data["fields"], modules)
    op_path = os.path.join(task_dir, OP_TABLE_FILE)
    with open(op_path, "w", encoding="utf-8") as f:
        json.dump({"operations": operations}, f, ensure_ascii=False, indent=2)
    print(f"生成: {OP_TABLE_FILE}（{len(operations)} 条路由条件）")
    os.makedirs(os.path.join(task_dir, "artifacts"), exist_ok=True)
    return 0


def cmd_status(task_dir, extra_state=None):
    data = load_steps(task_dir)
    fields = data["fields"]
    state = load_state(task_dir)
    modules = load_modules(task_dir)
    op_table = generate_op_table(fields, modules)
    nxt_result = next_field_by_op_table(op_table, state, extra_state)
    nxt = nxt_result["dispatch"] if nxt_result else None
    nxt_mind = nxt_result.get("mind") if nxt_result else None
    print(f"任务 {data.get('task_id', '?')} v{data.get('version', '?')}")
    for f in fields:
        fid = f["field"]
        produce = field_produce(fid)
        deps = field_inputs(f)
        dep_s = f"  <- {','.join(sorted(deps))}" if deps else ""
        marker = " ◀ 下一步" if fid == nxt else ""
        if produce == "discriminate":
            if state.get(fid):
                print(f"  {fid:<28} [{produce}]  [判断={state[fid]}]{marker} {f.get('name', '')}{dep_s}")
            else:
                print(f"  {fid:<28} [{produce}]  {'未判别':<12}{marker} {f.get('name', '')}{dep_s}")
        else:
            # 完成性 = 产物文件存在（物化语义）；最后一行驱动下一步
            done = os.path.exists(os.path.join(task_dir, f"artifacts/{fid}.json"))
            st = "done" if done else "未执行"
            print(f"  {fid:<28} [{produce}]  {st:<12}{marker} {f.get('name', '')}{dep_s}")
    if nxt is None:
        print("  当前无下一步（初始态或已终止）")
    elif nxt_mind:
        print(f"  下一步 mind: {nxt_mind}（op-table 指定换脑）")


def cmd_ready(task_dir, extra_state=None):
    data = load_steps(task_dir)
    fields = data["fields"]
    state = load_state(task_dir)
    modules = load_modules(task_dir)
    op_table = generate_op_table(fields, modules)
    nxt_result = next_field_by_op_table(op_table, state, extra_state)
    nxt = nxt_result["dispatch"] if nxt_result else None
    nxt_mind = nxt_result.get("mind") if nxt_result else None
    if nxt is None:
        # 初始态：入口字段 = 未被任何串行 next 或并行组 next 指向的字段
        # （并行组内互相引用不算前驱）
        referenced = set()
        for f in fields:
            n = f.get("next")
            if n and n != "stop":
                referenced.add(n)
            pg = f.get("parallel")
            if pg and f.get("next"):
                referenced.add(f["next"])
        entries = [f["field"] for f in fields if f["field"] not in referenced]
        nxt = entries[0] if entries else (fields[0]["field"] if fields else None)
    if nxt is None or nxt == "stop":
        print("无可执行字段（任务已终止）")
        return
    f = get_field(fields, nxt)
    if f is None:
        print(f"op-table 指向不存在的字段: {nxt}")
        return

    # 并行组：若 nxt 在并行组内，列出整个组（并行执行）
    pgroup = field_parallel_group(fields, nxt)
    if pgroup:
        print(f"下一步（并行组，组内字段并行执行）：")
        for fid in pgroup:
            gf = get_field(fields, fid)
            if gf is None:
                continue
            produce = field_produce(fid)
            print(f"  {fid}  [{produce}]  {gf.get('name', '')}")
            print(f"      module: {gf['module']}")
            print(f"      产出: artifacts/{fid}.json")
        print(f"      组内全部完成后（check 各字段）→ {f.get('next', 'stop')}")
    else:
        produce = field_produce(nxt)
        print(f"下一步（op-table 驱动）：{nxt}  [{produce}]  {f.get('name', '')}")
        print(f"      module: {f['module']}")
        print(f"      产出: artifacts/{nxt}.json")
        if nxt_mind:
            print(f"      mind: {nxt_mind}（op-table 指定换脑）")
        print(f"      执行后调用 check {nxt} 验证推进")


# ---------- T3 派发（消息即任务，零引导语） ----------

def merge_schema(base, extra):
    if not extra:
        return base
    merged = {**base}
    if extra.get("required") or base.get("required"):
        merged["required"] = list(dict.fromkeys(
            [*(base.get("required") or []), *(extra.get("required") or [])]
        ))
    props = {**(base.get("properties") or {}), **(extra.get("properties") or {})}
    if props:
        merged["properties"] = props
    return merged


def cmd_t3(task_dir, fid, mind_override=None):
    """从装配表 + 模块 + mind 生成字段 T3 六件套。

    rules = 任务描述 + 模块 action/verify + 验收标准 + mind 指令 + 能力插槽
    schema = 模块 output_schema + enforce.schema
    forbidden = 通用 + mind constraint + 模块 forbidden + 装配表 forbidden
    mind_override：回退重跑时主 agent 指定思维（如 crusher 降本），覆盖字段/模块默认 mind
    """
    data = load_steps(task_dir)
    fields = data["fields"]
    field = get_field(fields, fid)
    if field is None:
        sys.exit(f"字段不存在: {fid}")
    modules = load_modules(task_dir)
    module = modules.get(field["module"])
    if module is None:
        sys.exit(f"模块不存在: {field['module']}（检查 modules.json）")
    minds = load_minds(task_dir)
    mind = minds.get(mind_override or field.get("mind_ref") or module.get("mind"))

    produce = field_produce(fid)
    rules = []
    if field.get("name"):
        rules.append(f"任务：{field['name']}（{field.get('field', fid)}，产出类别：{produce}）")
    if module.get("action"):
        rules.append(f"执行方式：{module['action']}")
    if module.get("verify"):
        rules.append(f"验证方式：{module['verify']}")
    for ac in field.get("acceptance_criteria", []):
        rules.append(f"验收标准（必须全部满足）：{ac}")
    if produce == "discriminate":
        routing = field.get("routing") or module.get("routing") or {}
        if routing:
            routes = "；".join(f"{k}→{v}" for k, v in routing.items())
            rules.append(f"路由（判断项值必须命中其一）：{routes}")

    # mind 指令（constraint 负向 / directive 正向）
    if mind:
        mp = mind.get("params") or {}
        mtype = mind.get("type", "directive")
        mrole = mind.get("role")
        mdensity = mind.get("forbidden_density") or (
            "dense" if mrole in ("audit", "review") else
            "zero" if mrole == "diagnose" else
            "precise"
        )
        if mtype == "constraint":
            mforbidden = mind.get("forbidden") or []
            rules.append(f"思维约束（{mind.get('name', mp.get('mode', 'mind'))}）：以下为硬约束，违反即不合格")
            for fb in mforbidden:
                rules.append(f"  禁止：{fb}")
            if mdensity == "dense":
                rules.append("  预设：产出可能有错——逐条质疑，找出所有可改进点，不要放行")
        elif mp.get("instruction"):
            rules.append(f"思维模式（{mind.get('name', mp.get('mode', 'mind'))}）：{mp['instruction']}")
        elif mp.get("principle"):
            rules.append(f"思维模式：{mp['principle']}")
        else:
            rules.append(f"思维模式（execute）：机械执行，按 input 与规则产出，不发挥、不加戏。")

    # 能力插槽：module.skills/mcp + 装配表覆盖
    skills = module.get("skills") or []
    mcps = module.get("mcp") or []
    if skills:
        rules.append(f"可用 skill（装配，必须加载/遵循）：{', '.join(skills)}")
    if mcps:
        rules.append(f"可用 MCP（装配，执行时调用）：{', '.join(mcps)}")

    # data：inputs 连线引用的依赖产物内容注入
    data_payload = {"input": {k: v for k, v in (field.get("inputs") or {}).items()}}
    for dep in sorted(field_inputs(field)):
        dep_file = f"artifacts/{dep}.json"
        fpath = os.path.join(task_dir, dep_file)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8-sig") as f:
                data_payload[dep] = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            with open(fpath, "r", encoding="utf-8-sig") as f:
                data_payload[dep] = f.read()

    # feedback 注入：inputs.feedback 指向的产物文件（回退上下文传递，如 discriminate 的 failure_reason）
    feedback_refs = field.get("inputs", {}).get("feedback")
    if isinstance(feedback_refs, str):
        feedback_refs = [feedback_refs]
    if feedback_refs:
        fb_list = []
        for fb_path in feedback_refs:
            if not isinstance(fb_path, str):
                continue
            fpath = os.path.join(task_dir, fb_path)
            if not os.path.exists(fpath):
                continue
            try:
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    fb_list.append(json.load(f))
            except (json.JSONDecodeError, UnicodeDecodeError):
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    fb_list.append(f.read())
        if fb_list:
            data_payload["feedback"] = fb_list

    # forbidden 合并：通用 + enforce + mind constraint + 模块 + 装配表
    enforce = mind.get("enforce") if mind else None
    enforce_fill = (enforce or {}).get("fill") or []
    enforce_schema = (enforce or {}).get("schema") or {}
    enforce_forbidden = (enforce or {}).get("forbidden") or []
    enforce_check = (enforce or {}).get("check")
    constraint_forbidden = (mind.get("forbidden") or []) if (mind and mind.get("type") == "constraint") else []
    module_forbidden = module.get("forbidden") or []
    field_forbidden = field.get("forbidden") or []

    t3 = {
        "fill": (module.get("output_schema") or {}).get("required", []) + enforce_fill,
        "rules": rules,
        "schema": merge_schema(module.get("output_schema") or {}, enforce_schema),
        "data": data_payload,
        "write": f"artifacts/{fid}.json",
        "forbidden": [
            "响应正文只允许输出产物内容，禁止散文、解释、思考过程、Markdown 包裹",
            "产物必须写入 write 指定的相对路径（相对任务目录），禁止写其他路径",
            "产物必须满足全部验收标准（rules 中逐条列出），机械可检查",
            "不得引用输入数据中不存在的事实",
            "禁止修改输入数据或依赖产物——输入来自物化文件，不可变（LLM 最小阻力绕过路径第一优先是改输入）",
            "JSON 产物必须是合法 JSON，字段严格符合 schema（禁止多余顶层字段）",
        ] + enforce_forbidden + constraint_forbidden + module_forbidden + field_forbidden,
        "check": enforce_check,
    }
    ddir = os.path.join(task_dir, "dispatch")
    os.makedirs(ddir, exist_ok=True)
    tfile = os.path.join(ddir, f"{fid}.t3.json")
    with open(tfile, "w", encoding="utf-8") as f:
        json.dump(t3, f, ensure_ascii=False, indent=2)
    print(f"T3 已写入 {tfile}")
    print(f"派发 prompt: T3FILE:v1 读取 {tfile} 并按内容执行。产出写入 {task_dir} 下的 write 相对路径。")
    return 0


def cmd_check(task_dir, fid):
    """前置门禁（依赖产物已物化）→ 产物检查 → state.csv 追加一步行。

    物化语义：字段完成性 = artifacts/<field>.json 存在。
    - generate：产物 JSON 验证通过 → 追加状态行（passed），完成
    - discriminate：产物判断值 ∈ routing keys → 追加判断行，路由生效
    - 回修：路由目标产物存在 → 删除产物文件（物化语义：没了=未完成），下游依赖者同样失效
    state.csv 每行 = 一步，只填当步字段，不继承；op-table 只读最后一行。
    """
    data = load_steps(task_dir)
    fields = data["fields"]
    field = get_field(fields, fid)
    if field is None:
        sys.exit(f"字段不存在: {fid}")

    # 前置门禁：依赖产物已物化
    ok, why = prerequisites_met(task_dir, fields, field)
    if not ok:
        sys.exit(f"前置门禁拦截: {fid} — {why}")

    # 本字段必须已有产物（subagent 已执行），否则 check 无对象
    art_file = os.path.join(task_dir, f"artifacts/{fid}.json")
    if not os.path.exists(art_file):
        sys.exit(f"产物缺失: {art_file}（先执行本字段再 check）")

    modules = load_modules(task_dir)
    module = modules.get(field["module"], {})
    minds = load_minds(task_dir)
    mind = minds.get(field.get("mind_ref") or module.get("mind"))

    ok, issues = check_artifacts(task_dir, field, module)
    if ok:
        ok2, issues2 = check_mind_gates(task_dir, field, mind)
        ok = ok and ok2
        issues = issues + issues2

    produce = field_produce(fid)
    pgroup = field_parallel_group(fields, fid)
    if not ok:
        append_state(task_dir, fields, fid, "failed", note=f"FAIL {'; '.join(issues)[:60]}", parallel_group=pgroup)
        print(f"{fid} FAILED ✗")
        for i in issues:
            print(f"  ✗ {i}")
        return 1

    # generate：产物验证通过 → 追加/填充状态行（并行组同行填充）
    if produce == "generate":
        append_state(task_dir, fields, fid, "passed", note="执行完成", parallel_group=pgroup)
        print(f"{fid} PASSED ✓")
        return 0

    # discriminate：读判断值 → 追加判断行 → 路由
    routing = field.get("routing") or module.get("routing") or {}
    try:
        with open(art_file, "r", encoding="utf-8-sig") as f:
            content = json.load(f)
    except Exception:
        content = {}
    verdict_field = verdict_field_name(content, module)
    verdict = content.get(verdict_field) if verdict_field else None
    if verdict is None:
        print(f"  ⚠ 判别式 {fid} 未找到判断项值（routing 无法生效）")
        append_state(task_dir, fields, fid, "passed", note="判断项缺失", parallel_group=pgroup)
        return 0
    if verdict not in routing:
        print(f"  ✗ 判别式 {fid} 判断值 {verdict} 不在路由合法域 {sorted(routing.keys())}")
        append_state(task_dir, fields, fid, "failed", note=f"路由非法 {verdict}", parallel_group=pgroup)
        return 1

    append_state(task_dir, fields, fid, verdict, note=f"判别 {verdict}", parallel_group=pgroup)
    print(f"{fid} 判断 = {verdict} ✓")
    # 路由由 op-table 自然驱动：最后一行已是 <fid>=<verdict>，
    # next_field_by_op_table 将匹配 routing 目标（含回修指向 generate_01）。
    target = routing.get(verdict)
    if target == "stop":
        print(f"  → 路由: {verdict} → stop（任务终止）")
    else:
        print(f"  → 路由: {verdict} → {target}（op-table 据此指向下一步，无需删产物）")
    return 0


def cmd_retry(task_dir, fid):
    """重试 = 追加 retry 标记行（产物保留，重跑时覆盖写）。"""
    data = load_steps(task_dir)
    field = get_field(data["fields"], fid)
    if field is None:
        sys.exit(f"字段不存在: {fid}")
    append_state(task_dir, data["fields"], fid, "retry", note="重试")
    print(f"{fid} → retry（重跑后覆盖产物）")


def cmd_reset(task_dir, fid):
    """重新编排后重置 = 追加 reset 标记行。"""
    data = load_steps(task_dir)
    field = get_field(data["fields"], fid)
    if field is None:
        sys.exit(f"字段不存在: {fid}")
    append_state(task_dir, data["fields"], fid, "reset", note="重新编排后重置")
    print(f"{fid} → reset（重新编排完成）")


def parse_extra_state(argv):
    """解析 --state '{"S":2}' → 外部计数状态（主 agent 提供轮次/次数）。"""
    extra = {}
    if "--state" in argv:
        idx = argv.index("--state")
        if idx + 1 < len(argv):
            try:
                extra = json.loads(argv[idx + 1])
            except json.JSONDecodeError:
                sys.exit("--state 必须是合法 JSON，如 '{\"S\": 2}'")
    return extra


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    task_dir = sys.argv[2]
    extra = parse_extra_state(sys.argv)
    if cmd == "status":
        cmd_status(task_dir, extra)
    elif cmd == "ready":
        cmd_ready(task_dir, extra)
    elif cmd == "t3":
        if len(sys.argv) < 4:
            sys.exit("用法: executor.py t3 <task_dir> <field> [--mind <mind_id>]")
        mind_override = None
        if "--mind" in sys.argv:
            idx = sys.argv.index("--mind")
            if idx + 1 < len(sys.argv):
                mind_override = sys.argv[idx + 1]
        sys.exit(cmd_t3(task_dir, sys.argv[3], mind_override))
    elif cmd == "check":
        if len(sys.argv) < 4:
            sys.exit("用法: executor.py check <task_dir> <field>")
        sys.exit(cmd_check(task_dir, sys.argv[3]))
    elif cmd == "retry":
        if len(sys.argv) < 4:
            sys.exit("用法: executor.py retry <task_dir> <field>")
        cmd_retry(task_dir, sys.argv[3])
    elif cmd == "reset":
        if len(sys.argv) < 4:
            sys.exit("用法: executor.py reset <task_dir> <field>")
        cmd_reset(task_dir, sys.argv[3])
    elif cmd == "materialize":
        sys.exit(cmd_materialize(task_dir))
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
