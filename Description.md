# orchestration-skill — 人类阅读版

> 本文件给**人类**看：理念、架构、为什么。给 LLM 的协议在 `SKILL.md`（协议化，人类不需要读它）。

## 这是什么

**长任务不该贵到必须用前沿模型。** 本引擎让廉价模型跑出前沿模型的可靠性——把可靠性从模型身上搬进结构里。

核心逻辑：长任务失败不是因为模型在某一步弱，而是不可靠在长链上复利。与其花钱买更强的模型把整条链装进它的上下文，不如把长链拆成廉价模型轻松胜任的小步，让链的可靠性由机械结构承担——状态在磁盘（外部记忆，断点续跑）、每个边界有机械门禁（validate/check/compare 不信任模型自检）、多次廉价调用 > 一次昂贵调用（多脑子补足）、派发 prompt 被 regex 锁死（散文无法包裹协议，模型没有漂移空间）。

核心路径：主 agent 浓缩意图 → 编排者 subagent 从模块库挑模块、连线、设路由，产出装配表（`steps.json` + `minds.json`）→ 机械执行器按字段语义驱动状态机 → 每字段通过 **T3 协议** 派发（零引导语）→ 产物落到磁盘（文件夹 = 外部记忆，断点续跑）→ 两层审计拦截偏离。

实测（pharma-scm-001，廉价模型全链路）：降本回退对照实验 mind-crusher $12,676 vs mind-reason $15,730，预算缺口收窄 72%；经 mind-decider 运行时选思维精确复现 $12,676。

## 设计哲学（一脉相承）

1. **LLM 的归 LLM，人类的归人类**。人类不需要读协议（`SKILL.md` 协议化），LLM 不需要读散文解释（本文件）。本仓库所有自创 skill 同源。
2. **结构 > 内容。FORBIDDEN 比"请用 X 方法"有效一百倍**——不是提供新路，是物理封死老路。
3. **协议不能被散文包裹**。散文 = 滑行空间。派发 prompt 只能是 `T3FILE:v1 读取 <file> 并按内容执行`，任何多余文字都是污染（会在实验中制造双信号源）。
4. **编排层设计状态机形态**。op-table 完全由编排者声明（`next`/`parallel`/`routing`）展开，executor 零推导。
5. **不要用"写得更详细的散文"对抗偏离，用结构**。

## 核心架构

### 模块装配（搭积木）

编排者是**装配师**不是协议设计师：从 `modules/` 库挑模块、连线 `inputs`、给判别式设 `routing`。模块自带协议（produce/mind/output_schema/forbidden）。

**两级模块模型**：
- 级别一 `produce`：`generate`（产出落盘即推进）vs `discriminate`（判断值路由分支）
- 级别二 `mind`：认知参数集（write/extract/transform/query/reason/fill/verify/audit/classify/decider），决定 forbidden

字段名即状态语义：`generate_01`、`discriminate_01_verdict`。

### 完整状态机（三层分离）

| 层 | 文件 | 回答的问题 | 谁产出 |
|---|---|---|---|
| 结构层 | `steps.json` | 装配表：字段序列 + 模块 + 连线 + 判别点路由设计 | 编排者，物化后定稿 |
| 路由层 | `op-table.json` | 条件路由表（`<field>=<value> → dispatch`） | materialize 从声明展开，**不同项目形态不同**（线性/审计回退/并行），排它由顺序 + 条件互斥保证 |
| 状态层 | `state.csv` | 每步一行，只填当步字段（无继承），最后一行 = 当前状态；字段完成性 = 产物文件存在 | 执行器追加 |

并行语义：并行组字段**写在同一行**（state.csv 同行填充），op-table 用多条件 AND 表达"组完成才推进"；串行字段各占一行。

### 判别点路由设计（编排者设计每个判别点怎么路由）

```json
"routing": {
  "pass":   "generate_03",
  "revise": {"to": "generate_01", "counter": "revise_count", "limit": 2,
             "escalate": "mind-decider", "mind": "mind-flow"},
  "reject": "stop"
}
```

展开为 op-table（escalate 条件在前，排它）：
```
discriminate_01_verdict=revise,revise_count>=2 → mind-decider   （超限换脑）
discriminate_01_verdict=revise → generate_01, revise_count+1, mind: mind-flow  （回退+计数+心流）
```

