#!/usr/bin/env python3
"""
validate.py — 装配表机械校验（第一层审计的硬门禁）

检查项：
  1. steps.json / modules.json / minds.json 存在且为合法 JSON
  2. 字段命名合规（generate_N / discriminate_N_xxx）
  3. 模块引用存在（装配表 → modules 库）
  4. 判别式字段必须有 routing 且 routing 目标存在/stop
  5. inputs 连线引用的前序字段存在
  6. 依赖图无环（Kahn 拓扑排序）
  7. minds.apply_to 引用存在 + 双向一致
  8. 能力插槽真实性（capabilities.json 若存在）
  9. mind.enforce.check 的 source 存在

用法: python validate.py <task_dir>
退出码: 0=通过, 1=不通过, 2=用法错误
"""
import json
import os
import re
import sys
from collections import deque

GEN_FIELD = re.compile(r"^generate_(\d+)$")
DIS_FIELD = re.compile(r"^discriminate_(\d+)_([a-z][a-z0-9_]*)$")
MODULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modules")

REQUIRED_FILES = ["steps.json", "minds.json"]


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def check_field_names(fields, errors):
    for f in fields:
        fid = f.get("field", "")
        if not GEN_FIELD.match(fid) and not DIS_FIELD.match(fid):
            errors.append(f"steps.json: 字段名 '{fid}' 不合规（须 generate_N 或 discriminate_N_xxx）")
        if "module" not in f:
            errors.append(f"steps.json: 字段 {fid} 缺少 module")


def check_field_refs(fields, module_ids, errors):
    """模块引用存在 + inputs 引用存在 + 判别式 routing 合法。"""
    field_ids = {f.get("field") for f in fields if f.get("field")}
    seen = set()
    for f in fields:
        fid = f.get("field", "?")
        if fid in seen:
            errors.append(f"steps.json: 重复字段: {fid}")
        seen.add(fid)

        mod = f.get("module")
        if mod and mod not in module_ids:
            errors.append(f"steps.json: 字段 {fid} 引用不存在的模块: {mod}")

        # inputs 连线引用的前序字段
        for v in (f.get("inputs") or {}).values():
            if isinstance(v, str) and (GEN_FIELD.match(v) or DIS_FIELD.match(v)):
                if v not in field_ids:
                    errors.append(f"steps.json: 字段 {fid} 的 inputs 引用不存在的字段: {v}")

        # 判别式必须有 routing 且目标合法
        if DIS_FIELD.match(fid):
            routing = f.get("routing")
            if routing is None:
                errors.append(f"steps.json: 判别字段 {fid} 缺少 routing（须定义判断值→目标映射）")
            else:
                for val, target in routing.items():
                    if target != "stop" and target not in field_ids:
                        errors.append(f"steps.json: 字段 {fid} 的 routing[{val}] 目标不存在: {target}")


def check_acyclic(fields, errors):
    """Kahn 拓扑排序检测依赖环（inputs 连线 + 判别路由目标）。"""
    field_ids = {f["field"] for f in fields if f.get("field")}
    adj = {fid: set() for fid in field_ids}
    indeg = {fid: 0 for fid in field_ids}
    for f in fields:
        fid = f.get("field")
        if fid not in field_ids:
            continue
        for v in (f.get("inputs") or {}).values():
            if isinstance(v, str) and v in field_ids and v != fid:
                if fid not in adj[v]:
                    adj[v].add(fid)
                    indeg[fid] += 1
        for v in (f.get("routing") or {}).values():
            if v != "stop" and v in field_ids and v != fid:
                if fid not in adj[v]:
                    adj[v].add(fid)
                    indeg[fid] += 1
    q = deque([fid for fid in field_ids if indeg[fid] == 0])
    visited = 0
    while q:
        cur = q.popleft()
        visited += 1
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    if visited != len(field_ids):
        errors.append("steps.json: 依赖图存在环（inputs 连线或路由形成回路）")


def check_minds(fields, task_dir, errors):
    """minds.json：apply_to 引用存在；enforce.check.source 存在。"""
    minds_path = os.path.join(task_dir, "minds.json")
    if not os.path.exists(minds_path):
        return
    data = load_json(minds_path)
    minds = data.get("minds", [])
    mind_ids = {m.get("id") for m in minds}
    field_ids = {f.get("field") for f in fields}

    for m in minds:
        mid = m.get("id", "?")
        for ref in m.get("apply_to", []):
            if ref not in field_ids:
                errors.append(f"minds.json: mind {mid} 的 apply_to 引用不存在的字段: {ref}")
        enforce = m.get("enforce") or {}
        check = enforce.get("check") or {}
        if check:
            if check.get("type") != "evidence_in_source":
                errors.append(f"minds.json: mind {mid} 的 enforce.check.type 仅支持 evidence_in_source")
            if not check.get("field"):
                errors.append(f"minds.json: mind {mid} 的 enforce.check 缺少 field")
            src = check.get("source")
            if not src:
                errors.append(f"minds.json: mind {mid} 的 enforce.check 缺少 source")
            elif not os.path.exists(os.path.join(task_dir, src)):
                errors.append(f"minds.json: mind {mid} 的 enforce.check.source 不存在: {src}")

    # 装配表引用的 mind 必须存在
    for f in fields:
        mref = f.get("mind_ref")
        if mref and mref not in mind_ids:
            errors.append(f"steps.json: 字段 {f.get('field')} 引用不存在的 mind: {mref}")


def check_capability_slots(task_dir, fields, errors):
    """插槽引用的能力必须存在于 capabilities.json（若存在）。"""
    cap_path = os.path.join(task_dir, "artifacts", "capabilities.json")
    if not os.path.exists(cap_path):
        return
    caps = load_json(cap_path)
    known_skills = set(caps.get("skills") or [])
    known_mcp = set(caps.get("mcp_servers") or [])

    modules = load_modules(task_dir)
    for f in fields:
        fid = f.get("field", "?")
        mod = modules.get(f.get("module") or {})
        for s in (mod or {}).get("skills") or []:
            if s not in known_skills:
                errors.append(f"steps.json: 字段 {fid} 模块 {f.get('module')} 的 skill '{s}' 不在 capabilities.json")
        for m in (mod or {}).get("mcp") or []:
            if m not in known_mcp:
                errors.append(f"steps.json: 字段 {fid} 模块 {f.get('module')} 的 MCP '{m}' 不在 capabilities.json")


def load_modules(task_dir):
    local = os.path.join(task_dir, "modules.json")
    path = local if os.path.exists(local) else os.path.join(MODULES_DIR, "modules.json")
    data = load_json(path)
    return {m["id"]: m for m in data.get("modules", [])}


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

    if "steps.json" in data:
        fields = data["steps.json"].get("fields", [])
        if not fields:
            errors.append("steps.json: fields 为空（编排必须产出至少一个字段）")
        else:
            modules = load_modules(task_dir)
            check_field_names(fields, errors)
            check_field_refs(fields, set(modules.keys()), errors)
            check_acyclic(fields, errors)
            check_minds(fields, task_dir, errors)
            check_capability_slots(task_dir, fields, errors)

    if errors:
        print("校验失败:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        n = len(data["steps.json"]["fields"])
        print(f"校验通过 ✓  fields={n}")
        sys.exit(0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
