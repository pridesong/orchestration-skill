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


def append_state(task_dir, fields, fid, value, note=""):
    """追加一行：**只填当前步的 fid 列**，其他列全空（无继承）。

    每行 = 一步的产出记录；op-table 只读最后一行。generate 行填状态，
    discriminate 行填判断值（verdict 即状态）。
    """
    path = os.path.join(task_dir, STATE_FILE)
    import datetime
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    cols = state_columns(fields)
    row = {c: "" for c in cols}
    row[fid] = value
    row["_ts"] = ts
    row["_note"] = note
    is_new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(cols)
        writer.writerow([row.get(c, "") for c in cols])


def state_status(task_dir, fid):
    return load_state(task_dir).get(fid, "")


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
    """字段依赖：inputs 连线中的前序字段名 + 模块 input_schema 引用的来源。"""
    deps = set()
    for v in (field.get("inputs") or {}).values():
        if isinstance(v, str) and (GEN_FIELD.match(v) or DIS_FIELD.match(v)):
            deps.add(v)
    return deps


def routing_targets(field):
    """判别式字段的路由目标（routing 值的字段部分）。"""
    targets = set()
    for v in (field.get("routing") or {}).values():
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
    if field_produce(field["field"]) == "discriminate":
        routing = field.get("routing") or module.get("routing") or {}
        if not routing:
            issues.append(f"判别字段 {field['field']} 无 routing（模块与装配表均未定义）")
        for item in required:
            if item in content and isinstance(content[item], str) and routing:
                if content[item] not in routing:
                    issues.append(
                        f"产物 {out_file} 字段 {item}={content[item]} 不在路由合法域 {sorted(routing.keys())}"
                    )
    return (len(issues) == 0), issues


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

def generate_op_table(fields, modules):
    """从装配表推导 op-table.json（条件路由表）。

    规则：
      generate 字段 → {"condition": "<field>=passed", "dispatch": "<下一个依赖该字段的字段>"}
      discriminate 字段 → {"condition": "<field>=<verdict>", "dispatch": "<routing 目标>"}
    供审计/可视化；executor 运行时仍直接读装配表 routing（op-table 是派生物）。
    """
    operations = []
    field_ids = [f["field"] for f in fields]
    for f in fields:
        fid = f["field"]
        produce = field_produce(fid)
        module = modules.get(f["module"], {})
        if produce == "generate":
            operations.append({
                "condition": f"{fid}=passed",
                "dispatch": "next",
                "side_effect": None,
            })
        elif produce == "discriminate":
            routing = f.get("routing") or module.get("routing") or {}
            for verdict, target in routing.items():
                operations.append({
                    "condition": f"{fid}={verdict}",
                    "dispatch": target,
                    "side_effect": "reset" if target != "stop" and target in field_ids else None,
                })
    return operations


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


def cmd_status(task_dir):
    data = load_steps(task_dir)
    fields = data["fields"]
    state = load_state(task_dir)
    print(f"任务 {data.get('task_id', '?')} v{data.get('version', '?')}")
    for f in fields:
        fid = f["field"]
        produce = field_produce(fid)
        deps = field_inputs(f)
        dep_s = f"  <- {','.join(sorted(deps))}" if deps else ""
        # 完成性 = 产物文件存在；判别式额外显示最后判定值
        done = os.path.exists(os.path.join(task_dir, f"artifacts/{fid}.json"))
        if produce == "discriminate" and state.get(fid):
            st = f"[判断={state[fid]}]"
        else:
            st = "done" if done else "pending"
        print(f"  {fid:<28} [{produce}]  {st:<12} {f.get('name', '')}{dep_s}")


def cmd_ready(task_dir):
    data = load_steps(task_dir)
    fields = data["fields"]
    ready = []
    blocked = []
    for f in fields:
        fid = f["field"]
        if os.path.exists(os.path.join(task_dir, f"artifacts/{fid}.json")):
            continue  # 已物化 = 已完成
        ok, why = prerequisites_met(task_dir, fields, f)
        if ok:
            ready.append(f)
        else:
            blocked.append((f, why))
    if ready:
        print("可执行字段（执行后调用 check <field> 验证推进）：")
        for f in ready:
            produce = field_produce(f["field"])
            print(f"  {f['field']}  [{produce}]  {f.get('name', '')}")
            print(f"      module: {f['module']}")
            print(f"      产出: artifacts/{f['field']}.json")
    if blocked:
        print("暂不可执行（前置未满足）：")
        for f, why in blocked:
            print(f"  {f['field']}  {f.get('name', '')}  — {why}")


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


