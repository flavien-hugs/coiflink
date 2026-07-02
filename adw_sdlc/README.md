# adw_sdlc

A standalone, TypeScript-only control plane for the **ADW (Agentic Developer Workflow) SDLC**
pipeline. It drives a single GitHub issue through a phased, multi-agent software-delivery flow:

```
setup → classify → plan → implement → tests → resolve(loop) → e2e(gated)
      → review → patch(loop) → document(gated) → finalize → ci-fix(loop) → merge → report
```

The **orchestrator owns all git/gh** and withholds secrets from the agent (deny-by-default env
allowlist — the agent never sees `GH_TOKEN`). Each phase runs on one of four interchangeable
runner backends — `claude` | `codex` | `opencode` | `pi` — behind a single `AgentRunner.runPhase()`
seam. The phase prompts are domain-agnostic: they read the repository's `README`, any spec under
`specs/`, and ADRs under `docs/adr/`, and respect whatever architecture and security/privacy
invariants the repository documents.

See [`PLAN.md`](./PLAN.md) for the architecture, [`PORT.md`](./PORT.md) for what changed vs the
upstream `mx-agent` monorepo, and [`PARITY.md`](./PARITY.md) for the parity checklist.

## Layout requirement

The CLI resolves the repo root as the directory **two levels above** `adw_sdlc/src/`. That
directory must hold the package plus the prompt templates and state contract:

```
<repo>/
├── adw_sdlc/                      # this package
├── .claude/commands/<phase>.md    # phase prompts (claude runner)
├── .pi/prompts/<phase>.md         # phase prompts (pi / codex / opencode runners)
├── adw/state.schema.json          # cross-language state contract (+ adw/fixtures/)
└── scripts/check-adw-sdlc-env.sh  # secret-withholding lint gate (npm run lint:env)
```

To apply adw_sdlc to another project, copy those paths into the target repo.

## Prerequisites

- Node ≥ 20.19 and npm
- `gh` (GitHub CLI) authenticated for the target repository
- A git repository with a base branch (`main` by default)
- A runner credential for the selected runner (e.g. `ANTHROPIC_API_KEY` for `claude`)

## Install

```bash
cd adw_sdlc
npm install
npm run typecheck && npm test && npm run lint:env   # sanity check
```

Runner SDKs are `optionalDependencies` loaded via dynamic `import()`, so only the runner you
select needs to be installed; a missing SDK fails with a clear `RunnerNotInstalledError`.

## Configuration (environment)

| Variable | Purpose | Default |
| --- | --- | --- |
| `MX_AGENT_TEST_CMD` | The project's test gate (CoifLink: `bash ../scripts/test-gate.sh` — see [docs/strategie-de-tests.md](../docs/strategie-de-tests.md)) | empty → gate skipped (treated green) |
| `MX_AGENT_FINALIZE_GATES` | Extra pre-merge gates, **one per line** (lint, format, build, scans) | empty |
| `REPO` | `owner/repo` for issue lookups | current repo |
| `MX_AGENT_RUNNER` | `claude` \| `codex` \| `opencode` \| `pi` (same as `--runner`) | `claude` |
| `MX_AGENT_ENGINE` | `ts` \| `py` (the `py` sibling is not bundled here) | `ts` |
| `PROJECT_NUMBER` | Move the issue's card on the GitHub Project board | `1` |
| runner credential | e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`/`CODEX_API_KEY` | — |

> Variables prefixed `MX_AGENT_` / `MATRIX_` are **never** forwarded to the agent child
> (`src/env.ts`). This is the load-bearing secret boundary.

## Usage

```bash
cd adw_sdlc

# Preview the plan for issue #N (no runner SDK required):
npx tsx src/cli.ts <N> --dry-run

# Run the full pipeline on issue #N:
MX_AGENT_TEST_CMD="npm test" \
ANTHROPIC_API_KEY=… \
  npx tsx src/cli.ts <N> --runner claude --yes
```

The repository's [`scripts/run-issue.sh`](../scripts/run-issue.sh) wraps this: it sources local
config from `scripts/adw.env` (gitignored — see `scripts/adw.env.example`) and forwards all
arguments to the CLI.

### Common flags

```
--runner <id>          claude (default) | codex | opencode | pi   (env MX_AGENT_RUNNER)
--phases <list>        comma-separated phase subset/order
--adw-id <id> --resume resume an interrupted run by its 8-char id
--test-cmd <cmd>       test gate (env MX_AGENT_TEST_CMD)
--model <id>           model override (otherwise per-phase routing)
--base <branch>        base branch to fork from / merge into (default: main)
--max-resolve <n>      max self-heal test attempts (default 3)
--max-patch <n>        max review-blocker patch attempts (default 2)
--max-ci-fix <n>       max CI-fix attempts (default 3)
--timeout <s>          abort a runner call after N seconds (0 = none)
--max-budget-usd <usd> native budget cap (runners that support it)
--allow-dirty          skip the clean-working-tree precondition
--force                run even if the issue is already CLOSED
--dry-run              preview the plan; do not run
-y, --yes              do not prompt for confirmation
-h, --help             full flag list
```

Run state is persisted per run under `agents/{adw_id}/` (gitignored).

## CI

[`.github/workflows/adw-sdlc.yml`](../.github/workflows/adw-sdlc.yml) typechecks, tests, and runs
the secret-withholding lint gate against this package on Node 20/22. That is the pipeline's own CI,
separate from the project test gate (`MX_AGENT_TEST_CMD`) that the orchestrator runs during a job.
