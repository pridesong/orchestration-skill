# orchestration-skill

**长任务不该贵到必须用前沿模型。本引擎让廉价模型跑出前沿模型的可靠性——把可靠性从模型身上搬进结构里。**

核心逻辑：长任务失败不是因为模型在某一步弱，而是不可靠在长链上复利。与其花钱买更强的模型把整条链装进它的上下文，不如**把长链拆成廉价模型轻松胜任的小步**，让链的可靠性由机械结构承担：

- **状态在磁盘不在上下文** — 每步写 `artifacts/<field>.json`；断点续跑、零上下文损耗、只重跑失败的那一步
- **每个边界有机械门禁** — `validate`/`check`/`compare` 机械拦截幻觉与格式错误，不依赖模型自觉
- **多次廉价调用 > 一次昂贵调用** — 编排者 + 独立审计 + 动态审计，多脑子补足单次推理弱
- **零引导语派发（T3）** — subagent prompt 是 regex 锁定的文件引用（`T3FILE:v1 读取 <file> 并按内容执行`）；散文无法包裹协议，廉价模型没有漂移空间

## 为什么廉价模型跑得动

| 廉价模型的短板 | 本引擎怎么把它变成优势 |
|---|---|
| 上下文小 | 状态在磁盘；每次派发只带当前这一步的输入 |
| 容易幻觉 | 每个产物过机械门禁（schema/路由合法域/证据原文验证）——不信任模型自检 |
| 长链薄弱 | 每个字段是独立小任务；长链可靠性在 op-table + 审计，不在一次长生成 |
| 重跑成本高 | 断点续跑——第 9 步失败只重跑第 9 步，不重跑整个任务 |
| 散文指令下漂移 | 派发 prompt 被 pattern 锁死；FORBIDDEN 物理封死错路 |

## 实测证据

一个完整医药供应链任务（PVG→EZE 温控空运，1000kg，$11,500 硬预算）在廉价模型上全链路跑通：11 个字段（报价/海关/天气/航线/成本NPV/仪表板/审计/结论），每个都由锁定的 T3 prompt 派发。

降本回退对照实验展示了结构带来的差距：

| | mind-reason（方案内推导） | mind-crusher（翻墙） |
|---|---|---|
| 总成本 | $15,730 | **$12,676** |
| 预算缺口 | $4,230 | **$1,176**（收窄 72%） |
| 预算内可行运量 | 500kg（50%） | ≈888kg（89%） |

且当回修经由运行时 **mind-decider** 路由（读审计证据——固定成本墙 vs 单价墙——再选思维）时，精确复现 $12,676：选择是机械可复算的判别决策，不是散文运气。

## 工作原理

主 agent 浓缩意图 → **编排者 subagent** 从模块库挑模块、连线、设路由，产出字段驱动装配表（`steps.json` + `minds.json`）→ 机械执行器按字段语义驱动状态机（`generate_N` 产出推进 / `discriminate_N_xxx` 判断路由）→ 每字段经 **T3 协议**派发 → 产物落盘 → 两层审计拦截偏离。

关键机制（详见 `Description.md`）：
- **模块装配** — 编排者是装配师不是协议设计师；模块自带协议（produce/mind/output_schema/forbidden）
- **op-table 由声明展开** — executor 零推导：编排者声明的 `next`/`parallel`/`routing` 展开为排它条件路由表。并行组写同一行 state.csv（多条件 AND）；审计回退走 `{to, counter, limit, escalate, mind}`
- **mind-decider** — 复杂回退不静态绑死思维；策略师判别式在运行时读审计证据选重试思维（见实测证据）
- **T3 零引导语派发** — 六件套协议（fill/rules/schema/data/write/forbidden）由模块+mind+依赖产物生成；派发 prompt 被 regex 锁死；编排与审计走同一协议
- **mind 双轨制** — `directive`（crusher 类正向路径）vs `constraint`（FORBIDDEN 类负向守卫）；认知模态配比（`role` + `forbidden_density`）匹配每步心理状态；`enforce` 把 mind 从散文升级为可机械检查的协议
- **两层审计 + 失败回流** — 静态（独立审计装配表）+ 动态（3 次同类失败 → 重新编排）；失败轨迹回流模板
- **零依赖** — 纯 Python 标准库，有 Python 3.7+ 即可运行

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
