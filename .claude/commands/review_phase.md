---
description: Review the working-tree implementation in the phased ADW pipeline
argument-hint: "<spec-file-or-empty> <issue-and-change-context>"
---
Review the implementation currently in the working tree for this change. There is no pull
request yet — review the staged and uncommitted changes against the issue and, if one was
created, the spec.

Spec file, if any: $1

Issue and change context:

${@:2}

## What to do

1. Understand the change.
   - Inspect the working-tree diff against the base branch and read the changed files in
     context, not just the diff.
   - Read the issue/acceptance criteria and the spec (`$1`) when provided; treat them as the
     definition of done. For background, consult the repository's `README`, any relevant spec
     under `specs/`, and the specific GitHub issue being worked. The application source tree may
     not exist yet (early-stage repo) — review whatever artifacts the change touches.

2. Review for quality and correctness.
   - Correctness bugs, missing error handling, weak or missing tests, untested edge cases.
   - Scope control: the change should not exceed what the issue/spec asked for.
   - Docs updated when behavior changes; new public APIs documented.

3. Check the repository's documented invariants.
   - Respect the documented architecture and any security/privacy constraints the repository
     states; the change must not weaken them.
   - Secrets, credentials, and PII are never logged or persisted.
   - Where the repository documents trust, access-control, residency, or data-handling
     boundaries, verify the change respects them rather than bypassing them.

4. Grade every finding by severity:
   - `blocker` — must be fixed before merge. A later `patch` phase auto-resolves these.
   - `tech_debt` — should be addressed but is not blocking. Reported, not auto-fixed.
   - `skippable` — minor or nit. Reported only.

5. Author the release text.
   - This is the final authoring phase for most runs, so write a high-quality commit message
     (`commit_message.txt`) and PR body (`pr_body.md`) (see the output instructions below)
     describing the change, the tests/checks run, and any security considerations.
   - For tests/checks: run the project's configured test gate (the command surfaced via
     `MX_AGENT_TEST_CMD`) plus any format/lint/build checks the project defines. If no test
     command is configured yet, say so explicitly and recommend the exact command to run once
     the stack lands; do not assume a toolchain or invent one.

Do not modify code in this phase — only report findings; the `patch` phase fixes blockers.
