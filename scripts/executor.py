#!/usr/bin/env python3
"""
executor.py — 状态机执行器（机械化执行的强制者）

职责：
  1. 状态转移的唯一入口：转移表硬编码，非法转移拒绝（agent 不能手改状态）
  2. 前置门禁：依赖未 passed 的步骤不允许执行
  3. 后置门禁：产物未通过检查不允许标记 passed
  4. 失败轨迹：记录 failure_log；同一步 3 次同类失败自动标记 needs_reorchestration
  5. 断点续跑：状态唯一真相源 = steps.json 文件，原子写回
  6. mind 具象化：mind 的 enforce 四层（fill/schema/forbidden/check）合并进 T3 派发；
     check 机械执行证据门禁（evidence_in_source）——mind 从散文升级为协议

约束与执行分离：executor 只做机械约束，任务执行由 subagent 完成。

命令：
  python executor.py status <task_dir>            # 显示状态机全景
  python executor.py ready <task_dir>             # 列出可执行步骤（前置满足 + pending）
  python executor.py check <task_dir> <step_id>   # 验证产物并推进状态（passed/failed）
  python executor.py retry <task_dir> <step_id>   # failed → pending（重试）
  python executor.py reset <task_dir> <step_id>   # needs_reorchestration → pending（重新编排后）

退出码：0=正常, 1=检查失败/非法操作, 2=用法错误
"""
import json
import os
import sys
import tempfile
from collections import deque

# ---- 转移表：状态机的唯一合法转换集合 ----
VALID_TRANSITIONS = {
    "pending": ["running"],
    "running": ["passed", "failed", "needs_reorchestration"],  # 执行后判定结构性失败 → 直接进重新编排
    "failed": ["pending"],                 # 重试（retry）
    "needs_reorchestration": ["pending"],  # 重新编排后重置（reset）
    "passed": [],
    "skipped": [],
}

MAX_FAILURES = 3  # 同一步同类失败阈值 → 自动 needs_reorchestration

STEP_FILE = "steps.json"


# ---------- 文件 IO ----------

def load_steps(task_dir):
    path = os.path.join(task_dir, STEP_FILE)
    if not os.path.exists(path):
        sys.exit(f"缺少 {STEP_FILE}（先运行编排生成三件套）")
    with open(path, "r", encoding="utf-8-sig") as f:  # utf-8-sig 容忍 BOM
        return json.load(f)


def save_steps(task_dir, data):
    """原子写回：tmp 文件 + os.replace，避免写一半损坏。"""
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


def get_step(steps, sid):
    for s in steps:
        if s["id"] == sid:
            return s
    return None


def transition(steps, sid, new_status):
    """状态转移唯一入口：非法转移直接拒绝。"""
    step = get_step(steps, sid)
    if step is None:
        sys.exit(f"步骤不存在: {sid}")
    cur = step["status"]
    if new_status not in VALID_TRANSITIONS.get(cur, []):
        sys.exit(f"非法转移: {sid} {cur} → {new_status}（转移表不允许）")
    step["status"] = new_status


def prerequisites_met(steps, step):
    for dep in step.get("depends_on", []):
        ds = get_step(steps, dep)
        if ds is None:
            return False, f"依赖 {dep} 不存在"
        if ds["status"] != "passed":
            return False, f"依赖 {dep} 状态为 {ds['status']}（须 passed）"
    return True, ""


def record_failure(step, reason, cls):
    rt = step.setdefault("runtime", {})
    rt["failures"] = rt.get("failures", 0) + 1
    log = rt.setdefault("failure_log", [])
    log.append({"at": reason, "reason": reason, "class": cls})


# ---------- 产物检查（后置门禁，复用 compare 逻辑） ----------

def check_artifacts(task_dir, step):
    """返回 (ok, issues[])。

    语义：output.schema.required 非空 = 期望结构化 JSON 产物，解析失败/缺字段 → 不通过；
    required 为空 = 非 JSON 产物（md/txt 等），只检查存在性。
    """
    out = step.get("output") or {}
    fname = out.get("file")
    if not fname:
        return True, []
    fpath = os.path.join(task_dir, fname)
    issues = []
    if not os.path.exists(fpath):
        return False, [f"产物缺失 {fname}"]
    required = (out.get("schema") or {}).get("required", [])
    if required:
        try:
            # utf-8-sig 容忍 BOM；解析失败 = 坏 JSON = 不通过（不是宽容跳过）
            with open(fpath, "r", encoding="utf-8-sig") as f:
                content = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return False, [f"产物 {fname} 不是合法 JSON（期望字段 {required}）: {e}"]
        for field in required:
            if field not in content:
                issues.append(f"产物 {fname} 缺少字段 {field}")
    return (len(issues) == 0), issues


