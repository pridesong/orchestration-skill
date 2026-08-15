/**
 * orchestration-executor-tools — DSH Host 动态 Cordis 插件
 *
 * 把 orchestration-skill 的机械命令（executor.py / validate.py）包装成模型工具，
 * 使主 agent 通过工具调用驱动长任务，而不是读 SKILL.md 协议 + 手敲 python 命令。
 *
 * 用法（DSH 会话内）：
 *   cordis_define(kind: "new", idPrefix: "orch")
 *     → 返回 pluginId / packageId
 *   cordis_run(pluginId, packageId, mode: "run")
 *     → 激活后 6 个工具对模型可见：orch_status / orch_ready / orch_t3 /
 *       orch_check / orch_validate / orch_materialize
 *
 * 注意：SKILL_ROOT 是开发机路径，部署到其他机器需改为实际 skill 安装路径。
 */
return {
  name: 'orchestration-executor-tools',
  inject: ['tools'],
  apply(ctx) {
    const SKILL_ROOT = 'D:/MyProject/orchestration-skill'
    const PYTHON = 'python'

    // 跑 executor.py / validate.py 子命令，返回结构化 JSON 结果
    async function runScript(script, args, exec) {
      const shell = ctx.get('shell')
      if (shell === undefined) throw new Error('shell service unavailable')
      const argv = [PYTHON, SKILL_ROOT + '/scripts/' + script].concat(args)
      const command = argv.map(q).join(' ')
      const request = { command: command, workdir: SKILL_ROOT, timeoutMs: 60000, signal: exec.signal }
      const spec = shell.resolve(request)
      const result = await shell.run(spec)
      const stdout = typeof result.stdout === 'string' ? result.stdout : (result.stdout && result.stdout.text) || ''
      const stderr = typeof result.stderr === 'string' ? result.stderr : (result.stderr && result.stderr.text) || ''
      return { ok: result.exitCode === 0, exitCode: result.exitCode, stdout: stdout, stderr: stderr }
    }
    // 简单 shell 引号（Windows 路径无空格时可直传）
    function q(s) {
      return String(s).replace(/[\\"]/g, '\\$&').replace(/^|$/g, '"')
    }

    const tools = [
      {
        name: 'orch_status',
        description: '显示编排任务状态机全景：每个字段的完成状态、当前下一步、指定 mind。适合任务开始/续跑/结束时查看。',
        parameters: {
          task_dir: { type: 'string', required: true, description: '任务目录绝对路径' },
          state: { type: 'string', description: '可选：外部计数状态 JSON' },
        },
        output: {
          schema: { type: 'json' },
          render(_a, v) { return [{ type: 'text', text: JSON.stringify(v, null, 2) }] },
        },
        async execute(args, exec) {
          const a = ['status', args.task_dir]
          if (args.state) a.push('--state', args.state)
          return runScript('executor.py', a, exec)
        },
      },
      {
        name: 'orch_ready',
        description: '列出编排任务当前可执行的下一步（op-table 驱动）。返回下一步字段名、类型（generate/discriminate）、模块、并行组（若有）、指定 mind（若有）以及 T3 派发所需的字段信息。调用后应用 orch_t3 生成派发。',
        parameters: {
          task_dir: { type: 'string', required: true, description: '任务目录绝对路径' },
          state: { type: 'string', description: '可选：外部计数状态 JSON，如 {"revise_count": 2}' },
        },
        output: {
          schema: { type: 'json' },
          render(_a, v) { return [{ type: 'text', text: JSON.stringify(v, null, 2) }] },
        },
        async execute(args, exec) {
          const a = ['ready', args.task_dir]
          if (args.state) a.push('--state', args.state)
          return runScript('executor.py', a, exec)
        },
      },
      {
        name: 'orch_t3',
        description: '为指定字段生成 T3 六件套派发文件（dispatch/<field>.t3.json），返回派发 prompt（T3FILE:v1 零引导语）。该 prompt 是派发给执行 subagent 的唯一合法文本，禁止添加任何散文。',
        parameters: {
          task_dir: { type: 'string', required: true, description: '任务目录绝对路径' },
          field: { type: 'string', required: true, description: '字段名，如 generate_01 / discriminate_02_mind' },
          mind: { type: 'string', description: '可选：思维覆盖（如 mind-crusher），op-table 指定换脑时使用' },
        },
        output: {
          schema: { type: 'json' },
          render(_a, v) { return [{ type: 'text', text: JSON.stringify(v, null, 2) }] },
        },
        async execute(args, exec) {
          const a = ['t3', args.task_dir, args.field]
          if (args.mind) a.push('--mind', args.mind)
          const r = await runScript('executor.py', a, exec)
          const m = /派发 prompt: (T3FILE:v1 .+)/.exec(r.stdout)
          return Object.assign(r, { dispatch_prompt: m ? m[1] : null })
        },
      },
      {
        name: 'orch_check',
        description: '后置门禁：验证字段产物并推进/路由（判别式判断值生效）。返回 ok/问题列表/路由目标。调用后应用 orch_ready 看下一步。',
        parameters: {
          task_dir: { type: 'string', required: true, description: '任务目录绝对路径' },
          field: { type: 'string', required: true, description: '字段名' },
        },
        output: {
          schema: { type: 'json' },
          render(_a, v) { return [{ type: 'text', text: JSON.stringify(v, null, 2) }] },
        },
        async execute(args, exec) {
          return runScript('executor.py', ['check', args.task_dir, args.field], exec)
        },
      },
      {
        name: 'orch_validate',
        description: '机械校验装配表（字段命名/模块引用/routing 合法性/依赖无环/并行组一致性/mind 引用）。草稿态与定稿态都可用。返回校验错误列表（空=通过）。',
        parameters: {
          task_dir: { type: 'string', required: true, description: '任务目录绝对路径（含 steps.json 与 minds.json）' },
        },
        output: {
          schema: { type: 'json' },
          render(_a, v) { return [{ type: 'text', text: JSON.stringify(v, null, 2) }] },
        },
        async execute(args, exec) {
          return runScript('validate.py', [args.task_dir], exec)
        },
      },
      {
        name: 'orch_materialize',
        description: '设计收敛 → 执行态：把 draft/steps.json + draft/minds.json 复制到任务根并生成 op-table.json（条件路由表）。物化后装配表定稿，改动需回设计收敛。返回生成结果。',
        parameters: {
          task_dir: { type: 'string', required: true, description: '任务目录绝对路径（需有 draft/steps.json 与 draft/minds.json）' },
        },
        output: {
          schema: { type: 'json' },
          render(_a, v) { return [{ type: 'text', text: JSON.stringify(v, null, 2) }] },
        },
        async execute(args, exec) {
          return runScript('executor.py', ['materialize', args.task_dir], exec)
        },
      },
    ]

    const disposers = tools.map(t => ctx.tools.register(harness.defineTool(t)))
    return () => { disposers.forEach(d => d()) }
  },
}
