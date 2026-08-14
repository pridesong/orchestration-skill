#!/usr/bin/env python3
"""
compare.py — 产物偏离检查（机械化执行的自验辅助）

对每步检查：
  1. 期望产物文件是否存在（output.file 相对任务文件夹）
  2. 产物为 JSON 且定义了 required 字段时，检查字段完整性

偏离对抗原则：产物物化让偏离在交接处暴露。本脚本把"偏离检测"机械化——
不依赖 agent 自觉（自检也是 agent 做的，也会偏离，所以用脚本）。

用法: python compare.py <task_dir>
退出码: 0=全部满足, 1=存在缺失, 2=用法错误
"""
import json
import os
import sys


def main():
    if len(sys.argv) < 2:
        print("用法: python compare.py <task_dir>")
        sys.exit(2)
    task_dir = sys.argv[1]
    steps_path = os.path.join(task_dir, "steps.json")
    if not os.path.exists(steps_path):
        print("缺少 steps.json（先运行编排生成三件套）")
        sys.exit(1)

    with open(steps_path, "r", encoding="utf-8-sig") as f:  # utf-8-sig 容忍 BOM
        steps_data = json.load(f)

    issues = []
    checked = 0
    for s in steps_data.get("steps", []):
        sid = s.get("id", "?")
        out = s.get("output") or {}
        fname = out.get("file")
        if not fname:
            continue
        fpath = os.path.join(task_dir, fname)
        checked += 1
        if not os.path.exists(fpath):
            issues.append(f"步骤 {sid}: 期望产物缺失 {fname}")
            continue
        # JSON 产物字段检查：required 非空 = 期望 JSON，解析失败 = 不通过
        required = (out.get("schema") or {}).get("required", [])
        if required:
            try:
                # utf-8-sig 容忍 BOM
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    content = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                issues.append(f"步骤 {sid}: 产物 {fname} 不是合法 JSON（期望字段 {required}）: {e}")
                continue
            for field in required:
                if field not in content:
                    issues.append(f"步骤 {sid}: 产物 {fname} 缺少字段 {field}")

    if issues:
        print("偏离检查: 发现问题")
        for i in issues:
            print(f"  ✗ {i}")
        sys.exit(1)
    else:
        print(f"偏离检查: 通过 ✓（检查 {checked} 个产物）")
        sys.exit(0)


if __name__ == "__main__":
    # Windows 中文环境默认 GBK 编码，print 非 ASCII（✓/✗）会崩；强制 UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