**计数（轮次/次数）由主 agent 上下文管理**（`executor.py ready --state '{"revise_count": 2}'`），不落 csv——插件版主 agent 完全知道第几轮第几次；node 版程序主导才需要数据化。简单任务无需机制声明，路由用字符串目标即可。

## 工作流程（元状态机与任务状态机分离）

**设计收敛（草稿态）与执行（执行态）分离**——编排/审计是设计收敛，收敛后才物化为执行态：

```
Stage 0  初始化：在项目文件夹建任务目录 <project>/<task_id>/{artifacts,feedback,draft}；
         运行 discover.py 物化 capabilities.json（本机能力清单）
Stage A  编排：data 填入 orchestrator.t3.json → 派编排者 subagent（mind-orchestrator）→ draft/
Stage B  审计编排（同上下文多轮循环）：
         validate.py draft/ 机械校验 → 失败 send_message 编排者改（同一会话）→ 再验
         派独立审计 subagent（audit.t3.json，mind-orchestration-audit）→ revise 回流再改
Stage C  物化：收敛后机械复制 draft/ → 任务根（steps.json/minds.json 定稿）
Stage 2  执行：ready → t3 生成六件套 → subagent 零引导语执行 → check 验证推进/路由
Stage 3  动态审计：同字段 3 次同类失败 → needs_reorchestration（判执行错 vs 编排错）
Stage 4  收尾：compare.py 全量验证 + 装配表归档 templates/ 或 examples/
```

**为什么分离**：① subagent 减压——编排者在同一会话接收 validate 错误 + 审计意见多轮修改，不用每轮重讲任务；② 干净——任务目录只出现定稿，草稿迭代留在设计阶段；③ 审计真正闭环——意见回流到编排者修改，且保留多脑子原则（审计者每次独立上下文）。

## 关键机制

### T3 协议（零散文派发）

`executor.py t3` 从模块 + mind + 依赖产物生成六件套：**fill / rules / schema / data / write / forbidden**。唯一允许的 subagent prompt 是零引导语文件引用：

```
T3FILE:v1 读取 <task_dir>/dispatch/<field>.t3.json 并按内容执行。产出写入 <task_dir> 下的 write 相对路径。
```

**编排与编排审计同样走 T3 派发**（`templates/orchestrator.t3.json` / `templates/audit.t3.json`）。

### 审计回退机制

判别式 routing 对象形态 `{to, counter, limit, escalate, mind}`：回退目标 + 计数器 + 超限换脑 + 路由级 mind 覆盖。`materialize` 展开为 op-table（escalate 规则在前）。回修**不删产物**——op-table 只读最后一行，`discriminate_N 未通过 → 指向回退字段`，下一次完成后 csv 最后一行又会指向判别式，自然重判。

### mind-decider（运行时思维选择）

复杂回退（降本、重构）不静态绑定 `routing.mind`：判别失败先路由到策略师判别式（`mod-mind-decider`，产出 `chosen_mind` + 机械可复算的 `basis`），读审计证据（成本结构/固定成本占比/可议价空间/失败类型）在运行时选重试思维。

实验验证（2026-08-15）：同是降本回退，mind-reason 只在方案内换承运商（−590），mind-crusher 翻转成本结构假设（议价/租赁/复用，−3054）——固定成本墙场景选 mind-crusher 而非 mind-reason，回修结果 $12,676 与直接 crusher 运行完全一致（gap 收窄 72%）。

### mind 注入双轨制

方法论工具库证实 mind 注入分两大类：
- **directive（正向注入，crusher 类）**：给 LLM 一条思考路径（CRUSH_STEP_1-4、反目标构造、TRIZ 矩阵…），科研步骤用。`params.instruction` 注入 rules。
- **constraint（负向约束，FORBIDDEN 类）**：日常任务主力。默认 LLM 具备产出能力，问题不是"不会做"而是"在幻觉区滑行"——用 FORBIDDEN 封死错路，让正确的路成为唯一选项。`forbidden` 注入 T3 forbidden + rules 声明"硬约束，违反即不合格"。

**认知模态配比（认知模态交响乐）**：每步需要不同的 LLM 心理状态，同一 prompt 风格覆盖全管线 = 模态错配。mind 带 `role`（diagnose/scan/architect/write/audit/review/execute）+ `forbidden_density`（zero/precise/dense）：
- **diagnose（零约束）**：广域扫视——大量输入、不限搜索、鼓励类比；给 FORBIDDEN 会漏掉现象
- **write/execute（精准）**：心流构造——FORBIDDEN 命题级精准，不堵对路；通用禁令 = 负面心流
- **audit/review（密集）**：对抗怀疑——长 FORBIDDEN 清单 + 预设命题为假（executor 自动注入"产出可能有错——逐条质疑"）

