---
name: orchestration
description: 长任务编排引擎。接收任务→模块装配(steps.json 装配表 + minds.json)→两层审计→机械化执行。触发词：长任务、编排、拆解任务、多步骤执行、任务流水线、编排引擎。
---

# 编排引擎（Orchestration Engine）— 模块装配 + 字段语义状态机

本 skill 以 JSON Schema / T3 协议表达，**防止主 agent 跑偏**。主 agent 的职责边界由 `forbidden` 锁死：只做意图浓缩（填 `data`）、触发本 skill、执行机械命令（ready/t3/check）、交付确认。其余（编排生成、审计、执行）全部由 subagent 按协议承担。

**核心模型：模块装配（搭积木）**。编排者不是协议设计师，是**装配师**——根据任务确立链路、从模块库挑选模块、连线。状态机由字段名驱动：

- `generate_N`（生成式）：产出 artifacts/generate_N.json，落盘 + schema 验证即推进
- `discriminate_N_xxx`（判别式）：产出判断项，值 ∈ routing keys → 路由到目标字段或 stop（分支点）

## 协议（JSON Schema 形态）

```json
{
  "fill": ["data.task", "data.constraints", "data.deliverable"],
  "rules": [
    "Stage 0 初始化：建任务目录 tasks/<task_id>/{artifacts,feedback,draft}；运行 scripts/discover.py <task_dir> --skill-dirs <skill目录> --runtime-skills <本会话可见skill> --runtime-mcp <本机MCP server> 产出 artifacts/capabilities.json（本机能力清单，插槽引用的唯一依据）",
    "Stage A 编排（设计收敛，草稿态）：把 data 填入 templates/orchestrator.t3.json 的 data 槽（含 modules_ref/capabilities 引用），整个模板作为 task 字符串派给编排者 subagent（唯一派发方式，禁止散文包装）；编排者按 mind-orchestrator 思维产出装配表草稿（steps.json fields + minds.json）写入 draft/；草稿不进状态机，只做设计收敛",
    "Stage B 审计编排（同上下文多轮循环）：① scripts/validate.py draft/ 机械校验（字段命名/模块引用/routing 合法性/依赖无环），失败 → send_message 编排者（延续同一会话）按错误修改草稿 → 再校验，循环直到通过；② 派独立审计 subagent（templates/audit.t3.json，mind-orchestration-audit 思维）读 draft/ 产出意见（artifacts/audit_<route>.json），verdict=revise → 意见送回编排者修改 → 再审；多脑子纠错：编排者自审不充分，审计者每次独立上下文",
    "Stage C 物化（进入执行态）：设计收敛后，主 agent 机械复制 draft/ 到任务根（steps.json/minds.json 定稿），建 artifacts/；此后装配表是定稿，改动走 Stage 3 重新收敛",
    "Stage 2 机械化执行：scripts/executor.py ready <task_dir> 列可执行字段（前置门禁）；每字段派发必须用 executor.py t3 <task_dir> <field> 生成 T3 六件套（协议由模块 + mind 推导），派发 prompt 只能是 T3FILE:v1 零引导语模板；subagent 执行后 executor.py check <field> 验证推进/路由（后置门禁）",
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
        "template_ref": { "type": "string", "description": "可选：复用的三件套骨架路径" },
        "intel_ref": { "type": "string", "description": "可选：情报产物路径" }
      },
      "required": ["task", "deliverable"],
      "additionalProperties": false
    },
    "dispatch_t3": {
      "type": "object",
      "description": "executor.py t3 生成的步骤派发协议（fill/rules/schema/data/write/forbidden），主 agent 不手工构造",
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
  "write": "tasks/<task_id>/（draft/ 草稿态 → 物化后：steps.json/minds.json 定稿 + artifacts/ + dispatch/*.t3.json + feedback/）",
  "forbidden": [
    "主 agent 不得自行设计字段序列——编排是编排者 subagent 按 orchestrator.t3.json 的职责",
    "主 agent 不得用散文给执行 subagent 派发指令——派发必须走 executor.py t3 生成的 T3（prompt 只能是 T3FILE:v1 读取 <file> 并按内容执行，零引导语）",
    "不得跳过 scripts/validate.py 机械校验（草稿态与定稿态都要验）",
    "不得跳过独立审计（多路 subagent，多脑子纠错）",
    "产物必须物化到任务目录，不留对话上下文",
    "主 agent 不得中途改变已定稿装配表——需改动回 Stage A 重新收敛",
    "不得把 draft/ 当执行态——草稿只用于设计收敛，物化（复制到任务根）后才进入状态机",
    "不得把本 skill 当散文模板阅读后自由发挥——协议字段即约束"
  ]
}
```

