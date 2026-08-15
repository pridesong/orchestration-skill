# 示例

四个示例演示装配表的不同形态（字段命名：`generate_N` 产出推进 / `discriminate_N_xxx` 判断路由，op-table 完全由编排者声明展开）。

## demo-task/ — 完整好示例（线性）

三步骤演示任务：收集资料 → 分析 → 生成报告。字段 `generate_01 → generate_02 → generate_03`，串行 next 声明。演示 validate.py 通过路径 + T3 派发。

```bash
python scripts/validate.py examples/demo-task     # 应通过
python scripts/executor.py t3 examples/demo-task generate_01   # 生成 T3 派发
python scripts/compare.py examples/demo-task      # 应报产物缺失（未执行）
```

## bad-example/ — 故意损坏示例（负例）

包含五类编排性错误，用于演示 validate.py 的拦截：
1. `generate_01` 引用不存在的模块 `mod-nonexistent`（模块引用）
2. `generate_02` 的 inputs 引用不存在的字段 `generate_99`（依赖引用）
3. `generate_03` 与 `generate_04` 互相依赖（依赖环——耦合边界未拆开）
4. `generate_04` 未显式声明推进（generate 必须声明 next 或 parallel+next）
5. `discriminate_01_verdict` 判别式缺 routing（判断值无法路由）

```bash
python scripts/validate.py examples/bad-example   # 应失败并列出全部问题
```

## eco-analysis/ — 研究类任务示例（线性）

五步生态位调研任务：检索×3（generate_01/02/03，串行）→ 生态位机会分析（generate_04）→ 物化报告（generate_05）。演示：
- mod-query 多次装配 + 前置依赖连线（generate_04 依赖 01/02/03）
- 每字段验收标准机械可查

## quant-adaptive/ — 并行组示例

量化因子状态自适应任务，演示**并行组**：`generate_02`/`generate_03` 声明同一 parallel 组（同一行 state 填充，op-table 多条件 AND），组全部完成才推进到 `generate_04`。随后是判别式路由（`discriminate_01_verdict`/`discriminate_02_verdict`）。

## dsh-client/ — 线性 + 判别路由示例

DSH 客户端契约推导任务：`generate_01 → … → generate_05` 串行，随后三个判别式（`discriminate_01/02/03_verdict`）逐步把关——验证、验收、独立审计三层，最后一个判别式走 `mod-audit`（工具审计思维）。
