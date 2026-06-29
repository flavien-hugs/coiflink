---
description: Add or improve end-to-end tests for the repository's cross-component flows
argument-hint: "[spec-file|pr-url-or-number|notes]"
---
Add or improve end-to-end test coverage for this target:

$ARGUMENTS

This command is for heavier end-to-end scenarios, especially behavior that crosses component boundaries (e.g. client ↔ backend ↔ another service, persistence, and external integration points). Prefer `/tests` for unit tests and deterministic non-e2e integration tests.

Workflow:

1. Understand the e2e target
   - If the argument is a spec file path, read it completely and identify the end-to-end behavior that needs coverage.
   - If the argument is a PR URL or number, inspect PR metadata, changed files, commits, checks, and diff via the orchestrator-provided context. Do not run git or gh yourself; the orchestrator owns all git/gh.
   - If the argument is notes/free text, treat it as e2e testing goals for the current working tree.
   - If no argument is provided, inspect the current working tree and ask for clarification only if the target is genuinely unclear.

2. Read repository and test infrastructure context before editing
   - the repository's `README` and any relevant spec under `specs/` for the product requirements and architecture model.
   - the specific GitHub issue under test, if one is named.
   - the existing application source tree, existing tests, and any e2e harness — once they exist. If there is no source tree or e2e harness yet, say so explicitly and base scenarios on the docs and the issue.
   - any ADRs under `docs/adr/` that the e2e harness depends on (for example the stack choice), once they exist.

3. Decide whether e2e coverage is warranted
   - Summarize the behavior under test.
   - Identify what lower-level tests already cover.
   - Add e2e tests only when unit or non-e2e integration tests are insufficient.
   - Prefer a small number of high-value scenarios over broad, slow, flaky coverage.
   - Clearly separate live-backend / multi-process / device-emulator tests from default tests if the project convention requires gating.
   - High-value end-to-end surfaces are the documented user-visible flows that cross component boundaries: primary onboarding/setup paths, the core feature loop end to end, failure/recovery paths (network or process interruption), and any documented security/trust boundary exercised across components.

4. Add or improve e2e tests
   - Use existing project infrastructure and patterns.
   - Drive the real end-to-end flow rather than mocking past the boundary under test.
   - Do not require real production services, real user identities, or live production credentials; use local/test instances and synthetic fixtures.
   - Avoid making the default test gate depend on emulators, external networks, or live services unless that is already the project convention.
   - Prefer gated/tagged tests, or clearly documented external prerequisites, for tests that need a backend instance, a device emulator, or a local object store.
   - Keep tests reproducible, deterministic where possible, and safe to run repeatedly.
   - Avoid arbitrary sleeps; prefer readiness checks, bounded retries, or existing synchronization helpers. For time-dependent behavior (expiry, timeouts), drive a controllable clock rather than wall-clock sleeps.
   - Ensure test logs and fixtures never expose secrets, credentials, or PII.

5. Preserve repository invariants
   - Respect the documented architecture and any security/privacy constraints the repository states; e2e assertions must confirm them, not bypass them.
   - Never log or persist secrets, credentials, or PII — including in test output and fixtures.
   - Where the repository documents trust, access-control, residency, or expiry boundaries, e2e tests must exercise them, not circumvent them.
   - E2E tests must not create trust/access bypasses just to pass.
   - Do not imply unimplemented behavior exists unless it is actually implemented.

6. Document how to run the e2e tests
   - Update nearby docs, test comments, or scripts when needed.
   - Clearly list external requirements such as a local backend instance, a device/web emulator, or a local object store.
   - Include exact commands for setup, execution, and cleanup.

7. Verify before finishing
   - Run the narrowest relevant e2e test first when practical.
   - Run the project's configured test gate (the command surfaced via `MX_AGENT_TEST_CMD`) plus any format, lint, and build checks the project defines.
   - If no test command is configured yet, say so explicitly and recommend the exact commands to run once the stack lands — do not assume a particular language, build tool, or test runner, and do not invent a toolchain.
   - If a check cannot be run, explain why and recommend the exact command.

8. Final report
   - E2E target and scenario covered
   - Test infrastructure used
   - Files changed
   - Tests added or updated
   - Commands run and results
   - External requirements, if any
   - Bugs discovered, if any
   - Remaining gaps, flakes, risks, or follow-up recommendations

Important: focus on end-to-end coverage. Do not broaden product behavior beyond what is necessary to make the e2e scenario testable and safe.