def cmd_t3(task_dir, fid):
    """从装配表 + 模块 + mind 生成字段 T3 六件套。

    rules = 任务描述 + 模块 action/verify + 验收标准 + mind 指令 + 能力插槽
    schema = 模块 output_schema + enforce.schema
    forbidden = 通用 + mind constraint + 模块 forbidden + 装配表 forbidden
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
    mind = minds.get(field.get("mind_ref") or module.get("mind"))

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
    if not ok:
        append_state(task_dir, fields, fid, "failed", note=f"FAIL {'; '.join(issues)[:60]}")
        print(f"{fid} FAILED ✗")
        for i in issues:
            print(f"  ✗ {i}")
        return 1

    # generate：产物验证通过 → 追加状态行
    if produce == "generate":
        append_state(task_dir, fields, fid, "passed", note="执行完成")
        print(f"{fid} PASSED ✓")
        return 0

    # discriminate：读判断值 → 追加判断行 → 路由
    routing = field.get("routing") or module.get("routing") or {}
    try:
        with open(art_file, "r", encoding="utf-8-sig") as f:
            content = json.load(f)
    except Exception:
        content = {}
    verdict = None
    for item in (module.get("output_schema") or {}).get("required", []):
        if item in content and isinstance(content[item], str):
            verdict = content[item]
            break
    if verdict is None:
        print(f"  ⚠ 判别式 {fid} 未找到判断项值（routing 无法生效）")
        append_state(task_dir, fields, fid, "passed", note="判断项缺失")
        return 0
    if verdict not in routing:
        print(f"  ✗ 判别式 {fid} 判断值 {verdict} 不在路由合法域 {sorted(routing.keys())}")
        append_state(task_dir, fields, fid, "failed", note=f"路由非法 {verdict}")
        return 1

    append_state(task_dir, fields, fid, verdict, note=f"判别 {verdict}")
    print(f"{fid} 判断 = {verdict} ✓")
    target = routing.get(verdict)
    if target == "stop":
        print(f"  → 路由: {verdict} → stop（任务终止）")
    elif target:
        t_field = get_field(fields, target)
        if t_field is None:
            print(f"  → 路由: {verdict} → {target}（目标字段不存在，仅提示）")
        else:
            # 物化回修：目标产物存在 → 删除（=未完成），下游依赖者产物同步删除
            removed = []
            for ff in fields:
                dep_ok = True
                for dep in field_inputs(ff):
                    if dep == target and ff["field"] != target:
                        dep_ok = False
                        break
                if ff["field"] == target or not dep_ok:
                    fp = os.path.join(task_dir, f"artifacts/{ff['field']}.json")
                    if os.path.exists(fp):
                        os.remove(fp)
                        removed.append(ff["field"])
            print(f"  → 路由: {verdict} → {target}（回修：删除产物 {'、'.join(removed) or '(无)'}）")
    return 0


def cmd_retry(task_dir, fid):
    """重试 = 删除本字段产物（物化语义：产物没了=未完成=可重跑）。"""
    data = load_steps(task_dir)
    field = get_field(data["fields"], fid)
    if field is None:
        sys.exit(f"字段不存在: {fid}")
    fp = os.path.join(task_dir, f"artifacts/{fid}.json")
    if not os.path.exists(fp):
        sys.exit(f"产物不存在: {fid}（无产物可重试）")
    os.remove(fp)
    append_state(task_dir, data["fields"], fid, "retry", note="重试（产物删除）")
    print(f"{fid} → 未完成（产物已删除，可重跑）")


def cmd_reset(task_dir, fid):
    """重新编排后重置 = 删除本字段产物（回到未完成态）。"""
    data = load_steps(task_dir)
    field = get_field(data["fields"], fid)
    if field is None:
        sys.exit(f"字段不存在: {fid}")
    fp = os.path.join(task_dir, f"artifacts/{fid}.json")
    if os.path.exists(fp):
        os.remove(fp)
    append_state(task_dir, data["fields"], fid, "reset", note="重新编排后重置")
    print(f"{fid} → 未完成（产物已删除，可重跑）")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    task_dir = sys.argv[2]
    if cmd == "status":
        cmd_status(task_dir)
    elif cmd == "ready":
        cmd_ready(task_dir)
    elif cmd == "t3":
        if len(sys.argv) < 4:
            sys.exit("用法: executor.py t3 <task_dir> <field>")
        sys.exit(cmd_t3(task_dir, sys.argv[3]))
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
