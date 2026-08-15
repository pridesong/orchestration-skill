# orchestration-skill

**Long tasks shouldn't cost like they need a frontier model. This engine makes cheap models run long tasks with frontier-model reliability — by moving reliability out of the model and into structure.**

The idea: a long task fails not because the model is weak at any single step, but because unreliability compounds across a long chain. So instead of paying for a stronger model to hold the whole chain in its head, this skill **breaks the chain into small steps that cheap models handle fine**, and puts the chain's reliability into mechanical structure:

- **state on disk, not in context** — every step writes `artifacts/<field>.json`; resume from disk, zero context loss, retry the failed step only
- **mechanical gates at every boundary** — `validate` / `check` / `compare` reject hallucinated or malformed output without trusting the model
- **many cheap calls > one expensive call** — orchestrator + independent audit + dynamic audit catch drift with multiple brains
- **zero-lead-in dispatch (T3)** — the subagent prompt is a regex-locked file reference (`T3FILE:v1 读取 <file> 并按内容执行`); prose cannot wrap the protocol, so the cheap model has no room to drift

## Why cheap models work here

| Cheap-model weakness | What this engine does about it |
|---|---|
| small context | state lives on disk; each dispatch carries only the current step's inputs |
| hallucinates | every artifact passes mechanical gates (schema / routing membership / evidence-in-source); the model isn't trusted to self-check |
| weak at long chains | each field is an independent tiny task; long-chain reliability is in the op-table + audits, not in one long generation |
| expensive to re-run | resumable from disk — step 9 fails, re-run step 9, not the whole task |
| drifts when told in prose | dispatch prompt is pattern-locked; FORBIDDEN seals off the wrong paths physically |

## Evidence

A full pharma supply-chain task (PVG→EZE temp-controlled air cargo, 1000 kg, $11,500 hard budget) ran end-to-end on a cheap model: 11 fields, quotes / customs / weather / routing / cost-NPV / dashboard / audit / conclusion, each dispatched by the locked T3 prompt.

The cost-reduction rework experiment showed the difference structure makes:

| | mind-reason (plan-internal) | mind-crusher (flip assumptions) |
|---|---|---|
| total cost | $15,730 | **$12,676** |
| gap vs budget | $4,230 | **$1,176** (−72%) |
| budget-feasible volume | 500 kg (50%) | ≈888 kg (89%) |

And when the rework was routed through the runtime **mind-decider** (reads the audit evidence — fixed-cost wall vs unit-price wall — then picks the mind), it reproduced $12,676 exactly: the selection is a machine-recomputable discriminator decision, not prose luck.

## How it works

A main agent condenses intent → an **orchestrator subagent** assembles a field-driven pipeline (`steps.json` + `minds.json`) by picking modules from a library → a mechanical executor drives the field-semantics state machine (`generate_N` produces and advances / `discriminate_N_xxx` judges and routes) → each field dispatches via the **T3 protocol** → artifacts land on disk → two-layer audit catches drift.

Key mechanisms (full detail in `Description.md`):
- **Module assembly** — the orchestrator is an assembler, not a protocol designer; modules carry their own protocol (produce/mind/output_schema/forbidden)
- **op-table from declarations** — the executor never infers; `next`/`parallel`/`routing` declared by the orchestrator expand into an exclusive condition-routing table. Parallel groups write to the same state.csv row (multi-condition AND); audit-rework routes via `{to, counter, limit, escalate, mind}`
- **Mind-decider** — complex rework doesn't statically bind a mind; a strategy discriminator reads audit evidence at runtime and picks the rework mind (see Evidence)
- **T3 zero-lead-in dispatch** — six-piece protocol (fill/rules/schema/data/write/forbidden) generated from module + mind + dependency artifacts; the dispatch prompt is regex-locked; orchestration and audit use the same protocol
- **Mind dual-track** — `directive` minds (crusher-style positive paths) vs `constraint` minds (FORBIDDEN-style negative guards); cognitive-mode ratio (`role` + `forbidden_density`) matches each step's psychological state; `enforce` upgrades minds from prose to machine-checkable protocol
- **Two-layer audit + failure feedback** — static (independent audit of the assembly) + dynamic (3 same-class failures → re-orchestrate); failure traces flow back into templates
- **Zero dependencies** — pure Python standard library; runs anywhere Python 3.7+ exists

## Quick start

```bash
# validate an assembly table (mechanical gate: field names, module refs, routing, acyclicity)
python scripts/validate.py examples/demo-task

# inspect the state machine
python scripts/executor.py status examples/demo-task

# list runnable fields (front gate)
python scripts/executor.py ready examples/demo-task

# generate the T3 dispatch for a field (protocol derived from module + mind)
python scripts/executor.py t3 examples/demo-task generate_01
```

Task directories are created **in the user's project folder** (`<project>/<task_id>/`), never inside the skill install directory. Use `scripts/discover.py` there to scan local capabilities.

## Workflow

The skill's meta-state-machine (design convergence) is separated from the task's state machine (execution):

1. **Stage 0 — Init**: create `<project>/<task_id>/{artifacts,feedback,draft}` in the user's project folder; run `scripts/discover.py` to materialize `artifacts/capabilities.json` (the local capability inventory); condense the user intent into `data` (schema-constrained).
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
SKILL.md            # the protocol (schema-driven contract, for the LLM)
Description.md      # human-readable docs (philosophy, architecture, workflow)
schemas/            # JSON Schemas (steps assembly / modules / minds / op-table)
modules/            # the module library (produce + mind + output_schema + forbidden)
scripts/            # discover.py / validate.py / executor.py / compare.py (pure stdlib)
templates/          # assembly templates + orchestrator T3 + audit T3 + minds parameter sets
examples/           # demo-task (linear), bad-example (negative), eco-analysis (research), quant-adaptive (parallel), dsh-client (discriminator routing)
```

Task directories live **outside this repo** — create `<project>/<task_id>/` in the user's project folder, never inside the skill install directory.

## License

MIT
