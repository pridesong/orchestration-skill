# orchestration-skill

Long-task orchestration engine for AI agents: reliability comes from a **materialized state machine + mechanical execution + two-layer audit**, not from the model's long-context capability.

The agent condenses intent → an orchestrator subagent materializes a three-file contract (`steps`/`op-table`/`minds`) → a mechanical executor enforces the state machine → each step is dispatched via the **T3 protocol** (fill/rules/schema/data/write/forbidden, zero lead-in) → every artifact lands on disk (folder = external memory, resumable) → two-layer audit catches drift.

## Why

Long tasks fail not because the model is weak, but because unreliability compounds across a long chain:

- steps blur together, errors propagate silently
- the orchestrator's prose instructions get re-interpreted ("protocol wrapped in prose")
- state lives only in context and is lost on resume

This skill pushes all of it into **structure**: JSON contracts with JSON-Schema constraints, a state machine with hard transition tables, T3 protocol dispatch, and mechanical gates at every boundary. Never fight drift with more prose — fight it with structure.

## Features

- **Three-file contract** — `steps.json` (state layer: what to do), `op-table.json` (primitive layer: how to do it), `minds.json` (cognition layer: which mindset), all schema-constrained under `schemas/`
- **Mechanical state machine** — `scripts/executor.py`: `ready`/`check`/`retry`/`reset`/`status`. Front gate (dependencies must be passed), back gate (artifacts validated against `output.schema`), illegal transitions rejected by a hard transition table
- **T3 protocol dispatch** — `executor.py t3` generates the six-piece dispatch (fill/rules/schema/data/write/forbidden) from the contract + dependency artifacts; the only allowed subagent prompt is a zero-lead-in file reference — no prose can wrap the protocol
- **Two-layer audit** — static (multi-agent independent audit of the orchestration) + dynamic (3 same-class failures → `needs_reorchestration`; execution-error vs orchestration-error discrimination)
- **Failure feedback loop** — failure traces flow back into templates; the engine gets better at orchestrating each task type
- **Materialized artifacts** — every step writes to the task folder; resume from disk, hand off with zero context loss
- **Zero dependencies** — pure Python standard library (`json`/`os`/`sys`/`tempfile`/`collections`); runs anywhere Python 3.7+ exists

## Quick start

```bash
# validate a contract (mechanical gate)
python scripts/validate.py examples/demo-task

# inspect the state machine
python scripts/executor.py status examples/demo-task

# list runnable steps (front gate)
python scripts/executor.py ready examples/demo-task

# generate the T3 dispatch for a step
python scripts/executor.py t3 examples/demo-task s003
```

## How it works

1. **Stage 0 — Init**: create `tasks/<task_id>/{artifacts,feedback}`; condense the user intent into `data` (schema-constrained).
2. **Stage 0.5 — Orchestrate**: dispatch an orchestrator subagent with `templates/orchestrator.t3.json` (data filled in). It writes the three-file contract.
3. **Stage 1 — Static audit**: `validate.py` (mechanical) + independent multi-agent audit (coverage / granularity / executability / coupling boundaries). Fail → regenerate.
4. **Stage 2 — Execute**: `ready` lists runnable steps (front gate) → `t3` generates the T3 dispatch → the subagent executes with a zero-lead-in prompt → `check` validates the artifact (back gate).
5. **Stage 3 — Dynamic audit**: 3 same-class failures → `needs_reorchestration`; discriminate execution errors (retry) from orchestration errors (re-orchestrate).
6. **Stage 4 — Wrap**: `compare.py` full verification; archive the contract to `templates/` or `examples/`.

## Usage as a DeepSeek Harness skill

`SKILL.md` follows the DSH skill format (frontmatter + a schema-driven protocol). Point `dsh-skill-filesystem`'s `customSkillDirs` at this directory, or copy it into your skill root. The executor scripts run via any shell with Python.

## Layout

```
SKILL.md            # the protocol (schema-driven contract shape)
schemas/            # JSON Schemas for the three-file contract
scripts/            # validate.py / executor.py / compare.py (pure stdlib)
templates/          # contract templates + the orchestrator T3
examples/           # demo-task (happy path), bad-example (negative), eco-analysis (research task)
tasks/              # runtime artifacts (gitignored)
```

## License

MIT