def collect_field_values(node, field):
    """递归收集产物中所有名为 field 的值（字符串或字符串数组展开）。"""
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
    """折叠空白用于子串比较（材料原文换行/缩进与 evidence 摘录可能不同）。"""
    return " ".join(s.split())


def check_mind_gates(task_dir, step, minds):
    """执行 mind 的 enforce.check 机械门禁（evidence_in_source 原文验证）。

    返回 (ok, issues[])。产物中 field 的每个值必须作为子串出现在
    source 文件中（空白折叠后比较）——路径引用/自指引用会被拒。
    """
    out = step.get("output") or {}
    fname = out.get("file")
    if not fname:
        return True, []
    mind = minds.get(step.get("mind_ref"))
    if not mind:
        return True, []
    check = (mind.get("enforce") or {}).get("check")
    if not check or check.get("type") != "evidence_in_source":
        return True, []

    fpath = os.path.join(task_dir, fname)
    if not os.path.exists(fpath):
        return True, []  # 产物缺失由 check_artifacts 拦，这里不重复报
    try:
        with open(fpath, "r", encoding="utf-8-sig") as f:
            content = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return True, []  # 非法 JSON 由 check_artifacts 拦

    src_path = os.path.join(task_dir, check["source"])
    if not os.path.exists(src_path):
        return False, [f"mind 门禁 {check['type']}: 证据来源文件缺失 {check['source']}"]
    with open(src_path, "r", encoding="utf-8-sig") as f:
        src_norm = normalize_text(f.read())

    field = check["field"]
    values = collect_field_values(content, field)
    issues = []
    for v in values:
        if not v.strip():
            issues.append(f"mind 门禁 {check['type']}: {field} 存在空值")
        elif normalize_text(v) not in src_norm:
            issues.append(f"mind 门禁 {check['type']}: {field} 值不在来源文件中（路径引用/自指？）: {v[:60]}")
    return (len(issues) == 0), issues


# ---------- 命令实现 ----------

def cmd_status(task_dir):
    data = load_steps(task_dir)
    steps = data["steps"]
    print(f"任务 {data.get('task_id', '?')} v{data.get('version', '?')}")
    for s in steps:
        rt = s.get("runtime", {})
        fails = rt.get("failures", 0)
        flag = f"  (failures={fails})" if fails else ""
        deps = f"  <- {','.join(s['depends_on'])}" if s.get("depends_on") else ""
        print(f"  {s['id']}  {s['status']:<22} {s['name']}{flag}{deps}")


def cmd_ready(task_dir):
    data = load_steps(task_dir)
    steps = data["steps"]
    ready = []
    blocked = []
    for s in steps:
        if s["status"] != "pending":
            continue
        ok, why = prerequisites_met(steps, s)
        if ok:
            ready.append(s)
        else:
            blocked.append((s, why))
    if ready:
        print("可执行步骤（执行后调用 check <step_id> 验证推进）：")
        for s in ready:
            print(f"  {s['id']}  {s['name']}")
            print(f"      op: {s.get('op_ref')}  mind: {s.get('mind_ref','-')}")
            print(f"      产出: {s['output'].get('file')}")
    if blocked:
        print("暂不可执行（前置未满足）：")
        for s, why in blocked:
            print(f"  {s['id']}  {s['name']}  — {why}")


# ---------- T3 派发（消息即任务，零引导语） ----------

def load_table(task_dir, fname, key):
    path = os.path.join(task_dir, fname)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f).get(key, [])


def merge_schema(base, extra):
    """合并产物 schema 与 enforce.schema（extra 覆盖同名键，required 并集）。

    两者都是 {required: [...], properties: {...}} 形态的宽松结构。
    """
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


