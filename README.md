# orchestration-skill

Long-task orchestration engine for AI agents: reliability comes from a **module-assembled state machine + mechanical execution + two-layer audit**, not from the model's long-context capability.

The agent condenses intent → an orchestrator subagent assembles a field-driven pipeline (`steps.json` assembly table + `minds.json`) by picking modules from a library like building blocks → a mechanical executor drives the field-semantics state machine (`generate_N` produces and advances / `discriminate_N_xxx` judges and routes) → each field is dispatched via the **T3 protocol** (fill/rules/schema/data/write/forbidden, zero lead-in) → every artifact lands on disk (folder = external memory, resumable) → two-layer audit catches drift.

## Why

Long tasks fail not because the model is weak, but because unreliability compounds across a long chain:

- steps blur together, errors propagate silently
- the orchestrator's prose instructions get re-interpreted ("protocol wrapped in prose")
- state lives only in context and is lost on resume

This skill pushes all of it into **structure**: JSON contracts with JSON-Schema constraints, a field-semantics state machine, module-derived protocols, T3 dispatch, and mechanical gates at every boundary. Never fight drift with more prose — fight it with structure.

## Features

- **Module assembly (building blocks)** — the orchestrator is an assembler, not a protocol designer: pick modules (`mod-generate`/`mod-extract`/`mod-transform`/`mod-query`/`mod-reason`/`mod-fill`/`mod-verify`/`mod-audit`/`mod-classify`/`mod-mind-decider`) from `modules/`, wire `inputs`, set `routing` on discriminators. Modules carry their own protocol (produce/mind/output_schema/forbidden)
- **Two-level module model** — level 1 `produce`: `generate` (artifact lands → advance) vs `discriminate` (judgment value → route branch); level 2 `mind`: cognitive parameter sets (write/extract/transform/query/reason/fill/verify/audit/classify/decider) that determine forbidden. Field names encode state semantics: `generate_01`, `discriminate_01_verdict`
- **Field-semantics state machine** — `scripts/executor.py`: `ready`/`check`/`retry`/`reset`/`status`. Front gate (input dependencies materialized), back gate (generate validates output schema / discriminate validates routing membership), discriminator routing turns the machine from linear into branching (pass→next, revise→rework, reject→stop)
- **Audit-rework mechanism** — discriminator routing supports object form `{to, counter, limit, escalate, mind}`: rework target with counter, escalation (mind switch) after limit, mind override per route. `materialize` expands it into op-table (escalate rule first, exclusive by order + mutually exclusive conditions). Counters live in the main agent's context (`--state`), not state.csv — the plugin version knows round/count naturally; the node version datafies because a program drives it
- **Mind-decider (runtime mind selection)** — for complex rework (cost-cutting, refactoring) don't statically bind `routing.mind`; route the failure to a strategy discriminator (`mod-mind-decider`, outputs `chosen_mind` + machine-recomputable `basis`) which reads the audit evidence (cost structure / fixed-cost share / negotiation space / failure type) and picks the rework mind at runtime. Verified end-to-end: the decider chose `mind-crusher` over `mind-reason` for a fixed-cost wall, and the rework reproduced the same $12,676 as the direct crusher run (gap −72%)
- **T3 protocol dispatch** — `executor.py t3` generates the six-piece dispatch (fill/rules/schema/data/write/forbidden) from module + mind + dependency artifacts; the only allowed subagent prompt is a zero-lead-in file reference — no prose can wrap the protocol. **Orchestration and orchestration-audit are dispatched the same way** (`templates/orchestrator.t3.json`, `templates/audit.t3.json`)
- **Capability slots** — modules declare `skills`/`mcp`; the executor injects them into the T3 dispatch so the executing subagent assembles skills/MCP tools directly instead of discovering them
- **Local capability scan** — `scripts/discover.py` materializes `artifacts/capabilities.json` (MCP servers from the DSH patch layer + skill dirs + runtime supplements); `validate.py` rejects any slot that names a capability absent from this inventory
- **Mind constraints** — `mind-orchestrator` and `mind-orchestration-audit` encode LLM-psychology guards (anchoring / path-locking / sycophancy / confirmation bias) directly into the T3 rules of orchestration and its audit
- **Mind dual-track injection** — minds are `directive` (crusher-style positive paths for research steps) or `constraint` (FORBIDDEN-style negative guards for everyday tasks): the default assumption is the LLM can produce — the job of constraint minds is to seal off the hallucination slide, not to teach method
- **Cognitive-mode ratio** — each step needs a different LLM psychological state: `role` (diagnose/scan/architect/write/audit/review) + `forbidden_density` (zero/precise/dense). Diagnose gets zero FORBIDDEN (broad scan), writers get precise proposition-level FORBIDDEN (universal bans cause negative flow), auditors get dense FORBIDDEN + presumed-guilty framing. Module/mind/field-level `forbidden` arrays bind bans to the concrete proposition
- **Mind materialization (enforce)** — a mind's `enforce` block (fill/schema/forbidden/check) is merged into the T3 dispatch; `executor.py check` mechanically verifies evidence against its source file. A control experiment showed prose mind instructions produce self-referential path "evidence" (`材料/决策/D1`) and drop existing fields — enforce upgrades minds from prose to protocol
- **Two-layer audit** — static (multi-agent independent audit of the assembly) + dynamic (3 same-class failures → `needs_reorchestration`; execution-error vs orchestration-error discrimination)
- **Failure feedback loop** — failure traces flow back into templates; the engine gets better at assembling each task type
- **Materialized artifacts** — every field writes `artifacts/<field>.json`; resume from disk, hand off with zero context loss
- **Zero dependencies** — pure Python standard library; runs anywhere Python 3.7+ exists

