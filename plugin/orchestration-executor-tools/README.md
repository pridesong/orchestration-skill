# orchestration-executor-tools (DSH 集成插件)

把 orchestration-skill 的机械命令包装成 **6 个模型工具**，使主 agent 通过工具调用驱动长任务，而不是读 SKILL.md 协议 + 手敲 python 命令。

## 定位

这是 **skill 的可选 DSH 集成层**，不替代 skill 本身：
- **skill 形态**（`SKILL.md` + `scripts/`）：主 agent 读协议 → 手敲命令。可靠但主 agent 层有散文滑行空间。
- **plugin 形态**（本插件）：机械命令 → 模型工具。参数被 schema 约束（required/additionalProperties:false），主 agent 从"协议执行者"降级为"工具调用者"，零散文滑行面。

实测：pharma-scm-001（7 轮）与 hvac-chicago-001（11 步）18 步零失败零重试，全链路由 orch_* 工具驱动。

## 工具

| 工具 | 包装命令 | 主 agent 视角 |
|---|---|---|
| `orch_status` | `executor.py status` | 状态机全景 |
| `orch_ready` | `executor.py ready [--state]` | 列下一步（op-table 驱动） |
| `orch_t3` | `executor.py t3 [--mind]` | 生成 T3 六件套 + dispatch_prompt（零引导语） |
| `orch_check` | `executor.py check` | 后置门禁：验证推进/路由 |
| `orch_validate` | `validate.py` | 装配表机械校验 |
| `orch_materialize` | `executor.py materialize` | 设计收敛 → 执行态 |

## 安装（DSH 会话内）

```js
// 1. 定义（host.js 内容作为 code.host，idPrefix 3-6 小写字母）
cordis_define({
  plugin: { kind: "new", idPrefix: "orch" },
  name: "orchestration-executor-tools",
  purpose: "把 orchestration-skill 的机械命令包装成模型工具",
  code: { host: "<host.js 内容>" },
})
// → 返回 pluginId / packageId

// 2. 激活
cordis_run(pluginId, packageId, mode: "run")
// → 6 个工具对模型可见
```

## 配置

`host.js` 顶部两个常量需按部署环境调整：

| 常量 | 说明 |
|---|---|
| `SKILL_ROOT` | orchestration-skill 安装路径（当前 `D:/MyProject/orchestration-skill`） |
| `PYTHON` | python 可执行名（默认 `python`） |

## 限制

- 动态 Cordis 插件是进程内的，**进程重启即失**——需要时重新 cordis_define + cordis_run
- 工具底层仍调用 executor.py（Python 脚本），不是原生 JS 状态机
- 适用于 DSH 会话（有 `harness`/`shell` service 的环境）
