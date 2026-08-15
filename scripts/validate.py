#!/usr/bin/env python3
"""
validate.py — 三件套机械校验（第一层审计的硬门禁）

检查项：
  1. 三个文件存在且为合法 JSON
  2. 基本结构（必需字段）
  3. 步骤 id 唯一
  4. 引用完整性：op_ref / mind_ref 必须存在于对应表
  5. depends_on 引用存在且依赖图无环（Kahn 拓扑排序）
  6. minds.apply_to 引用的步骤必须存在

用法: python validate.py <task_dir>
退出码: 0=通过, 1=不通过, 2=用法错误

不依赖任何第三方库。偏离对抗原则：约束走 schema 不走散文，本脚本是机械检查，
不依赖 agent 自觉。
"""
import json
import os
import sys
from collections import deque

REQUIRED_FILES = ["steps.json", "op-table.json", "minds.json"]


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:  # utf-8-sig 容忍 BOM
        return json.load(f)


def check_steps(steps, op_ids, mind_ids, errors):
    step_ids = [s.get("id") for s in steps]

    # id 唯一
    seen = set()
    for sid in step_ids:
        if sid in seen:
            errors.append(f"steps.json: 重复步骤 id: {sid}")
        seen.add(sid)

    for s in steps:
        sid = s.get("id", "?")
        # 必需字段
        for field in ("id", "name", "output", "depends_on", "op_ref", "acceptance_criteria", "status"):
            if field not in s:
                errors.append(f"steps.json: 步骤 {sid} 缺少字段 {field}")
        # 引用完整性
        op_ref = s.get("op_ref")
        if op_ref and op_ref not in op_ids:
            errors.append(f"steps.json: 步骤 {sid} 引用不存在的 op: {op_ref}")
        mind_ref = s.get("mind_ref")
        if mind_ref and mind_ref not in mind_ids:
            errors.append(f"steps.json: 步骤 {sid} 引用不存在的 mind: {mind_ref}")
        # 依赖引用存在
        for dep in s.get("depends_on", []):
            if dep not in seen:
                errors.append(f"steps.json: 步骤 {sid} 依赖不存在的步骤: {dep}")
        # 验收标准非空
        if not s.get("acceptance_criteria"):
            errors.append(f"steps.json: 步骤 {sid} 缺少 acceptance_criteria（验收标准必须可机械检查）")
        # 产物路径
        out = s.get("output")
        if out and not out.get("file"):
            errors.append(f"steps.json: 步骤 {sid} 的 output 缺少 file（产物必须物化）")
        # 能力插槽（step 级补充）：extra_skills / extra_mcp 必须是 string 数组
        for slot in ("extra_skills", "extra_mcp"):
            v = s.get(slot)
            if v is not None and (not isinstance(v, list) or not all(isinstance(x, str) and x for x in v)):
                errors.append(f"steps.json: 步骤 {sid} 的 {slot} 必须是非空字符串数组（或缺失）")


def check_acyclic(steps, errors):
    """Kahn 拓扑排序检测依赖环。"""
    step_ids = {s["id"] for s in steps if s.get("id")}
    adj = {sid: [] for sid in step_ids}
    indeg = {sid: 0 for sid in step_ids}
    for s in steps:
        sid = s.get("id")
        if sid not in step_ids:
            continue
        for d in s.get("depends_on", []):
            if d in step_ids:
                adj[d].append(sid)
                indeg[sid] += 1
    q = deque([sid for sid in step_ids if indeg[sid] == 0])
    visited = 0
    while q:
        cur = q.popleft()
        visited += 1
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    if visited != len(step_ids):
        errors.append("steps.json: 依赖图存在环（编排性错误——耦合边界未拆开）")


def check_mind_coverage(steps, minds, errors):
    """minds.apply_to 引用的步骤必须存在；双向一致性由调用方做。"""
    step_ids = {s["id"] for s in steps if s.get("id")}
    for m in minds:
        mid = m.get("id", "?")
        for ref in m.get("apply_to", []):
            if ref not in step_ids:
                errors.append(f"minds.json: mind {mid} 的 apply_to 引用不存在的步骤: {ref}")


def check_mind_backrefs(steps, minds, errors):
    """steps.mind_ref 与 minds.apply_to 双向一致性（若 apply_to 非空）。"""
    apply_map = {}
    for m in minds:
        mid = m.get("id")
        for ref in m.get("apply_to", []):
            apply_map.setdefault(ref, set()).add(mid)
    for s in steps:
        sid = s.get("id")
        mref = s.get("mind_ref")
        if mref and sid in apply_map and mref not in apply_map[sid]:
            errors.append(
                f"steps.json: 步骤 {sid} 的 mind_ref={mref} 与 minds.apply_to 不一致 "
                f"({sid} 被指派给 {sorted(apply_map[sid])})"
            )


