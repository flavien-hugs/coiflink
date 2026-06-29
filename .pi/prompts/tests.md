---
description: Add or improve focused non-e2e tests for a spec, PR, or working tree
argument-hint: "[spec-file|pr-url-or-number|notes]"
---
Add or improve focused non-e2e test coverage for this target:

$ARGUMENTS

This command is for unit tests, deterministic integration tests that do not require external services, argument/output tests, policy/protocol/schema tests, and negative/security regression tests. Do not add tests that require live infrastructure (real network, a running backend, or device hardware) here; use `/e2e_tests` for those.

Workflow:

1. Understand the testing target
   - If the argument is a spec file path, read it completely and identify the behavior that should be covered by tests.
   - If the argument is a PR URL or number, inspect PR metadata, changed files, commits, checks, and diff using `gh` (or `~/.local/bin/gh` if needed).
   - If the argument is notes/free text, treat it as testing goals for the current working tree.
   - If no argument is provided, inspect the current working tree and ask for clarification only if the target is genuinely unclear.

2. Read repository context before editing
   - the repository's `README` and any relevant spec under `specs/`
   - the specific GitHub issue being worked, if named in the target
   - the existing application source tree and any tests around the target behavior — if the source tree does not exist yet, say so.

3. Identify coverage gaps
   - Summarize the behavior under test.
   - Identify existing tests that already cover it.
   - Identify missing edge cases, negative cases, error handling, security/trust boundaries, access-control checks, schema/protocol compatibility, failure/recovery paths, and regression risks.
   - Prefer the smallest test layer that gives confidence: unit tests before integration tests, integration tests before e2e tests.

4. Add or improve tests
   - Add focused, deterministic tests that cover the gaps.
   - Do not implement new product behavior except minimal testability hooks when absolutely necessary.
   - Do not weaken assertions or delete meaningful coverage to make tests pass.
   - Do not introduce flaky sleeps, timing-sensitive assertions, network dependencies, or external service requirements.
   - Do not use real secrets, credentials, tokens, private keys, or PII in fixtures; use synthetic, clearly-fake values.
   - Match whatever language and test framework the project has adopted; do not introduce a new toolchain.
   - Document public test helpers if they are public APIs; prefer private helpers when possible.

5. Preserve repository invariants
   - Respect the documented architecture and any security/privacy constraints the repository states; tests must assert them, never circumvent them.
   - Never log or persist secrets, credentials, or PII — including in test fixtures, assertions, and snapshots.
   - Where the repository documents trust, access-control, or expiry boundaries, add negative tests that they cannot be bypassed.
   - Do not imply unimplemented behavior exists; only test what is actually implemented.

6. Verify before finishing
   - Run the most relevant test first (the single test or module covering the changed behavior) before the full gate, when practical.
   - Then run the project's configured test gate (the command surfaced via `MX_AGENT_TEST_CMD`) plus any format, lint, and build checks the project defines.
   - If no test command is configured yet, say so explicitly and recommend the exact command to run once the stack lands — do NOT assume a particular language, build tool, or test runner, and do NOT invent a toolchain.
   - If a check fails, fix the issue and rerun the relevant check when practical.
   - If a check cannot be run, explain why and recommend the exact command.

7. Final report
   - Testing target
   - Files changed
   - Tests added or updated
   - Coverage gaps closed
   - Bugs discovered, if any
   - Checks run and results
   - Remaining coverage gaps or follow-up recommendations

Important: focus on tests. Do not broaden the implementation scope or add e2e infrastructure unless explicitly asked.