def cmd_t3(task_dir, sid):
    """从三件套 + 依赖产物生成该步骤的 T3 六件套（fill/rules/schema/data/write/forbidden），
    写入 dispatch/<sid>.t3.json，并打印派发 prompt（T3FILE:v1 零引导语）。
    """
    steps = load_steps(task_dir)["steps"]
    step = get_step(steps, sid)
    if step is None:
        sys.exit(f"步骤不存在: {sid}")
    ops = {o["id"]: o for o in load_table(task_dir, "op-table.json", "operations")}
    minds = {m["id"]: m for m in load_table(task_dir, "minds.json", "minds")}
    op = ops.get(step.get("op_ref"))
    mind = minds.get(step.get("mind_ref"))

    # rules：做什么 + 怎么做 + 怎么验证 + 验收标准 + 思维模式指令
    rules = []
    if step.get("description"):
        rules.append(f"任务：{step['description']}")
    if op and op.get("action"):
        rules.append(f"执行方式：{op['action']}")
    if op and op.get("verify"):
        rules.append(f"验证方式：{op['verify']}")
    for ac in step.get("acceptance_criteria", []):
        rules.append(f"验收标准（必须全部满足）：{ac}")
    if mind:
        mp = mind.get("params") or {}
        if mp.get("instruction"):
            rules.append(f"思维模式（{mind.get('name', mp.get('mode', 'mind'))}）：{mp['instruction']}")
        elif mp.get("mode") == "audit":
            rules.append(f"思维模式（audit）：只可用可验证事实为据；每条结论必须附证据引用（指向输入数据中真实存在的条目）；无法溯源的信息不得写入产物。")
        elif mp.get("principle"):
            rules.append(f"思维模式：{mp['principle']}")
        else:
            rules.append(f"思维模式（execute）：机械执行，按 input 与规则产出，不发挥、不加戏。")

    # mind 具象化：enforce 四层（fill/schema/forbidden/check）合并进派发——mind 从散文升级为协议
    enforce = mind.get("enforce") if mind else None
    enforce_fill = (enforce or {}).get("fill") or []
    enforce_schema = (enforce or {}).get("schema") or {}
    enforce_forbidden = (enforce or {}).get("forbidden") or []
    enforce_check = (enforce or {}).get("check")

    # 能力插槽：op.required_skills/required_mcp + step.extra_skills/extra_mcp（合并去重）→ 注入 rules
    skills = list(dict.fromkeys([*(op.get("required_skills") or []), *(step.get("extra_skills") or [])]))
    mcps = list(dict.fromkeys([*(op.get("required_mcp") or []), *(step.get("extra_mcp") or [])]))
    if skills:
        rules.append(f"可用 skill（装配，必须加载/遵循）：{', '.join(skills)}")
    if mcps:
        rules.append(f"可用 MCP（装配，执行时调用）：{', '.join(mcps)}")

    # data：input + 依赖产物内容注入（JSON 或 markdown 原文）
    data = {"input": step.get("input") or {}}
    for dep in step.get("depends_on", []):
        ds = get_step(steps, dep)
        if ds is None:
            continue
        fname = (ds.get("output") or {}).get("file")
        if not fname:
            continue
        fpath = os.path.join(task_dir, fname)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8-sig") as f:
                data[dep] = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            with open(fpath, "r", encoding="utf-8-sig") as f:
                data[dep] = f.read()

    t3 = {
        "fill": (step.get("output") or {}).get("schema", {}).get("required", []) + enforce_fill,
        "rules": rules,
        "schema": merge_schema((step.get("output") or {}).get("schema", {}), enforce_schema),
        "data": data,
        "write": (step.get("output") or {}).get("file", ""),
        "forbidden": [
            "响应正文只允许输出产物内容，禁止散文、解释、思考过程、Markdown 包裹",
            "产物必须写入 write 指定的相对路径（相对任务目录），禁止写其他路径",
            "产物必须满足全部验收标准（rules 中逐条列出），机械可检查",
            "不得引用输入数据中不存在的事实",
            "JSON 产物必须是合法 JSON，字段严格符合 schema（禁止多余顶层字段）",
        ] + enforce_forbidden,
        "check": enforce_check,
    }
    ddir = os.path.join(task_dir, "dispatch")
    os.makedirs(ddir, exist_ok=True)
    tfile = os.path.join(ddir, f"{sid}.t3.json")
    with open(tfile, "w", encoding="utf-8") as f:
        json.dump(t3, f, ensure_ascii=False, indent=2)
    print(f"T3 已写入 {tfile}")
    print(f"派发 prompt: T3FILE:v1 读取 {tfile} 并按内容执行。产出写入 {task_dir} 下的 write 相对路径。")
    return 0
    if not ready:
        # 无 ready 且无 blocked 说明全部完成或全部 failed
        pending = [s for s in steps if s["status"] == "pending"]
        if not pending:
            print("无 pending 步骤：任务完成或存在 needs_reorchestration 步骤（见 status）")


