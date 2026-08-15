#!/usr/bin/env python3
"""替换 executor.py：op-table 生成（判别点路由设计展开）+ 多条件匹配器。"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
path = r"D:\MyProject\orchestration-skill\scripts\executor.py"
src = open(path, encoding="utf-8").read()

# 替换 generate_op_table
start = src.index("def generate_op_table(fields, modules):")
end = src.index("def cmd_materialize(task_dir):")

new_op_table = '''def generate_op_table(fields, modules):
    """从编排者设计生成 op-table.json（条件路由表，排它）。

    状态机形态由编排者设计决定：
      generate 字段 → {condition: "<field>=passed", dispatch: "<拓扑序最前的消费者>"}
      discriminate 字段 → 判别点路由设计展开：
        字符串目标 → {condition: "<field>=<verdict>", dispatch: "<目标>"}
        对象机制（审计回退）→ 展开：
          {condition: "<field>=<verdict>", dispatch: "<to>", side_effect: "<cnt>+1", mind: "<mind>"}
          {condition: "<field>=<verdict>,<cnt>>=<limit>", dispatch: "<escalate>"}
    生成器读编排者的判别点设计，机械展开为 op-table；形态随设计变化。
    """
    operations = []
    topo = topological_order(fields)

    for f in fields:
        fid = f["field"]
        produce = field_produce(fid)
        module = modules.get(f["module"], {})
        if produce == "generate":
            consumers = [c for c in topo if c != fid and fid in field_inputs(get_field(fields, c))]
            nxt = consumers[0] if consumers else "stop"
            operations.append({
                "condition": f"{fid}=passed",
                "dispatch": nxt,
                "side_effect": None,
            })
        elif produce == "discriminate":
            routing = f.get("routing") or module.get("routing") or {}
            for verdict, target in routing.items():
                if isinstance(target, str):
                    operations.append({
                        "condition": f"{fid}={verdict}",
                        "dispatch": target,
                        "side_effect": None,
                    })
                elif isinstance(target, dict):
                    # 审计回退机制：目标 + 计数 + 换脑 + mind 覆盖
                    to = target.get("to", "stop")
                    cnt = target.get("counter", f"{fid}_count")
                    limit = target.get("limit")
                    escalate = target.get("escalate")
                    mind = target.get("mind")
                    op = {
                        "condition": f"{fid}={verdict}",
                        "dispatch": to,
                        "side_effect": f"{cnt}+1",
                    }
                    if mind:
                        op["mind"] = mind
                    operations.append(op)
                    if limit is not None and escalate:
                        operations.append({
                            "condition": f"{fid}={verdict},{cnt}>={limit}",
                            "dispatch": escalate,
                            "side_effect": None,
                        })
    return operations


def condition_matches(condition, last_state):
    """条件匹配（排它）：逗号分隔的多条件 AND。

    每项 <field>=<value>：字段存在且值相等。last_state = 最后一行非空字段。
    返回 (matched, matched_field)。matched_field 供日志。
    """
    if not condition or not last_state:
        return False, None
    parts = [p.strip() for p in condition.split(",") if p.strip()]
    matched_field = None
    for part in parts:
        if "=" not in part:
            continue
        c_field, c_val = part.split("=", 1)
        if last_state.get(c_field) == c_val:
            matched_field = c_field
        else:
            return False, None
    return matched_field is not None, matched_field


def next_field_by_op_table(op_table, last_state):
    """op-table 匹配最后一行 → 下一步（排它：条件互斥，顺序第一个命中）。

    last_state = state.csv 最后一行非空字段 {field: value}（一步只填一个字段）。
    返回 {dispatch, mind} 或 None。
    """
    if not last_state:
        return None
    for op in op_table:
        matched, _ = condition_matches(op.get("condition", ""), last_state)
        if matched:
            result = {"dispatch": op.get("dispatch")}
            if op.get("mind"):
                result["mind"] = op["mind"]
            return result
    return None


'''

src = src[:start] + new_op_table + src[end:]

# 替换 cmd_ready 与 cmd_status 中 next_field_by_op_table 的用法（返回值变 dict）
open(path, "w", encoding="utf-8").write(src)
print("op-table generation + matcher replaced")
