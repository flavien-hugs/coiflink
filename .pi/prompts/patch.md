---
description: Resolve blocking review findings in the phased ADW pipeline
argument-hint: "<blocker-findings-and-context>"
---
A self-review found blocking issues in the current implementation. Resolve them.

Blocking findings and context:

$ARGUMENTS

## Instructions

- Address every blocking finding above with the smallest correct change.
- Only fix the listed blockers; do not act on tech-debt or skippable items, and do not start
  unrelated work or broad rewrites.
- Keep tests meaningful — fix the cause, do not weaken assertions.
- Preserve the repository's documented invariants: respect the documented architecture and any
  security/privacy constraints the repository states; never weaken them. Never log or persist
  secrets, credentials, or PII, and keep documented trust, access-control, residency, and
  data-handling boundaries intact.
- Report how many blocking findings you fixed (`resolved`) and how many remain (`remaining`).

## Verify before finishing

If you changed code, before you report run the project's configured test gate (the command surfaced via
`MX_AGENT_TEST_CMD`) plus any format, lint, and build checks the project defines.

If no test command is configured yet, say so explicitly and recommend the exact command to run once the
stack lands — do not assume a particular language, build tool, or test runner, and do not invent a
toolchain.

Fix anything these surface and rerun the relevant check. If a check cannot be run, say why and
give the exact command.