def cmd_check(task_dir, sid):
    """前置门禁 → pending→running → 后置门禁 → passed/failed。"""
    data = load_steps(task_dir)
    steps = data["steps"]
    step = get_step(steps, sid)
    if step is None:
        sys.exit(f"步骤不存在: {sid}")
    if step["status"] not in ("pending", "running", "failed"):
        sys.exit(f"步骤 {sid} 当前状态 {step['status']}，不能 check")

    # 前置门禁
    ok, why = prerequisites_met(steps, step)
    if not ok:
        sys.exit(f"前置门禁拦截: {sid} — {why}")

    transition(steps, sid, "running")

    # 后置门禁：产物检查
    ok, issues = check_artifacts(task_dir, step)

    # mind 具象化门禁：evidence 原文验证（mind 从散文升级为协议，check 机械执行）
    if ok:
        minds = {m["id"]: m for m in load_table(task_dir, "minds.json", "minds")}
        ok2, issues2 = check_mind_gates(task_dir, step, minds)
        ok = ok and ok2
        issues = issues + issues2

    if ok:
        transition(steps, sid, "passed")
        save_steps(task_dir, data)
        print(f"{sid} PASSED ✓")
        return 0
    else:
        record_failure(step, "; ".join(issues), "artifact_missing")
        fails = step["runtime"]["failures"]
        if fails >= MAX_FAILURES:
            transition(steps, sid, "needs_reorchestration")
            save_steps(task_dir, data)
            print(f"{sid} FAILED ✗（第 {fails} 次失败，达阈值 {MAX_FAILURES}）")
            print(f"  标记 needs_reorchestration → Stage 3：重新审计编排，改三件套后 reset")
            for i in issues:
                print(f"  ✗ {i}")
            return 1
        transition(steps, sid, "failed")
        save_steps(task_dir, data)
        print(f"{sid} FAILED ✗（failures={fails}，达 {MAX_FAILURES} 次将触发重新编排）")
        for i in issues:
            print(f"  ✗ {i}")
        return 1


def cmd_retry(task_dir, sid):
    data = load_steps(task_dir)
    step = get_step(data["steps"], sid)
    if step is None:
        sys.exit(f"步骤不存在: {sid}")
    if step["status"] != "failed":
        sys.exit(f"只有 failed 步骤可 retry（当前 {step['status']}）")
    transition(data["steps"], sid, "pending")
    save_steps(task_dir, data)
    print(f"{sid} → pending（重试）")


def cmd_reset(task_dir, sid):
    data = load_steps(task_dir)
    step = get_step(data["steps"], sid)
    if step is None:
        sys.exit(f"步骤不存在: {sid}")
    if step["status"] != "needs_reorchestration":
        sys.exit(f"只有 needs_reorchestration 步骤可 reset（当前 {step['status']}）")
    transition(data["steps"], sid, "pending")
    # 重新编排后清空失败计数
    step.pop("runtime", None)
    save_steps(task_dir, data)
    print(f"{sid} → pending（重新编排完成，失败计数已清零）")


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
            sys.exit("用法: executor.py t3 <task_dir> <step_id>")
        sys.exit(cmd_t3(task_dir, sys.argv[3]))
    elif cmd == "check":
        if len(sys.argv) < 4:
            sys.exit("用法: executor.py check <task_dir> <step_id>")
        sys.exit(cmd_check(task_dir, sys.argv[3]))
    elif cmd == "retry":
        if len(sys.argv) < 4:
            sys.exit("用法: executor.py retry <task_dir> <step_id>")
        cmd_retry(task_dir, sys.argv[3])
    elif cmd == "reset":
        if len(sys.argv) < 4:
            sys.exit("用法: executor.py reset <task_dir> <step_id>")
        cmd_reset(task_dir, sys.argv[3])
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    # Windows 中文环境默认 GBK 编码，print 非 ASCII（✓/✗/→）会崩；强制 UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
