---
description: Implement a spec file end-to-end
argument-hint: "<spec-file>"
---
Implement the specification in this file end-to-end:

$1

Extra context/notes from me (everything after the spec path; may be empty). Full invocation for reference: $ARGUMENTS

Do not stop after planning unless the spec is genuinely ambiguous, unsafe, impossible, or blocked by missing information. Read the spec, implement it, test it, and report the result.

Workflow:

1. Read and understand the spec
   - Read the spec file at `$1` completely.
   - Treat the spec as the source of truth for scope and acceptance criteria.
   - If the file does not exist, stop and report the missing path.
   - If the spec is ambiguous, state the ambiguity, make a reasonable assumption when safe, and proceed. Stop only for real blockers.

2. Read repository context before editing
   - the repository's `README` and any relevant spec under `specs/`
   - the specific GitHub issue the spec implements, if one is referenced
   - the existing application source tree and tests for the affected behavior — if no source tree exists yet, say so and work from the docs and the spec
   - existing docs (including any ADRs under `docs/adr/`) around the affected behavior

3. Summarize and plan briefly
   - Summarize the requested implementation in a few bullets.
   - Identify the owning component(s), modules, and existing patterns.
   - List the concrete implementation steps.
   - Then proceed with implementation.

4. Implement the spec completely
   - Make the smallest correct change that satisfies the spec.
   - Keep changes focused, idiomatic, and testable.
   - Preserve existing repository conventions and component boundaries.
   - Do not introduce broad rewrites unless the spec explicitly requires them.
   - Update docs when behavior changes.
   - Add or update tests that cover the new behavior.

5. Preserve repository invariants
   - Respect the documented architecture and any security/privacy constraints the repository states; never weaken them.
   - Never log or persist secrets, credentials, or PII.
   - Preserve documented authentication/authorization, data-handling, and residency/hosting boundaries the change touches.
   - Do not imply unimplemented behavior exists unless this implementation actually adds it.

6. Verify before finishing
   - Run the project's configured test gate (the command surfaced via the `MX_AGENT_TEST_CMD` environment variable) plus any format, lint, and build checks the project defines.
   - If no test command is configured yet, say so explicitly and recommend the exact command to run once the stack lands — do not assume a particular language, build tool, or test runner, and do not invent a toolchain.
   - Run any additional checks named in the spec.
   - If a check fails, fix the issue and rerun the relevant check when practical.
   - If a check cannot be run, explain why and recommend the exact command.

7. Final report
   - Spec implemented: `$1`
   - Files changed
   - Behavior implemented
   - Tests/checks run and results
   - Any assumptions made
   - Any remaining risks, limitations, or follow-up work

Important: do not merely create another plan. Implement the provided spec end-to-end.
