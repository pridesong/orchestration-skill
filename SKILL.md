---
name: orchestration
description: 长任务编排引擎。接收任务→物化三件套(steps.json/op-table.json/minds.json)→两层审计→机械化执行。触发词：长任务、编排、拆解任务、多步骤执行、任务流水线、编排引擎。
---

# 编排引擎（Orchestration Engine）— schema 驱动硬协议

本 skill 以 JSON Schema / T3 协议表达，**防止主 agent 跑偏**。主 agent 的职责边界由 `forbidden` 锁死：只做意图浓缩（填 `data`）、触发本 skill、执行机械命令（ready/t3/check）、交付确认。其余（编排生成、审计、执行）全部由 subagent 按协议承担。

## 协议（JSON Schema 形态）

```json
{
  "fill": ["data.task", "data.constraints", "data.deliverable"],
  "rules": [
    "Stage 0 初始化：建任务目录 tasks/<task_id>/{artifacts,feedback}；运行 scripts/discover.py <task_dir> --skill-dirs <skill目录> --runtime-skills <本会话可见skill> --runtime-mcp <本机MCP server> 产出 artifacts/capabilities.json（本机能力清单，插槽引用的唯一依据）",
    "Stage 0.5 编排生成：把 data 填入 templates/orchestrator.t3.json 的 data 槽（含 capabilities 引用），整个模板作为 task 字符串派给编排者 subagent（唯一派发方式，禁止散文包装），编排者按 mind-orchestrator 思维产出三件套写入任务目录；编排者不得引用 capabilities.json 之外的能力",
    "Stage 1 第一层审计：scripts/validate.py 机械校验（必须通过，含能力插槽真实性检查）+ 多路 subagent 独立审计；审计派发必须用 templates/audit.t3.json 的 T3 协议（fill/rules/schema/data/write/forbidden 六件套，auditor 按 mind-orchestration-audit 思维独立审查覆盖度/粒度/可执行性/耦合边界/能力真实性），每路产出 artifacts/audit_<route>.json，多路意见汇总；不通过打回重生成",
    "Stage 2 机械化执行：scripts/executor.py ready <task_dir> 列可执行步骤（前置门禁）；每步派发必须用 executor.py t3 <task_dir> <step_id> 生成 T3 六件套，派发 prompt 只能是 T3FILE:v1 零引导语模板；subagent 执行后 executor.py check <step_id> 验证推进（后置门禁）",
    "Stage 3 动态审计：同一步 3 次同类失败自动 needs_reorchestration，判执行性错误（重试）vs 编排性错误（重新编排）",
    "Stage 4 收尾：scripts/compare.py 全量验证 + 三件套归档 templates/ 或 examples/",
    "能力插槽：op 需要外部 skill/MCP 时在 op-table 声明 required_skills/required_mcp（非空字符串数组，空=无）；步骤可在 steps 用 extra_skills/extra_mcp 补充；插槽由 executor.py t3 注入 T3 rules，执行者直接装配而非自行发现；插槽引用必须存在于 capabilities.json",
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
  "write": "tasks/<task_id>/（三件套 + artifacts/ + dispatch/*.t3.json + feedback/）",
  "forbidden": [
    "主 agent 不得自行设计步骤序列——编排是编排者 subagent 按 orchestrator.t3.json 的职责",
    "主 agent 不得用散文给执行 subagent 派发指令——派发必须走 executor.py t3 生成的 T3（prompt 只能是 T3FILE:v1 读取 <file> 并按内容执行，零引导语）",
    "不得跳过 scripts/validate.py 机械校验",
    "不得跳过第一层独立审计（多路 subagent）",
    "产物必须物化到任务目录，不留对话上下文",
    "主 agent 不得中途改变已固化三件套——需改动走 Stage 3 重新编排",
    "不得把本 skill 当散文模板阅读后自由发挥——协议字段即约束"
  ]
}
```

## 三件套（编排者产出，状态层/原语层/认知层）

| 文件 | 层 | 回答的问题 | 约束 schema | 能力插槽 |
|------|-----|-----------|-------------|----------|
| steps.json | 状态层 | 做什么（步骤+依赖+验收标准） | `schemas/steps.schema.json` | `extra_skills`/`extra_mcp`（步级补充） |
| op-table.json | 原语层 | 怎么做（操作原语） | `schemas/op-table.schema.json` | `required_skills`/`required_mcp`（op 级声明） |
| minds.json | 认知层 | 用什么思维做 | `schemas/minds.schema.json` | —（含 mind-orchestrator / mind-orchestration-audit 编排心智） |

## 编排与审计的 T3 协议（零散文派发）

编排（Stage 0.5）与编排审计（Stage 1）同样走 T3 六件套，主 agent 只做管道：

```
编排：把 data 填入 templates/orchestrator.t3.json → 整体作为 task 派给编排者 subagent
审计：把 data 填入 templates/audit.t3.json → 整体作为 task 派给审计 subagent（每路 route 不同）
执行：executor.py t3 <task_dir> <step_id> → T3FILE:v1 派发（见下）
```

- 编排者 mind：`mind-orchestrator`（C05 早期锚定 / C03 路径锁定 / C02 执行启动缺失——先列子目标再定步骤、op/mind 由问题驱动非模板驱动、验收必须机械可查）
- 审计者 mind：`mind-orchestration-audit`（C05 确认偏误 / M07 谄媚 / C06 阈值失敏——每维至少找一条可改进点、verdict 默认 revise 倾向、每条意见必须附 evidence 引用）
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

**FORBIDDEN 最优粒度 = 命题级**：mind 通用 forbidden 之外，steps.json 步骤可声明 `forbidden` 数组（绑定到本步骤具体产出/输入），executor 追加进 T3 forbidden。通用禁令过度约束，命题级才精准。

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
python scripts/executor.py ready   <task_dir>           # 列可执行步骤（前置门禁）
python scripts/executor.py t3      <task_dir> <step_id> # 生成步骤 T3 六件套（派发唯一依据）
python scripts/executor.py check   <task_dir> <step_id> # 后置门禁：验证产物并推进状态
python scripts/executor.py retry   <task_dir> <step_id> # failed → pending（重试）
python scripts/executor.py reset   <task_dir> <step_id> # needs_reorchestration → pending
python scripts/executor.py status  <task_dir>           # 状态机全景
python scripts/validate.py         <task_dir>           # 三件套机械校验（含能力插槽真实性）
python scripts/compare.py          <task_dir>           # 收尾全量验证
```

派发模板（唯一允许的 subagent prompt）：
```
T3FILE:v1 读取 <task_dir>/dispatch/<step_id>.t3.json 并按内容执行。产出写入 <task_dir> 下的 write 相对路径。
```

## 偏离对抗

agent 执行本 skill 会偏离（解释性偏离 / 选择性遵循 / 上下文挤压 / 静默偏离）。对抗手段全部机械化：
- **schema 机械校验**（validate.py）——格式偏离被拦截
- **T3 派发**（executor.py t3）——执行指令结构化，散文无从注入
- **产物物化**——隐形偏离在交接处暴露
- **独立审计**（多路 subagent）——静默偏离被抓
- **失败回流**（Stage 3）——编排偏离被修正

不要用"写得更详细的散文"对抗偏离，用结构。
