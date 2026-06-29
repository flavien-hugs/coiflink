---
description: Resolve failing repository checks reported by the phased ADW test gate
argument-hint: "<failing-output-and-context>"
---
The repository's test/verification gate is failing. Fix the failures.

Failing output and context (truncated):

$ARGUMENTS

## Instructions

- Investigate the failures above and make the smallest correct change that fixes them.
- Fix the root cause in the code or the tests as appropriate. Do NOT weaken or delete
  meaningful assertions, skip tests, or mask failures to make the gate pass.
- Stay within the scope of the current change; do not start unrelated work.
- Preserve the repository's documented invariants: respect the documented architecture and any
  security/privacy constraints the repository states; never weaken them. Never log or persist
  secrets, credentials, or PII, and keep documented trust, access-control, residency, and
  data-handling boundaries intact.
- The orchestrator re-runs the gate after you finish. Report how many failing checks you
  fixed (`resolved`) and how many remain (`remaining`); if you could fix nothing, say so via
  the counts so the loop can stop.

## Verify before finishing

Before you report, re-run the failing check and the project's configured verification gate
(the command surfaced via `MX_AGENT_TEST_CMD`) plus any format/lint/build checks the project
defines, and confirm they pass.

- If a test/lint/format/build command IS configured, run it, fix anything it surfaces, and rerun
  the relevant check until it passes.
- If NO test command is configured yet, say so explicitly. Do NOT assume a particular language, build
  tool, or test command, and do NOT invent a toolchain. Recommend the exact command that should be
  run once the stack lands so the gate can be re-run.

If a check cannot be run, say why and give the exact command.
