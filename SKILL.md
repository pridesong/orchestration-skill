---
name: orchestration
description: 长任务编排引擎。接收任务→模块装配(steps.json 装配表 + minds.json)→两层审计→机械化执行。触发词：长任务、编排、拆解任务、多步骤执行、任务流水线、编排引擎。
---

# 编排引擎 — 协议

本文件是**协议**，只给 LLM 读。人类阅读见 `Description.md`。协议字段即约束，不得当作散文模板自由发挥。

## 协议（JSON Schema 形态）

```json
{
  "fill": ["data.task", "data.constraints", "data.deliverable"],
  "rules": [
    "Stage 0 初始化：在用户项目文件夹建任务目录 <project>/<task_id>/{artifacts,feedback,draft}（不得在 skill 安装目录下创建）；运行 scripts/discover.py <task_dir> --runtime-skills <本会话可见skill> --runtime-mcp <本机MCP server> 产出 artifacts/capabilities.json（本机能力清单，插槽引用的唯一依据）",
    "Stage A 编排（设计收敛，草稿态）：把 data 填入 templates/orchestrator.t3.json 的 data 槽（含 modules_ref/capabilities 引用），整个模板作为 task 字符串派给编排者 subagent（唯一派发方式，禁止散文包装）；编排者按 mind-orchestrator 思维产出装配表草稿（steps.json fields + minds.json）写入 draft/；草稿不进状态机，只做设计收敛",
    "Stage B 审计编排（同上下文多轮循环）：① scripts/validate.py draft/ 机械校验（字段命名/模块引用/routing 合法性/依赖无环），失败 → send_message 编排者（延续同一会话）按错误修改草稿 → 再校验，循环直到通过；② 派独立审计 subagent（templates/audit.t3.json，mind-orchestration-audit 思维）读 draft/ 产出意见（artifacts/audit_<route>.json），verdict=revise → 意见送回编排者修改 → 再审；多脑子纠错：编排者自审不充分，审计者每次独立上下文",
    "Stage C 物化（进入执行态）：设计收敛后，主 agent 机械复制 draft/ 到任务根（steps.json/minds.json 定稿），建 artifacts/；此后装配表是定稿，改动走 Stage 3 重新收敛",
    "Stage 2 机械化执行：scripts/executor.py ready <task_dir> 列可执行字段（前置门禁）；每字段派发必须用 executor.py t3 <task_dir> <field> 生成 T3 六件套（协议由模块 + mind 推导），派发 prompt 只能是 T3FILE:v1 零引导语模板（见 schema.dispatch_prompt 的 pattern，禁止任何散文前缀/后缀）；subagent 执行后 executor.py check <field> 验证推进/路由（后置门禁）",
    "Stage 3 动态审计：同一字段 3 次同类失败自动 needs_reorchestration，判执行性错误（重试）vs 编排性错误（回 Stage A 重新收敛）",
    "Stage 4 收尾：scripts/compare.py 全量验证 + 装配表归档 templates/ 或 examples/",
    "模块装配：module 决定 produce（generate/discriminate）、mind 参数集、output_schema、默认 forbidden；能用模块库就不自造协议；判别式字段必须有 routing（判断值→目标字段/stop）",
    "mind 限制：编排者用 mind-orchestrator（对抗 C05 早期锚定/C03 路径锁定/C02 执行启动缺失），编排审计用 mind-orchestration-audit（对抗 C05 确认偏误/M07 谄媚/C06 阈值失敏）——mind 指令随 T3 rules 注入，散文不产生约束力，指令即契约"
  ],
  "schema": {
    "data": {
      "type": "object",
      "properties": {
        "task": { "type": "string", "description": "意图浓缩后的任务目标" },
        "constraints": { "type": "array", "items": { "type": "string" }, "description": "用户意图中的隐式约束" },
        "deliverable": { "type": "string", "description": "最终交付物定义" },
        "template_ref": { "type": "string", "description": "可选：复用的装配表骨架路径（steps.json + minds.json 示例）" },
        "intel_ref": { "type": "string", "description": "可选：情报产物路径" }
      },
      "required": ["task", "deliverable"],
      "additionalProperties": false
    },
    "dispatch_prompt": {
      "type": "string",
      "pattern": "^T3FILE:v1 读取 <task_dir>/dispatch/<field>\\.t3\\.json 并按内容执行。产出写入 <task_dir> 下的 write 相对路径。$",
      "description": "派发给执行 subagent 的 prompt 唯一合法形态（零引导语）。pattern 锁定：不得有任何散文前缀/后缀/解释/补充——多一个词即不合格。task_dir/field 替换为实际值，其余逐字匹配。",
      "examples": [
        "T3FILE:v1 读取 <project>/<task_id>/dispatch/generate_01.t3.json 并按内容执行。产出写入 <project>/<task_id> 下的 write 相对路径。"
      ]
    },
    "dispatch_t3": {
      "type": "object",
      "description": "executor.py t3 生成的步骤派发协议（fill/rules/schema/data/write/forbidden），主 agent 不手工构造",
      "required": ["fill", "rules", "schema", "data", "write", "forbidden"],
      "additionalProperties": false,
      "properties": {
        "fill": { "type": "array", "items": { "type": "string" } },
        "rules": { "type": "array", "items": { "type": "string" } },
        "schema": { "type": "object" },
        "data": { "type": "object" },
        "write": { "type": "string" },
        "forbidden": { "type": "array", "items": { "type": "string" } }
      }
    }
  },
  "data": {
    "task": "<用户任务（意图浓缩后）>",
    "constraints": ["<隐式约束>"],
    "deliverable": "<交付物>",
    "template_ref": "<可选>",
    "intel_ref": "<可选>"
  },
  "write": "<project>/<task_id>/（任务目录在用户项目文件夹下，不在 skill 安装目录。draft/ 草稿态 → 物化后：steps.json/minds.json 定稿 + artifacts/ + dispatch/*.t3.json + feedback/）",
  "forbidden": [
    "主 agent 不得自行设计字段序列——编排是编排者 subagent 按 orchestrator.t3.json 的职责",
    "主 agent 不得用散文给执行 subagent 派发指令——派发 prompt 必须逐字匹配 schema.dispatch_prompt 的 pattern（T3FILE:v1 零引导语），禁止任何前缀/后缀/解释/补充",
    "不得在 skill 安装目录下创建任务目录——任务目录必须建在用户项目文件夹（<project>/<task_id>/）",
    "不得跳过 scripts/validate.py 机械校验（草稿态与定稿态都要验）",
    "不得跳过独立审计（多路 subagent，多脑子纠错）",
    "产物必须物化到任务目录，不留对话上下文",
    "主 agent 不得中途改变已定稿装配表——需改动回 Stage A 重新收敛",
    "不得把 draft/ 当执行态——草稿只用于设计收敛，物化（复制到任务根）后才进入状态机",
    "不得把本 skill 当散文模板阅读后自由发挥——协议字段即约束"
  ]
}
```

