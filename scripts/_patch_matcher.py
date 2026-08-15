#!/usr/bin/env python3
"""替换 condition_matches / next_field_by_op_table：支持外部计数状态（主 agent 提供轮次/次数）。"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
path = r"D:\MyProject\orchestration-skill\scripts\executor.py"
src = open(path, encoding="utf-8").read()

start = src.index("def condition_matches(condition, last_state):")
end = src.index("def cmd_materialize(task_dir):")

new_body = '''def condition_matches(condition, last_state, extra_state=None):
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
        if "=" not in part:
            continue
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


'''

src = src[:start] + new_body + src[end:]
open(path, "w", encoding="utf-8").write(src)
print("condition matcher with extra_state replaced")