## 装配产物（编排者产出）

| 文件 | 回答的问题 | 约束 schema |
|------|-----------|-------------|
| steps.json | 装配表：字段序列（generate_N / discriminate_N_xxx）+ 模块选择 + inputs 连线 + routing | `schemas/steps.schema.json` |
| modules.json | 模块库（produce/mind/output_schema/routing/skills/mcp）——内置在 `modules/`，任务级可扩展 | `schemas/modules.schema.json` |
| minds.json | 认知参数集（mind-write/extract/transform/query/reason/fill/verify/audit/classify…） | `schemas/minds.schema.json` |

**完整状态机（三层分离）**：
- `steps.json` — 结构层：装配表（字段定义 + 模块 + 连线 + 路由），编排者产出，物化后定稿
- `op-table.json` — 路由层：条件路由表（`<field>=<verdict> → dispatch`），由装配表在 materialize 时机械生成，供审计/可视化（cataclysm op-table 同构）
- `state.csv` — 状态层：追加行稀疏表（field/produce/status/judgment/module/routing_target/ts），**状态真相源**——每个字段执行/回修/重试都追加一行，最后一行=当前状态，全部历史=审计轨迹（cataclysm state.csv 同构）；steps.json 只保留结构，不存运行状态

**模块 = 两级**：级别一 `produce`（generate 产出推进 / discriminate 判断路由）+ 级别二 `mind`（认知参数集，决定 forbidden）。模块自带协议（action/verify/output_schema/forbidden），编排者选模块 + 连线，不发明协议。

## 编排与审计的 T3 协议（零散文派发，设计收敛循环）

**元流程与执行态分离**：编排/审计是"设计收敛"（草稿态，subagent 同上下文多轮循环），只有收敛后才物化为执行态。主 agent 只做管道：

```
编排：把 data 填入 templates/orchestrator.t3.json → 整体作为 task 派给编排者 subagent → draft/
校验：validate.py draft/ → 失败则 send_message 编排者改（延续同一会话）→ 再验（循环）
审计：把 data 填入 templates/audit.t3.json → 派独立审计 subagent 读 draft/ → 意见
回流：audit verdict=revise → 意见送回编排者修改 → 再审（循环直到 pass）
物化：收敛后机械复制 draft/ → 任务根（steps.json/minds.json 定稿）
执行：executor.py t3 <task_dir> <field> → T3FILE:v1 派发（见下）
```

**为什么分离**：① subagent 减压——编排者在同一会话接收 validate 错误 + 审计意见多轮修改，不用每轮重讲任务；② 干净——任务目录只出现定稿，草稿迭代留在设计阶段；③ 审计真正闭环——意见回流到编排者修改，且保留多脑子原则（审计者每次独立上下文）。

