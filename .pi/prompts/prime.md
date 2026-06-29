---
description: Prime the agent with the repository architecture and contribution rules
argument-hint: "[task/context]"
---
Prime yourself for working on this repository before taking action.

Optional task/context from me: $ARGUMENTS

First, read and internalize the repository context:
- the repository's `README` and any top-level docs that describe the product, goals, and constraints
- any relevant spec under `specs/` and any Architecture Decision Records under `docs/adr/`
- the specific GitHub issue being worked and its acceptance criteria
- the existing application source tree for the requested task. If no source exists yet for this area (a greenfield or early-stage repo), say so explicitly and work from the docs, the issue, and any committed ADRs.

Project summary:
Summarize, in a few bullets, what this repository is and what it does, based on the docs you just read. Do not invent a domain, stack, or feature set — describe only what the README/specs/ADRs and source tree actually establish.

Architecture and constraints:
- Identify the documented architecture, the main components/packages, and the boundaries between them.
- Identify any security, privacy, performance, or compliance constraints the docs state (for example: data handling/redaction rules, residency or hosting requirements, latency/size budgets, threat-model assumptions) and treat them as invariants — never weaken them in a change.
- If the docs are silent on a constraint, do not assume one; flag the gap instead of inventing a rule.

Current status to preserve:
- Note whether the stack and tooling are settled or still open. If the build tool, language, or test command have NOT been chosen yet, do not assume a particular toolchain and do not imply that a feature or component exists when it has not been implemented.

Working rules:
- Identify the owning component and any existing patterns before editing.
- Keep changes focused, idiomatic, and testable.
- Respect any documented dependency/milestone order before starting downstream work.
- Preserve the documented architecture and security/privacy invariants in every change.
- Avoid broad rewrites unless explicitly requested.
- Update the relevant docs (README, ADRs, schemas) when behavior changes.
- The orchestrator owns ALL git/gh operations; do not run git or gh yourself.

Before finalizing code changes, run or clearly recommend:
- The project's configured test gate (the command surfaced via `MX_AGENT_TEST_CMD`) plus any format/lint/build checks the project defines.
- If no test command is configured yet, say so explicitly and recommend the exact command(s) to run once the stack lands — do NOT assume a particular toolchain or invent one.

After reading the relevant files, summarize the repository context in a few bullets, identify the likely component(s) involved in the task/context above, and propose a short plan before making code changes.
