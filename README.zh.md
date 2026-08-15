# orchestration-skill

面向 AI agent 的长任务编排引擎：可靠性来自**模块装配的状态机 + 机械化执行 + 两层审计**，而不是模型的长链能力。

主 agent 浓缩意图 → 编排者 subagent 从模块库挑模块、连线、设路由，产出字段驱动的装配表（`steps.json` fields + `minds.json`）→ 机械执行器按字段语义驱动状态机（`generate_N` 产出推进 / `discriminate_N_xxx` 判断路由）→ 每字段通过 **T3 协议**（fill/rules/schema/data/write/forbidden，零引导语）派发 → 所有产物落到磁盘（文件夹 = 外部记忆，断点续跑）→ 两层审计拦截偏离。

## 为什么

长任务失败不是因为模型弱，而是因为不可靠在长链上复利：

- 步骤模糊化，错误静默传播
- 编排者的散文指令被重新解读（"协议被散文包裹"）
- 状态只活在上下文里，续跑即丢失

本 skill 把这一切推入**结构**：JSON-Schema 约束的 JSON 契约、字段语义的状态机、模块推导的协议、T3 派发、每个边界的机械门禁。不要用更详细的散文对抗偏离，用结构。

## 特性

- **模块装配（搭积木）** — 编排者是装配师不是协议设计师：从 `modules/` 库挑模块（mod-generate/extract/transform/query/reason/fill/verify/audit/classify/mind-decider）、连线 inputs、给判别式设 routing。模块自带协议（produce/mind/output_schema/forbidden）
- **两级模块模型** — 级别一 `produce`：`generate`（产出落盘即推进）vs `discriminate`（判断值路由分支）；级别二 `mind`：认知参数集（write/extract/transform/query/reason/fill/verify/audit/classify/decider）决定 forbidden。字段名即状态语义：`generate_01`、`discriminate_01_verdict`
- **字段语义状态机** — `scripts/executor.py`：`ready`/`check`/`retry`/`reset`/`status`；前置门禁（输入依赖已物化）、后置门禁（generate 验 schema / discriminate 验判断值 ∈ routing）、判别路由让状态机从线性变分支（pass→下一步、revise→回修、reject→stop）
- **审计回退机制** — 判别点 routing 支持对象形态 `{to, counter, limit, escalate, mind}`：回退目标 + 计数器 + 超限换脑 + 路由级 mind 覆盖。`materialize` 展开为 op-table（escalate 规则在前，排它由顺序 + 条件互斥保证）。计数器活在主 agent 上下文（`--state`），不落 state.csv——插件版主 agent 自然知道轮次；node 版程序主导才需数据化
- **mind-decider（运行时思维选择）** — 复杂回退（降本、重构）不静态绑定 `routing.mind`：判别失败先路由到策略师判别式（`mod-mind-decider`，产出 chosen_mind + 机械可复算的 basis），读审计证据（成本结构/固定成本占比/可议价空间/失败类型）在运行时选重试思维。端到端已验证：固定成本墙场景选 mind-crusher 而非 mind-reason，回修结果 $12,676 与直接 crusher 运行完全一致（gap 收窄 72%）
- **T3 协议派发** — `executor.py t3` 从模块 + mind + 依赖产物生成六件套派发（fill/rules/schema/data/write/forbidden）；唯一允许的 subagent prompt 是零引导语文件引用——散文无从包裹协议。**编排与编排审计同样走 T3 派发**（`templates/orchestrator.t3.json` / `templates/audit.t3.json`）
- **能力插槽** — 模块声明 `skills`/`mcp`；执行器把插槽注入 T3 派发，执行 subagent 直接装配 skill/MCP 而非自行发现
- **本机能力扫描** — `scripts/discover.py` 物化 `artifacts/capabilities.json`（DSH patch 层的 MCP server + skill 目录 + 运行时补充）；`validate.py` 拒绝任何不在清单中的插槽引用
- **mind 限制** — `mind-orchestrator` 与 `mind-orchestration-audit` 把 LLM 心理学守卫（早期锚定/路径锁定/谄媚/确认偏误）直接编入编排与审计的 T3 rules
- **mind 注入双轨制** — mind 分 `directive`（crusher 类正向路径，科研步骤）与 `constraint`（FORBIDDEN 类负向守卫，日常任务主力）：默认假设 LLM 具备产出能力，constraint mind 的职责是封死幻觉区滑行，而非教方法
- **认知模态配比** — 每步需要不同的 LLM 心理状态：`role`（diagnose/scan/architect/write/audit/review）+ `forbidden_density`（zero/precise/dense）。诊断类零约束（广域扫视）、写手类命题级精准约束（通用禁令=负面心流）、审计类密集约束+预设命题为假；模块/mind/字段级 `forbidden` 把禁令绑定到具体命题
- **mind 具象化（enforce）** — mind 的 `enforce` 四层（fill/schema/forbidden/check）合并进 T3 派发；`executor.py check` 机械验证证据是否来自来源文件原文。对照实验证明：散文 mind 指令只产出路径自指"证据"（`材料/决策/D1`）且丢失原有字段——enforce 把 mind 从散文升级为协议
- **两层审计** — 静态（多路 subagent 独立审计装配表）+ 动态（同字段 3 次同类失败 → `needs_reorchestration`；执行性错误 vs 编排性错误判别）
- **失败回流** — 失败轨迹回流进模板，引擎对每类任务的装配越用越准
- **产物物化** — 每字段写入 `artifacts/<field>.json`；断点续跑、零上下文损耗交接
- **零依赖** — 纯 Python 标准库（`json`/`os`/`sys`/`tempfile`/`collections`），有 Python 3.7+ 即可运行