- 编排者 mind：`mind-orchestrator`（C05 早期锚定 / C03 路径锁定 / C02 执行启动缺失——先列子目标再定步骤、op/mind 由问题驱动非模板驱动、验收必须机械可查）；指令已内置进 orchestrator.t3.json 的 rules（与 minds.json 定义一致）
- 审计者 mind：`mind-orchestration-audit`（C05 确认偏误 / M07 谄媚 / C06 阈值失敏——每维至少找一条可改进点、verdict 默认 revise 倾向、每条意见必须附 evidence 引用）；指令已内置进 audit.t3.json 的 rules（与 minds.json 定义一致）
- 能力真实性：编排与审计的插槽引用都必须存在于 `artifacts/capabilities.json`（discover.py 产出），validate.py 机械校验

## mind 注入双轨制（directive 正向 vs constraint 负向）

方法论工具库（Obsidian：AI Factory/方法论工具库.md、思维参数手册、LLM认知心理学）证实：**mind 注入分两大类**——

- **directive（正向注入，crusher 类）**：给 LLM 一条思考路径（CRUSH_STEP_1-4、反目标构造、TRIZ 矩阵…），科研步骤用。`params.instruction` 注入 rules。
- **constraint（负向约束，FORBIDDEN 类）**：日常任务主力。默认 LLM 具备产出能力，问题不是"不会做"而是"在幻觉区滑行"——用 FORBIDDEN 封死错路，让正确的路成为唯一选项。`forbidden` 数组注入 T3 forbidden（协议层）+ rules 声明"硬约束，违反即不合格"。

依据（LLM认知心理学）："结构 > 内容。FORBIDDEN 比'请用 X 方法'有效一百倍——不是提供新路，是物理封死老路。" 五类退化（摘果/摔门/融合/检索/散文）各自对应阻断手段。

**认知模态配比（认知模态交响乐）**：每条步骤需要不同的 LLM 心理状态，同一 prompt 风格覆盖全管线 = 模态错配。mind 带 `role`（diagnose/scan/architect/write/audit/review/execute）+ `forbidden_density`（zero/precise/dense）：
- **diagnose（零约束）**：广域扫视——大量输入、不限搜索、鼓励类比；给 FORBIDDEN 会漏掉现象
- **write/execute（精准）**：心流构造——FORBIDDEN 命题级精准，不堵对路；通用禁令 = 负面心流
- **audit/review（密集）**：对抗怀疑——长 FORBIDDEN 清单 + 预设命题为假（executor 自动注入"产出可能有错——逐条质疑"）

**FORBIDDEN 最优粒度 = 命题级**：mind 通用 forbidden 之外，模块可声明 forbidden（模块级），装配表字段可声明 forbidden（命题级绑定到具体产出/输入），executor 追加进 T3 forbidden。通用禁令过度约束，命题级才精准。

**输入不可变性（三层绕过优先级）**：LLM 找最小阻力绕过路径——改输入数据（最低费力）> 换算法 > 改约束。T3 forbidden 默认含"禁止修改输入数据或依赖产物——输入来自物化文件，不可变"。

**日常 FORBIDDEN 库**（constraint 型 mind 的 forbidden 清单，从五类退化阻断提炼）：
- 禁编造（幻觉）——不得输出输入中不存在的事实/数字/来源
- 禁模糊（散文退化）——不得输出不可溯源的概括
- 禁摘果——不得只挑最容易验证的条目
- 禁只做部分——覆盖全部产出字段

**模板内置 mind 分类**：
| mind | type | role/密度 | 来源 | 用途 |
|---|---|---|---|---|
| mind-default | constraint | execute/precise | 五类退化阻断 | 日常执行默认约束 |
| mind-focus | constraint | execute/precise | 步骤边界 | 防止 scope 扩散 |
| mind-diagnose | constraint | diagnose/zero | 模态交响乐 | 广域扫视（诊断类步骤） |
| mind-trap-detect | constraint | audit/dense | llm-trap-detect.js | 认知陷阱检测 |
| mind-decompose | constraint | architect/precise | systemic-decomposition.js | 系统分解（找边界非实现） |
| mind-audit | constraint+enforce | audit/dense | I2 门 | 证据强制审计 |
| mind-orchestrator | directive | — | C05/C03/C02 | 编排者心智 |
| mind-orchestration-audit | directive | — | C05/M07/C06 | 编排审计心智 |
| mind-crusher | directive | — | organs.js CRUSH_STEPS | 翻墙（科研） |
| mind-anti-goal | directive | — | anti-goal.js | 反目标（科研） |

