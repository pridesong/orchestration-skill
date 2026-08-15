#!/usr/bin/env python3
"""迁移旧三件套示例到新装配表格式（一次性脚本）。

规则：
  s001..s009 → generate_N（产出类）或 discriminate_N_xxx（判断类，按 op_ref）
  op_ref → module 映射：op-query→mod-query, op-generate→mod-generate, op-build→mod-generate,
    op-test→mod-verify, op-verify→mod-verify, op-audit→mod-audit, op-materialize→mod-generate,
    op-research→mod-reason, op-transform→mod-transform, op-classify→mod-classify
  depends_on s00X → inputs 连线（{source: generate_0X} 或判别目标）
  s007（条件执行）→ discriminate_01_live：reachable→真实冒烟 / false→降级
  产物重命名：artifacts/s00X_*.json → artifacts/<field>.json
"""
import json
import os
import re
import sys
import shutil

sys.stdout.reconfigure(encoding="utf-8")

OP_TO_MODULE = {
    "op-query": "mod-query",
    "op-generate": "mod-generate",
    "op-build": "mod-generate",
    "op-test": "mod-verify",
    "op-verify": "mod-verify",
    "op-audit": "mod-audit",
    "op-materialize": "mod-generate",
    "op-research": "mod-reason",
    "op-transform": "mod-transform",
    "op-classify": "mod-classify",
}

# 判别式步骤（旧 op-ref → 判断字段语义）
DISCRIMINATORS = {
    "op-verify": "verdict",
    "op-audit": "verdict",
    "op-test": "verdict",
}


def migrate(example_dir):
    steps_path = os.path.join(example_dir, "steps.json")
    with open(steps_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    old_steps = data.get("steps")
    if old_steps is None:
        print(f"{example_dir}: 已是新格式，跳过")
        return

    # 旧 id → 新字段映射（保持顺序，判断类用 discriminate）
    id_to_field = {}
    gen_counter = 0
    dis_counter = 0
    for s in old_steps:
        op = s.get("op_ref", "")
        if op in DISCRIMINATORS and op != "op-query":
            dis_counter += 1
            suffix = DISCRIMINATORS[op]
            fid = f"discriminate_{dis_counter:02d}_{suffix}"
        else:
            gen_counter += 1
            fid = f"generate_{gen_counter:02d}"
        id_to_field[s["id"]] = fid

    new_fields = []
    for s in old_steps:
        fid = id_to_field[s["id"]]
        op = s.get("op_ref", "")
        module = OP_TO_MODULE.get(op, "mod-generate")
        # inputs 连线：旧 input.from / input.from[] → 新 inputs {source: 字段}
        inputs = {}
        if isinstance(s.get("input"), dict):
            frm = s["input"].get("from")
            if isinstance(frm, str):
                inputs["source"] = id_to_field.get(frm, frm)
            elif isinstance(frm, list):
                srcs = [id_to_field.get(x, x) for x in frm]
                inputs["source"] = srcs[0] if len(srcs) == 1 else srcs
            else:
                for k, v in s["input"].items():
                    if k != "from":
                        inputs[k] = v
        field = {
            "field": fid,
            "name": s.get("name", ""),
            "module": module,
            "inputs": inputs,
            "acceptance_criteria": s.get("acceptance_criteria", []),
            "status": "pending",
        }
        if fid.startswith("discriminate"):
            # 判别式默认路由：pass→下一个 generate，revise→前一个 generate
            gen_fields = [f["field"] for f in new_fields if f["field"].startswith("generate")]
            routing = {"pass": "", "revise": ""}
            if gen_fields:
                routing["revise"] = gen_fields[-1]
            field["routing"] = routing
        new_fields.append(field)

    # 补 discriminate 的 pass 路由：指向下一个未定义 generate（用占位，validate 只查目标存在）
    # 简化：pass→stop（示例仅展示结构），或指向最后字段
    gen_all = [id_to_field[s["id"]] for s in old_steps if s["op_ref"] not in DISCRIMINATORS]
    for f in new_fields:
        if f["field"].startswith("discriminate") and f.get("routing"):
            f["routing"]["pass"] = gen_all[-1] if gen_all else "stop"

    new_data = {
        "task_id": data.get("task_id", ""),
        "version": "0.2.0",
        "created_at": data.get("created_at", ""),
        "fields": new_fields,
    }
    with open(steps_path, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
    print(f"{example_dir}: 迁移完成，字段 = {[f['field'] for f in new_fields]}")

    # 产物重命名：artifacts/s00X_*.json → artifacts/<field>.json
    artifacts_dir = os.path.join(example_dir, "artifacts")
    if os.path.isdir(artifacts_dir):
        for old_id, fid in id_to_field.items():
            for name in os.listdir(artifacts_dir):
                if name.startswith(f"{old_id}_") or name.startswith(f"{old_id}."):
                    src = os.path.join(artifacts_dir, name)
                    dst = os.path.join(artifacts_dir, f"{fid}.json")
                    if os.path.isfile(src) and src != dst:
                        shutil.move(src, dst)
                        print(f"  {name} → {fid}.json")

    # minds.json：apply_to 的 s00X → 新字段名
    minds_path = os.path.join(example_dir, "minds.json")
    if os.path.exists(minds_path):
        with open(minds_path, "r", encoding="utf-8") as f:
            minds = json.load(f)
        changed = False
        for m in minds.get("minds", []):
            new_apply = []
            for ref in m.get("apply_to", []):
                new_apply.append(id_to_field.get(ref, ref))
            if new_apply != m.get("apply_to"):
                m["apply_to"] = new_apply
                changed = True
        if changed:
            with open(minds_path, "w", encoding="utf-8") as f:
                json.dump(minds, f, ensure_ascii=False, indent=2)
            print(f"  minds.json apply_to 已迁移")

    # 删除 op-table.json（新架构由模块库提供原语）
    op_table = os.path.join(example_dir, "op-table.json")
    if os.path.exists(op_table):
        os.remove(op_table)
        print(f"  已删除 op-table.json")


def main():
    for d in sys.argv[1:]:
        migrate(d)


if __name__ == "__main__":
    main()