## Quick start

```bash
# scan local capabilities (MCP servers from DSH patch layer + skill dirs + runtime)
python scripts/discover.py tasks/demo-task --runtime-skills web-search,lark-doc --runtime-mcp obsidian

# validate an assembly table (mechanical gate: field names, module refs, routing, acyclicity)
python scripts/validate.py examples/demo-task

# inspect the state machine
python scripts/executor.py status examples/demo-task

# list runnable fields (front gate)
python scripts/executor.py ready examples/demo-task

# generate the T3 dispatch for a field (protocol derived from module + mind)
python scripts/executor.py t3 examples/demo-task generate_01
```

## How it works

The skill's meta-state-machine (design convergence) is separated from the task's state machine (execution):

1. **Stage 0 — Init**: create `tasks/<task_id>/{artifacts,feedback,draft}`; run `scripts/discover.py` to materialize `artifacts/capabilities.json` (the local capability inventory); condense the user intent into `data` (schema-constrained).
2. **Stage A — Orchestrate (design convergence, draft state)**: dispatch an orchestrator subagent with `templates/orchestrator.t3.json` (data filled in, modules_ref + capabilities referenced). The orchestrator works under `mind-orchestrator` (anti-anchoring / anti-path-locking) and produces the assembly draft in `draft/`: field sequence (`generate_N` / `discriminate_N_xxx`), module picks, `inputs` wiring, `routing` on discriminators.
3. **Stage B — Audit orchestration (same-context multi-round loop)**: `validate.py draft/` (mechanical: field-name regex, module refs, routing legality, acyclic deps) — on failure `send_message` the orchestrator (same session) to fix; then an independent audit subagent reads `draft/` via `templates/audit.t3.json` under `mind-orchestration-audit` (anti-confirmation-bias / anti-sycophancy); revise opinions flow back to the orchestrator for another round. Loop until validate passes + audit passes. Separate brains: the auditor stays independent each round.
4. **Stage C — Materialize (enter execution state)**: on convergence the main agent mechanically copies `draft/` to the task root (`executor.py materialize`) — the assembly is now frozen; later changes return to Stage A.
5. **Stage 2 — Execute**: `ready` lists runnable fields (front gate) → `t3` generates the T3 dispatch from module + mind + dependency artifacts → the subagent executes with a zero-lead-in prompt → `check` validates (generate: output schema; discriminate: judgment ∈ routing keys) and advances/routes.
6. **Stage 3 — Dynamic audit**: 3 same-class failures → `needs_reorchestration`; discriminate execution errors (retry) from orchestration errors (return to Stage A).
7. **Stage 4 — Wrap**: `compare.py` full verification; archive the assembly to `templates/` or `examples/`.

## Usage as a DeepSeek Harness skill

`SKILL.md` follows the DSH skill format (frontmatter + a schema-driven protocol). Point `dsh-skill-filesystem`'s `customSkillDirs` at this directory, or copy it into your skill root. The executor scripts run via any shell with Python.

## Layout

```
SKILL.md            # the protocol (schema-driven contract shape)
schemas/            # JSON Schemas (steps assembly / modules / minds)
modules/            # the module library (produce + mind + output_schema + forbidden)
scripts/            # discover.py / validate.py / executor.py / compare.py (pure stdlib)
templates/          # assembly templates + orchestrator T3 + audit T3
examples/           # demo-task (happy path), bad-example (negative), eco-analysis (research task)
tasks/              # runtime artifacts (gitignored)
```

## License

MIT