## 快速开始

```bash
# 机械校验装配表（字段命名/模块引用/routing/无环）
python scripts/validate.py examples/demo-task

# 查看状态机全景
python scripts/executor.py status examples/demo-task

# 列出可执行字段（前置门禁）
python scripts/executor.py ready examples/demo-task

# 为某字段生成 T3 派发（协议由模块 + mind 推导）
python scripts/executor.py t3 examples/demo-task generate_01
```

任务目录**在用户项目文件夹下创建**（`<project>/<task_id>/`），绝不在 skill 安装目录下创建。在项目任务目录里运行 `scripts/discover.py` 扫描本机能力。

## 工作流程

**skill 元状态机（设计收敛）与任务状态机（执行）分离**：

1. **Stage 0 初始化**：在用户项目文件夹建 `<project>/<task_id>/{artifacts,feedback,draft}`；运行 `scripts/discover.py` 物化 `artifacts/capabilities.json`（本机能力清单）；把用户意图浓缩进 `data`（schema 约束）。
2. **Stage A 编排（设计收敛，草稿态）**：以 `templates/orchestrator.t3.json`（填入 data、引用 modules_ref/capabilities）派发编排者 subagent；编排者按 `mind-orchestrator`（防早期锚定/防路径锁定）产出装配表草稿到 `draft/`——字段序列（`generate_N`/`discriminate_N_xxx`）、模块选择、inputs 连线、判别式 routing。
3. **Stage B 审计编排（同上下文多轮循环）**：`validate.py draft/`（机械：字段命名/模块引用/routing 合法性/依赖无环），失败 → `send_message` 编排者（延续同一会话）修改；再派独立审计 subagent 经 `templates/audit.t3.json` 按 `mind-orchestration-audit`（防确认偏误/防谄媚）读 `draft/` 产出意见，revise → 意见回流编排者再改。循环直到校验通过 + 审计 pass。多脑子纠错：审计者每次独立上下文。
4. **Stage C 物化（进入执行态）**：收敛后主 agent 机械复制 `draft/` 到任务根（`executor.py materialize`）——装配表定稿；此后改动回 Stage A。
5. **Stage 2 执行**：`ready` 列可执行字段（前置门禁）→ `t3` 从模块+mind+依赖产物生成 T3 派发 → subagent 零引导语执行 → `check` 验证推进/路由（generate 验 schema / discriminate 验判断值）。
6. **Stage 3 动态审计**：3 次同类失败 → `needs_reorchestration`；判别执行性错误（重试）与编排性错误（回 Stage A）。
7. **Stage 4 收尾**：`compare.py` 全量验证；装配表归档到 `templates/` 或 `examples/`。

## 作为 DeepSeek Harness skill 使用

`SKILL.md` 遵循 DSH skill 格式（frontmatter + schema 驱动协议）。把 `dsh-skill-filesystem` 的 `customSkillDirs` 指向本目录，或复制进你的 skill 根目录。执行脚本经任意带 Python 的 shell 调用。

## 目录

```
SKILL.md            # 协议（schema 驱动契约形态，给 LLM 读）
Description.md      # 人类阅读版（理念/架构/工作流）
schemas/            # JSON Schema（steps 装配表 / modules / minds / op-table）
modules/            # 模块库（produce + mind + output_schema + forbidden）
scripts/            # discover.py / validate.py / executor.py / compare.py（纯标准库）
templates/          # 装配模板 + 编排者 T3 + 审计 T3 + mind 参数集
examples/           # demo-task（线性）、bad-example（负例）、eco-analysis（研究）、quant-adaptive（并行组）、dsh-client（判别路由）
```

任务目录**在本仓库之外**——在用户项目文件夹下创建 `<project>/<task_id>/`，绝不在 skill 安装目录下创建。

## License

MIT
