# orchestration-skill

面向 AI agent 的长任务编排引擎：可靠性来自**物化的状态机 + 机械化执行 + 两层审计**，而不是模型的长链能力。

主 agent 浓缩意图 → 编排者 subagent 物化三件套（`steps`/`op-table`/`minds`）→ 机械执行器强制状态机 → 每步通过 **T3 协议**（fill/rules/schema/data/write/forbidden，零引导语）派发 → 所有产物落到磁盘（文件夹 = 外部记忆，断点续跑）→ 两层审计拦截偏离。

## 为什么

长任务失败不是因为模型弱，而是因为不可靠在长链上复利：

- 步骤模糊化，错误静默传播
- 编排者的散文指令被重新解读（"协议被散文包裹"）
- 状态只活在上下文里，续跑即丢失

本 skill 把这一切推入**结构**：JSON-Schema 约束的 JSON 契约、硬转移表的状态机、T3 协议派发、每个边界的机械门禁。不要用更详细的散文对抗偏离，用结构。

## 特性

- **三件套契约** — `steps.json`（状态层：做什么）/ `op-table.json`（原语层：怎么做）/ `minds.json`（认知层：用什么思维），全部受 `schemas/` 约束
- **机械化状态机** — `scripts/executor.py`：`ready`/`check`/`retry`/`reset`/`status`；前置门禁（依赖须 passed）、后置门禁（产物对照 `output.schema` 校验）、非法转移被硬转移表拒绝
- **T3 协议派发** — `executor.py t3` 从契约 + 依赖产物生成六件套派发（fill/rules/schema/data/write/forbidden）；唯一允许的 subagent prompt 是零引导语文件引用——散文无从包裹协议。**编排与编排审计同样走 T3 派发**（`templates/orchestrator.t3.json` / `templates/audit.t3.json`）
- **能力插槽** — op 声明 `required_skills`/`required_mcp`，步骤可用 `extra_skills`/`extra_mcp` 补充；执行器把插槽注入 T3 派发，执行 subagent 直接装配 skill/MCP 而非自行发现
- **本机能力扫描** — `scripts/discover.py` 物化 `artifacts/capabilities.json`（DSH patch 层的 MCP server + skill 目录 + 运行时补充）；`validate.py` 拒绝任何不在清单中的插槽引用——编排者只能装配本机真实拥有的能力
- **mind 限制** — `mind-orchestrator` 与 `mind-orchestration-audit` 把 LLM 心理学守卫（早期锚定/路径锁定/谄媚/确认偏误）直接编入编排与审计的 T3 rules
- **mind 具象化（enforce）** — mind 的 `enforce` 四层（fill/schema/forbidden/check）合并进 T3 派发；`executor.py check` 机械验证证据是否来自来源文件原文。对照实验证明：散文 mind 指令只产出路径自指"证据"（`材料/决策/D1`）且丢失原有字段——enforce 把 mind 从散文升级为协议
- **两层审计** — 静态（多路 subagent 独立审计编排）+ 动态（同一步 3 次同类失败 → `needs_reorchestration`；执行性错误 vs 编排性错误判别）
- **失败回流** — 失败轨迹回流进模板，引擎对每类任务的编排越用越准
- **产物物化** — 每步写入任务文件夹；断点续跑、零上下文损耗交接
- **零依赖** — 纯 Python 标准库（`json`/`os`/`sys`/`tempfile`/`collections`），有 Python 3.7+ 即可运行

## 快速开始

```bash
# 扫描本机能力（DSH patch 层 MCP server + skill 目录 + 运行时补充）
python scripts/discover.py tasks/demo-task --runtime-skills web-search,lark-doc --runtime-mcp obsidian

# 机械校验契约（含能力插槽真实性门禁）
python scripts/validate.py examples/demo-task

# 查看状态机全景
python scripts/executor.py status examples/demo-task

# 列出可执行步骤（前置门禁）
python scripts/executor.py ready examples/demo-task

# 为某步生成 T3 派发
python scripts/executor.py t3 examples/demo-task s003
```

## 工作流程

1. **Stage 0 初始化**：建 `tasks/<task_id>/{artifacts,feedback}`；运行 `scripts/discover.py` 物化 `artifacts/capabilities.json`（本机能力清单）；把用户意图浓缩进 `data`（schema 约束）。
2. **Stage 0.5 编排生成**：以 `templates/orchestrator.t3.json`（填入 data、引用 capabilities）派发编排者 subagent；编排者按 `mind-orchestrator`（防早期锚定/防路径锁定）产出三件套。
3. **Stage 1 静态审计**：`validate.py`（机械，含能力插槽真实性）+ 多路 subagent 独立审计——经 `templates/audit.t3.json` 按 `mind-orchestration-audit`（防确认偏误/防谄媚）派发，每路产出 `artifacts/audit_<route>.json`。不过打回重生成。
4. **Stage 2 执行**：`ready` 列可执行步骤（前置门禁）→ `t3` 生成 T3 派发 → subagent 零引导语执行 → `check` 校验产物（后置门禁）。
5. **Stage 3 动态审计**：3 次同类失败 → `needs_reorchestration`；判别执行性错误（重试）与编排性错误（重新编排）。
6. **Stage 4 收尾**：`compare.py` 全量验证；三件套归档到 `templates/` 或 `examples/`。

## 作为 DeepSeek Harness skill 使用

`SKILL.md` 遵循 DSH skill 格式（frontmatter + schema 驱动协议）。把 `dsh-skill-filesystem` 的 `customSkillDirs` 指向本目录，或复制进你的 skill 根目录。执行脚本经任意带 Python 的 shell 调用。

## 目录

```
SKILL.md            # 协议（schema 驱动契约形态）
schemas/            # 三件套的 JSON Schema
scripts/            # discover.py / validate.py / executor.py / compare.py（纯标准库）
templates/          # 契约模板 + 编排者 T3 + 审计 T3
examples/           # demo-task（正例）、bad-example（负例）、eco-analysis（研究任务）
tasks/              # 运行时产物（gitignore）
```

## License

MIT
