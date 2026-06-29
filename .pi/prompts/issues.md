---
description: Implement multiple GitHub issues sequentially using /issue semantics
argument-hint: "<issue-id-or-range> [issue-id-or-range ...] [-- notes]"
---
Implement multiple GitHub issues sequentially for this repository, end to end, using `/issue` semantics for each issue.

Issue selectors and shared notes:

$ARGUMENTS

`/issues` is a batch orchestrator. It must process issues one at a time, in normalized order, and must return to a clean, updated `main` between issues. Do not parallelize. Do not combine multiple issues into one branch or PR unless the user explicitly asks and the issues genuinely require a shared implementation.

Read `.claude/commands/issue.md` before starting. Treat it as the phase contract for each individual issue. Apply its workflow inline for every issue; do not merely tell the user to run `/issue` separately.

Workflow:

1. Parse and normalize issue selectors
   - Accept single numeric issue IDs, e.g. `12`.
   - Accept inclusive hyphen ranges, e.g. `12-14` expands to `12, 13, 14`.
   - Accept inclusive dot ranges, e.g. `12..14` expands to `12, 13, 14`.
   - Preserve the order written by the user.
   - Expand ranges in place.
   - Deduplicate repeated IDs while preserving the first occurrence.
   - Treat everything after `--` as shared notes/context to pass into each issue workflow.
   - If no issue selector is provided, stop and ask for one or more issue IDs/ranges.
   - If any selector is invalid, stop and report the invalid selector.
   - Print the expanded issue list before starting.
   - If more than 5 issues are selected, ask for confirmation before proceeding.

2. Preflight all selected issues before implementing any of them
   - For each normalized issue ID, inspect the title, labels, milestone, status, scope, dependencies, and acceptance criteria via the issue context provided to you (or with `gh`, using `~/.local/bin/gh` if `gh` is not on PATH).
   - Cross-check each issue against the repository's `README`, any relevant spec under `specs/`, and any documented milestone ordering for scope and the dependency chain.
   - If an issue is already CLOSED, mark it as skipped and continue.
   - If an issue is missing or inaccessible, stop and report it.
   - Detect obvious dependency lines such as `Depends on #<id>`, and respect any documented ordering or critical path.
   - If an issue depends on another selected issue that appears later in the normalized list, recommend reordering and ask whether to continue in the given order.
   - If an issue depends on an open issue that is not selected, ask whether to skip that issue, stop the batch, or continue anyway.
   - Stop for real blockers such as acceptance criteria that conflict with the repository's documented security/privacy constraints, require real secrets/credentials or real user data, require choosing the technical stack with insufficient detail, or require broad architecture decisions that are not yet settled.

3. Establish batch processing rules
   - Default branch/PR strategy: one issue → one branch → one PR → one merge.
   - Preserve user-provided order after range expansion unless dependency preflight leads to an explicit user-approved reorder.
   - Continue automatically after successfully shipped issues.
   - Skip already-closed issues.
   - If an issue hits a genuine blocker, stop the entire batch unless the user explicitly instructs you to skip blocked issues.
   - If CI fails for an issue, fix it as `/issue` would; do not move on while that PR is red.
   - If the repository is dirty unexpectedly between issues, stop and report the dirty state.

4. Process each issue sequentially using `/issue` semantics
   For each issue ID that was not skipped:
   - Confirm the repository is on `main`, updated from origin, and has a clean working tree before starting.
   - Run the equivalent of `/issue <id> <shared notes>` inline, following `.claude/commands/issue.md` completely:
     - read repository context (README, any relevant spec, the issue, and any existing source tree — noting if no source exists yet)
     - decide whether a `/plan`-style spec is needed
     - implement using `/implement` semantics
     - strengthen focused tests using `/tests` semantics
     - evaluate e2e coverage using `/e2e_tests` semantics
     - self-review using `/review` semantics
     - run the configured test gate and any required checks
     - hand off a clean working tree and a commit message ending in `closes #<id>` plus a complete PR body for the orchestrator to commit, push, open the PR, watch CI, fix failures until green, review, and merge
   - Confirm the issue is closed after merge.
   - Record the result, PR number, spec path or spec-skip reason, tests added, e2e decision, checks, assumptions, and any follow-up notes.
   - Only then continue to the next issue.

5. Preserve the repository's invariants for every issue
   - Respect the documented architecture and any security/privacy constraints the repository states; never weaken them.
   - Never log or persist secrets, credentials, or PII.
   - Keep documented trust, access-control, residency, and data-handling boundaries intact.
   - Identify the owning component and reuse existing patterns before editing.
   - If the technical stack (framework, language, object storage, build tool, test command) is NOT chosen yet, do not assume one, and do not imply that any feature or component already exists unless a given issue actually implements it.

6. Final batch report
   At the end, produce a concise table with one row per normalized issue:

   | Issue | Result | PR | Spec | Tests | E2E | Notes |
   |---|---|---|---|---|---|---|

   Include:
   - Total selected
   - Total shipped
   - Total skipped
   - Total blocked
   - Final branch
   - Final working tree status
   - Any issue order/dependency decisions
   - Any assumptions, risks, limitations, or follow-up work

Important: `/issues` is intentionally sequential and conservative. Each issue should be fully shipped or explicitly skipped/blocked before moving to the next one.