**FORBIDDEN 最优粒度 = 命题级**：mind 通用 forbidden 之外，模块可声明 forbidden（模块级），装配表字段可声明 forbidden（命题级绑定到具体产出/输入）。

**输入不可变性（三层绕过优先级）**：LLM 找最小阻力绕过路径——改输入数据（最低费力）> 换算法 > 改约束。T3 forbidden 默认含"禁止修改输入数据或依赖产物——输入来自物化文件，不可变"。

### mind 具象化（enforce 四层，mind 从散文升级为协议）

对照实验证明（2026-08-15，n=1/组）：散文 mind 指令会改变行为（evidence 0/8→8/8）但产出**路径自指引用**（`材料/决策/D1`）；且聚焦新要求会**牺牲原有字段**（owner/deadline 丢失）。因此 mind 必须具象化——minds.json 每个 mind 可带 `enforce` 四层：

```json
"enforce": {
  "fill": ["每条结论必须附 evidence 字段，值为来源文件原文片段（非路径引用）"],
  "schema": {"required": ["evidence", "owner"], "properties": {...}},
  "forbidden": ["禁止用路径式引用（如 材料/决策/D1）充当证据"],
  "check": {"type": "evidence_in_source", "field": "evidence", "source": "artifacts/material.md"}
}
```

- **fill** → 追加进 T3 fill；**schema** → 合并进 T3 schema（`required` 并集——必须包含该步骤原有全部必需字段，否则 subagent 聚焦新要求会丢旧字段）；**forbidden** → 追加进 T3 forbidden；**check** → `executor.py check` 机械执行（evidence 必须作为子串出现在 source 文件中，路径引用被拒）。

实验验证：路径引用 8/8 被拒 → 具象化后 24/24 evidence 为真实原文摘录并全部通过 check。

## 偏离对抗

agent 执行本 skill 会偏离（解释性偏离 / 选择性遵循 / 上下文挤压 / 静默偏离）。对抗手段全部机械化：
- **schema 机械校验**（validate.py）——格式偏离被拦截
- **T3 派发**（executor.py t3）——执行指令结构化，散文无从注入
- **产物物化**——隐形偏离在交接处暴露
- **独立审计**（多路 subagent）——静默偏离被抓
- **失败回流**（Stage 3）——编排偏离被修正

## 目录结构

```
SKILL.md            # 协议（给 LLM，schema 驱动契约形态）
Description.md      # 本文件（给人类）
schemas/            # JSON Schema（steps 装配表 / modules / minds / op-table）
modules/            # 模块库（produce + mind + output_schema + forbidden）
scripts/            # discover.py / validate.py / executor.py / compare.py（纯标准库）
templates/          # 装配模板 + orchestrator T3 + audit T3 + minds 参数集
examples/           # demo-task（线性）、bad-example（负例）、eco-analysis（研究）、quant-adaptive（并行）、dsh-client（判别路由）
```

任务目录**不在本仓库**——在用户的项目文件夹下创建 `<project>/<task_id>/`（见 SKILL.md）。

## 快速开始

```bash
# 在项目文件夹建任务目录，扫描本机能力
mkdir -p my-project/tasks/my-task
python scripts/discover.py my-project/tasks/my-task --runtime-skills web-search,lark-doc --runtime-mcp obsidian

# 机械校验装配表
python scripts/validate.py examples/demo-task

# 查看状态机 / 列出可执行字段 / 生成 T3 派发
python scripts/executor.py status examples/demo-task
python scripts/executor.py ready examples/demo-task
python scripts/executor.py t3 examples/demo-task generate_01
```

## 示例

| 示例 | 演示 |
|---|---|
| examples/demo-task | 线性三步骤（收集→分析→报告），validate 通过路径 |
| examples/bad-example | 五类编排性错误，validate 拦截演示 |
| examples/eco-analysis | 研究任务：检索×3 → 机会分析 → 报告 |
| examples/quant-adaptive | **并行组**（generate_02/03 同行填充 + 多条件 AND）+ 判别路由 |
| examples/dsh-client | 线性 + 三层判别（验证/验收/独立审计） |

## License

MIT
