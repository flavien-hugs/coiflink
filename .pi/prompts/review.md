---
description: Review a PR produced by /implement and comment when useful
argument-hint: "<pr-url-or-number> [spec-file]"
---
Review this pull request, which may have been produced by `/implement`:

PR: $1
Spec file, if provided: $2
Extra context/notes from me (everything after the PR and optional spec file; may be empty). Full invocation for reference: $ARGUMENTS

Do not modify code unless explicitly asked. Focus on review quality, correctness, security, scope control, and actionable feedback. If the PR has actionable issues, comment on the PR when useful.

Workflow:

1. Validate inputs
   - If `$1` is missing, stop and ask for a PR URL or number.
   - If `$2` is provided, read the spec file completely and review the PR against it.
   - If `$2` is provided but missing, report that clearly and continue reviewing against repository context if possible.

2. Read repository context before reviewing
   - the repository's `README` and any relevant spec under `specs/`
   - the specific GitHub issue the PR addresses, if referenced
   - the application source tree once it exists (if no app code exists yet, say so and review against the docs and any committed ADRs under `docs/adr/`)
   - changed source files, tests, and docs from the PR

3. Inspect the PR
   - Use `gh` (or `~/.local/bin/gh` if needed) to inspect PR metadata, commits, changed files, checks, and diff.
   - Determine the base branch and compare the PR against the correct base.
   - Read enough of the changed files in context to understand the implementation, not just the diff.

4. Review against the spec and repository constraints
   - Verify whether the PR satisfies the provided spec and acceptance criteria.
   - Check that the implementation does not exceed the requested scope.
   - Confirm docs are updated when behavior changes.
   - Confirm tests cover the new behavior and important edge cases.

5. Check the repository's documented invariants
   - Preserve the documented architecture and any security/privacy constraints the repository states; the change must not weaken them.
   - Ensure secrets, credentials, and PII are never logged, persisted, or posted; use existing redaction patterns.
   - Where the repository documents trust, access-control, residency, or data-handling boundaries, verify the change respects them.
   - Do not accept misleading status claims or docs implying unimplemented behavior exists.

6. Look for general review issues
   - Correctness bugs or incomplete behavior
   - Missing error handling or poor error messages
   - Race conditions, restart/retry issues, or persistence gaps
   - Security regressions or trust/policy bypasses
   - Protocol/schema compatibility issues
   - Weak tests or missing negative tests
   - Overly broad rewrites or unrelated changes
   - Formatting, lint, or docs-warning risks

7. Verify checks when practical
   - Inspect existing PR/CI check status with `gh`.
   - When practical and appropriate locally, run the project's configured test gate (the command surfaced via `MX_AGENT_TEST_CMD`) plus any format/lint/build checks the project defines.
   - If no test command is configured yet, say so explicitly and recommend the exact command to run once the stack lands — do not assume a particular language, build tool, or test runner.
   - If checks cannot be run, explain why and recommend exact commands.

8. Comment on the PR when needed
   - If the PR has actionable issues, post a clear PR review comment or review summary using `gh`.
   - Prefer one consolidated review comment over many noisy comments unless line-specific feedback is important.
   - Comment only when feedback is useful, actionable, and relevant to the PR.
   - Do not post a PR comment for purely local observations unless they affect the PR.
   - If the PR looks good, either approve if appropriate or leave a concise positive summary, depending on available permissions.
   - Never post secrets, tokens, credentials, PII, private paths that matter, or sensitive data in PR comments.
   - In the local final report, state exactly what PR comments or reviews were posted, if any.

9. Produce a structured local review report
   - Summary
   - Spec compliance assessment
   - Security assessment
   - Correctness issues
   - Testing/docs gaps
   - Required fixes
   - Optional improvements
   - Checks reviewed or run, with results
   - PR comments posted, if any
   - Final recommendation: approve / request changes / needs more info

Important: do not implement fixes during review unless explicitly asked. Review first; comment on the PR only when it improves the PR outcome.
