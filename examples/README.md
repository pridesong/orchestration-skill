# 示例

## demo-task/ — 完整好示例

一个三步骤演示任务：收集资料 → 分析 → 生成报告。用于演示 validate.py 通过路径。

## bad-example/ — 故意损坏示例

包含三类编排性错误，用于演示 validate.py 的拦截：
1. `s001.op_ref` 引用不存在的操作（引用完整性）
2. `s002` 依赖不存在的步骤 `s999`（依赖引用）
3. `s002` 与 `s003` 互相依赖（依赖环——耦合边界未拆开）

## eco-analysis/ — 研究类任务示例

一个五步生态位调研任务（检索×3 并行 → 交叉分析 → 物化报告），演示：
- 可并行的独立步骤（s001/s002/s003 无依赖）
- mind-audit 模式（交叉审计步，只可用可验证事实、每条结论附证据引用）
- T3 派发：`python scripts/executor.py t3 examples/eco-analysis s005`

运行方式：

```bash
python scripts/validate.py examples/demo-task     # 应通过
python scripts/validate.py examples/bad-example   # 应失败并列出全部问题
python scripts/compare.py examples/demo-task      # 应报产物缺失（未执行）
```
