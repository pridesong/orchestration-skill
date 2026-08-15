#!/usr/bin/env python3
"""
discover.py — 本机能力扫描（编排前的情报步骤）

在调用编排引擎时，主 agent 先运行本脚本，把本机真实可装配的能力物化为
artifacts/capabilities.json。编排者 subagent 的 T3 派发会引用该文件，
required_skills / required_mcp 插槽只能从其中选择——杜绝编排者发明不存在的
skill / MCP。

能力来源（三路合并，去重）：
  1. MCP server：扫描 DSH 用户 patch 层（$DSH_HOME/cordis.patch.yml 与
     $DSH_HOME/profiles/*/cordis.patch.yml）中 @deepseek-ai/dsh-mcp-client
     的 insert 行，提取 serverName（机器生成的 YAML，行级解析足够）。
  2. Skill 目录：--skill-dirs 显式给出的目录（逗号分隔）。每个子目录若含
     SKILL.md，取其 frontmatter 的 name；否则用目录名。
  3. 运行时补充：--runtime-skills / --runtime-mcp 是主 agent 当前会话实际
     可见的能力（最可靠来源），原样并入。

用法:
  python scripts/discover.py <task_dir> [--skill-dirs dir1,dir2]
      [--runtime-skills a,b,c] [--runtime-mcp obsidian,github]

输出: <task_dir>/artifacts/capabilities.json
退出码: 0=成功, 2=用法错误
"""
import json
import os
import re
import sys

DSH_HOME = os.environ.get("DSH_HOME", os.path.join(os.path.expanduser("~"), ".dsh"))
MCP_PLUGIN_NAME = "@deepseek-ai/dsh-mcp-client"


def find_patch_files():
    """DSH 用户 patch 层：home 级 + profiles 级。"""
    candidates = [os.path.join(DSH_HOME, "cordis.patch.yml")]
    profiles_dir = os.path.join(DSH_HOME, "profiles")
    if os.path.isdir(profiles_dir):
        for entry in sorted(os.listdir(profiles_dir)):
            p = os.path.join(profiles_dir, entry, "cordis.patch.yml")
            if os.path.isfile(p):
                candidates.append(p)
    return [c for c in candidates if os.path.isfile(c)]


def scan_mcp_servers():
    """从 patch 文件提取 mcp-client insert 行的 serverName。"""
    servers = []
    for fpath in find_patch_files():
        try:
            with open(fpath, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except OSError:
            continue
        # 定位 mcp-client 插件行，取其 config 下的 serverName（下一个顶层 - 之前）
        for m in re.finditer(
            r"name:\s*['\"]?" + re.escape(MCP_PLUGIN_NAME) + r"['\"]?",
            text,
        ):
            rest = text[m.end():]
            # 取到下一个顶层列表项（行首 - ）为止
            block = re.split(r"\n\s*-\s", rest, maxsplit=1)[0]
            sm = re.search(r"serverName:\s*['\"]?([A-Za-z0-9_-]+)['\"]?", block)
            if sm and sm.group(1) not in servers:
                servers.append(sm.group(1))
    return servers


def read_frontmatter_name(skill_dir):
    """SKILL.md frontmatter 的 name 字段；无则返回 None。"""
    path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            head = f.read(2000)
    except OSError:
        return None
    m = re.search(r"^name:\s*(.+)$", head, re.MULTILINE)
    return m.group(1).strip().strip("'\"") if m else None


def scan_skills(skill_dirs):
    """扫描 skill 目录：子目录名 + SKILL.md frontmatter name。"""
    skills = []
    for root in skill_dirs:
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            full = os.path.join(root, entry)
            if not os.path.isdir(full):
                continue
            name = read_frontmatter_name(full) or entry
            if name and name not in skills:
                skills.append(name)
    return skills


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    task_dir = sys.argv[1]
    skill_dirs = []
    runtime_skills = []
    runtime_mcp = []

    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--skill-dirs" and i + 1 < len(sys.argv):
            skill_dirs = [d for d in sys.argv[i + 1].split(",") if d]
            i += 2
        elif arg == "--runtime-skills" and i + 1 < len(sys.argv):
            runtime_skills = [s for s in sys.argv[i + 1].split(",") if s]
            i += 2
        elif arg == "--runtime-mcp" and i + 1 < len(sys.argv):
            runtime_mcp = [s for s in sys.argv[i + 1].split(",") if s]
            i += 2
        else:
            print(f"未知参数: {arg}")
            sys.exit(2)

    # 三路合并，保持顺序去重
    mcp = []
    for s in scan_mcp_servers() + runtime_mcp:
        if s not in mcp:
            mcp.append(s)
    skills = []
    for s in scan_skills(skill_dirs) + runtime_skills:
        if s not in skills:
            skills.append(s)

    capabilities = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "dsh_home": DSH_HOME,
            "patch_files": find_patch_files(),
            "skill_dirs": skill_dirs,
            "runtime": bool(runtime_skills or runtime_mcp),
        },
        "skills": skills,
        "mcp_servers": mcp,
    }

    artifacts_dir = os.path.join(task_dir, "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    out = os.path.join(artifacts_dir, "capabilities.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(capabilities, f, ensure_ascii=False, indent=2)

    print(f"能力扫描完成 → {out}")
    print(f"  skills ({len(skills)}): {', '.join(skills) or '(空)'}")
    print(f"  mcp_servers ({len(mcp)}): {', '.join(mcp) or '(空)'}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