def check_mind_enforce(task_dir, minds, errors):
    """mind.enforce.check 的 source 必须存在（机械门禁的前提条件）。

    enforce.check 只在 type=evidence_in_source 时校验：field 非空、
    source 文件存在。缺失 = 门禁无法执行 = 编排错误。
    """
    for m in minds:
        mid = m.get("id", "?")
        enforce = m.get("enforce") or {}
        check = enforce.get("check") or {}
        if not check:
            continue
        if check.get("type") != "evidence_in_source":
            errors.append(f"minds.json: mind {mid} 的 enforce.check.type 仅支持 evidence_in_source（当前 {check.get('type')}）")
            continue
        if not check.get("field"):
            errors.append(f"minds.json: mind {mid} 的 enforce.check 缺少 field")
        src = check.get("source")
        if not src:
            errors.append(f"minds.json: mind {mid} 的 enforce.check 缺少 source")
        elif not os.path.exists(os.path.join(task_dir, src)):
            errors.append(f"minds.json: mind {mid} 的 enforce.check.source 不存在: {src}")


def check_capability_slots(task_dir, data, errors):
    """插槽引用的能力必须存在于 capabilities.json（若存在该文件）。

    不强制 capabilities.json 存在（旧任务没有能力扫描也可通过）；但一旦存在，
    插槽引用就是硬约束：required_skills/required_mcp/extra_skills/extra_mcp
    必须命中文档中的 skills/mcp_servers。
    """
    cap_path = os.path.join(task_dir, "artifacts", "capabilities.json")
    if not os.path.exists(cap_path):
        return
    try:
        with open(cap_path, "r", encoding="utf-8-sig") as f:
            caps = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        errors.append(f"capabilities.json 读取失败: {e}")
        return
    known_skills = set(caps.get("skills") or [])
    known_mcp = set(caps.get("mcp_servers") or [])

    slots = []
    for op in data.get("op-table.json", {}).get("operations", []):
        opid = op.get("id", "?")
        for s in op.get("required_skills") or []:
            slots.append(("op-table.json", f"op {opid} required_skills", s, known_skills))
        for s in op.get("required_mcp") or []:
            slots.append(("op-table.json", f"op {opid} required_mcp", s, known_mcp))
    for st in data.get("steps.json", {}).get("steps", []):
        sid = st.get("id", "?")
        for s in st.get("extra_skills") or []:
            slots.append(("steps.json", f"step {sid} extra_skills", s, known_skills))
        for s in st.get("extra_mcp") or []:
            slots.append(("steps.json", f"step {sid} extra_mcp", s, known_mcp))

    for fname, where, cap, known in slots:
        if cap not in known:
            errors.append(
                f"{fname}: {where} 引用能力 '{cap}' 不在 capabilities.json "
                f"(skills={sorted(known_skills) or '空'}, mcp_servers={sorted(known_mcp) or '空'})"
            )


def main():
    if len(sys.argv) < 2:
        print("用法: python validate.py <task_dir>")
        sys.exit(2)
    task_dir = sys.argv[1]
    errors = []
    data = {}

    for name in REQUIRED_FILES:
        path = os.path.join(task_dir, name)
        if not os.path.exists(path):
            errors.append(f"缺少文件: {name}")
            continue
        try:
            data[name] = load_json(path)
        except json.JSONDecodeError as e:
            errors.append(f"{name}: JSON 解析失败: {e}")
        except OSError as e:
            errors.append(f"{name}: 读取失败: {e}")

    if "op-table.json" in data:
        for op in data["op-table.json"].get("operations", []):
            opid = op.get("id", "?")
            for slot in ("required_skills", "required_mcp"):
                v = op.get(slot)
                if v is not None and (not isinstance(v, list) or not all(isinstance(x, str) and x for x in v)):
                    errors.append(f"op-table.json: 操作 {opid} 的 {slot} 必须是非空字符串数组（或缺失）")

    if "steps.json" in data:
        steps = data["steps.json"].get("steps", [])
        if not steps:
            errors.append("steps.json: steps 为空（编排必须产出至少一个步骤）")
        else:
            op_ids = {op["id"] for op in data.get("op-table.json", {}).get("operations", [])}
            mind_ids = {m["id"] for m in data.get("minds.json", {}).get("minds", [])}
            check_steps(steps, op_ids, mind_ids, errors)
            check_acyclic(steps, errors)
            if "minds.json" in data and data["minds.json"].get("minds"):
                check_mind_backrefs(steps, data["minds.json"]["minds"], errors)
    if "minds.json" in data:
        minds = data["minds.json"].get("minds", [])
        if "steps.json" in data:
            check_mind_coverage(data["steps.json"].get("steps", []), minds, errors)
        check_mind_enforce(task_dir, minds, errors)

    check_capability_slots(task_dir, data, errors)

    if errors:
        print("校验失败:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        n_steps = len(data["steps.json"]["steps"])
        n_ops = len(data["op-table.json"]["operations"])
        n_minds = len(data["minds.json"]["minds"])
        print(f"校验通过 ✓  steps={n_steps}  ops={n_ops}  minds={n_minds}")
        sys.exit(0)


if __name__ == "__main__":
    # Windows 中文环境默认 GBK 编码，print 非 ASCII（✓/✗）会崩；强制 UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
