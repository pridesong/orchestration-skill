#!/usr/bin/env python3
"""
compare.py — 产物偏离检查（机械化执行的自验辅助）

对每个字段检查：
  1. 期望产物文件是否存在（artifacts/<field>.json）
  2. 产物为 JSON 且模块 output_schema 定义了 required 时，检查字段完整性
  3. 判别式字段：判断项值 ∈ routing 合法域

用法: python compare.py <task_dir>
退出码: 0=全部满足, 1=存在缺失, 2=用法错误
"""
import json
import os
import re
import sys

GEN_FIELD = re.compile(r"^generate_(\d+)$")
DIS_FIELD = re.compile(r"^discriminate_(\d+)_([a-z][a-z0-9_]*)$")
MODULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modules")


def load_modules(task_dir):
    local = os.path.join(task_dir, "modules.json")
    path = local if os.path.exists(local) else os.path.join(MODULES_DIR, "modules.json")
    with open(path, "r", encoding="utf-8-sig") as f:
        return {m["id"]: m for m in json.load(f).get("modules", [])}


def main():
    if len(sys.argv) < 2:
        print("用法: python compare.py <task_dir>")
        sys.exit(2)
    task_dir = sys.argv[1]
    steps_path = os.path.join(task_dir, "steps.json")
    if not os.path.exists(steps_path):
        print("缺少 steps.json（先运行编排生成装配表）")
        sys.exit(1)

    with open(steps_path, "r", encoding="utf-8-sig") as f:
        steps_data = json.load(f)
    modules = load_modules(task_dir)

    issues = []
    checked = 0
    for f in steps_data.get("fields", []):
        fid = f.get("field", "?")
        fname = f"artifacts/{fid}.json"
        fpath = os.path.join(task_dir, fname)
        checked += 1
        if not os.path.exists(fpath):
            issues.append(f"字段 {fid}: 期望产物缺失 {fname}")
            continue
        module = modules.get(f.get("module") or {}) or {}
        required = (module.get("output_schema") or {}).get("required", [])
        try:
            with open(fpath, "r", encoding="utf-8-sig") as fh:
                content = json.load(fh)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            issues.append(f"字段 {fid}: 产物 {fname} 不是合法 JSON: {e}")
            continue
        for field_name in required:
            if field_name not in content:
                issues.append(f"字段 {fid}: 产物 {fname} 缺少字段 {field_name}")
        if DIS_FIELD.match(fid):
            routing = f.get("routing") or module.get("routing") or {}
            for item in required:
                if item in content and isinstance(content[item], str) and routing:
                    if content[item] not in routing:
                        issues.append(
                            f"字段 {fid}: 判断项 {item}={content[item]} 不在路由合法域 {sorted(routing.keys())}"
                        )

    if issues:
        print("偏离检查: 发现问题")
        for i in issues:
            print(f"  ✗ {i}")
        sys.exit(1)
    else:
        print(f"偏离检查: 通过 ✓（检查 {checked} 个产物）")
        sys.exit(0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