## 机械命令清单（唯一允许的操作）

```
python scripts/discover.py   <task_dir> [--runtime-skills <a,b>] [--runtime-mcp <obsidian,...>]  # 本机能力扫描 → artifacts/capabilities.json
python scripts/executor.py materialize <task_dir>      # 设计收敛 → 执行态：复制 draft/ 到任务根（物化）
python scripts/executor.py ready   <task_dir> [--state '<json>']  # 列可执行字段（前置门禁；--state 传外部计数）
python scripts/executor.py t3      <task_dir> <field>  # 生成字段 T3 六件套（派发唯一依据，协议由模块+mind推导）
python scripts/executor.py check   <task_dir> <field>  # 后置门禁：验证产物并推进/路由（判别式路由生效）
python scripts/executor.py retry   <task_dir> <field>  # failed → pending（重试）
python scripts/executor.py reset   <task_dir> <field>  # needs_reorchestration → pending
python scripts/executor.py status  <task_dir>          # 状态机全景
python scripts/validate.py         <task_dir>          # 装配表机械校验（草稿态与定稿态都可用）
python scripts/compare.py          <task_dir>          # 收尾全量验证
```

`<task_dir>` = `<project>/<task_id>`（用户项目文件夹下的任务子目录）。

## 装配产物

| 文件 | 约束 schema | 产出者 |
|------|-------------|--------|
| steps.json | `schemas/steps.schema.json` | 编排者（draft/ → 物化定稿） |
| minds.json | `schemas/minds.schema.json` | 编排者（draft/ → 物化定稿） |
| op-table.json | `schemas/op-table.schema.json` | materialize 从声明展开 |
| state.csv | — | executor 追加（每步一行，只填当步字段，无继承） |
| modules.json | `schemas/modules.schema.json` | 内置 `modules/`，任务级可扩展 |