## mind 具象化（enforce 四层，mind 从散文升级为协议）

对照实验证明（2026-08-15，n=1/组）：散文 mind 指令会改变行为（evidence 0/8→8/8）但产出**路径自指引用**（`材料/决策/D1`——subagent 引用自己的输出）；且聚焦新要求会**牺牲原有字段**（owner/deadline 丢失）。因此 mind 必须具象化——minds.json 每个 mind 可带 `enforce` 四层：

```json
"enforce": {
  "fill": ["每条结论必须附 evidence 字段，值为来源文件原文片段（非路径引用）"],
  "schema": {
    "required": ["evidence", "owner"],
    "properties": {"evidence": {"type": "array", "items": {"type": "string"}}}
  },
  "forbidden": ["禁止用路径式引用（如 材料/决策/D1）充当证据"],
  "check": {"type": "evidence_in_source", "field": "evidence", "source": "artifacts/material.md"}
}
```

- **fill** → 追加进 T3 fill（强制产出要求）
- **schema** → 合并进 T3 schema（`required` 并集——**必须包含该步骤原有全部必需字段**，否则 subagent 聚焦新要求会丢旧字段）
- **forbidden** → 追加进 T3 forbidden（禁止应付）
- **check** → `executor.py check` 机械执行：产物中 field 的每个值必须作为子串出现在 source 文件中（空白折叠）——路径引用/自指引用被拒

实验验证：路径引用 8/8 被拒（exit 1）→ 具象化后 24/24 evidence 为真实原文摘录并全部通过 check。

## 主 agent 机械命令清单（唯一允许的操作）

```
python scripts/discover.py   <task_dir> [--skill-dirs <dirs>] [--runtime-skills <a,b>] [--runtime-mcp <obsidian,...>]  # 本机能力扫描 → artifacts/capabilities.json
python scripts/executor.py materialize <task_dir>      # 设计收敛 → 执行态：复制 draft/ 到任务根（物化）
python scripts/executor.py ready   <task_dir>          # 列可执行字段（前置门禁）
python scripts/executor.py t3      <task_dir> <field>  # 生成字段 T3 六件套（派发唯一依据，协议由模块+mind推导）
python scripts/executor.py check   <task_dir> <field>  # 后置门禁：验证产物并推进/路由（判别式路由生效）
python scripts/executor.py retry   <task_dir> <field>  # failed → pending（重试）
python scripts/executor.py reset   <task_dir> <field>  # needs_reorchestration → pending
python scripts/executor.py status  <task_dir>          # 状态机全景
python scripts/validate.py         <task_dir>          # 装配表机械校验（草稿态与定稿态都可用）
python scripts/compare.py          <task_dir>          # 收尾全量验证
```

派发模板（唯一允许的 subagent prompt）：
```
T3FILE:v1 读取 <task_dir>/dispatch/<field>.t3.json 并按内容执行。产出写入 <task_dir> 下的 write 相对路径。
```

## 偏离对抗

agent 执行本 skill 会偏离（解释性偏离 / 选择性遵循 / 上下文挤压 / 静默偏离）。对抗手段全部机械化：
- **schema 机械校验**（validate.py）——格式偏离被拦截
- **T3 派发**（executor.py t3）——执行指令结构化，散文无从注入
- **产物物化**——隐形偏离在交接处暴露
- **独立审计**（多路 subagent）——静默偏离被抓
- **失败回流**（Stage 3）——编排偏离被修正

不要用"写得更详细的散文"对抗偏离，用结构。
