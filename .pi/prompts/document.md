---
description: Update standalone documentation after a reviewed implementation (phased ADW)
argument-hint: "<change-summary-and-files>"
---
Update the repository's documentation to reflect the implemented, reviewed change.

Change summary, files changed, and context:

$ARGUMENTS

## Scope and boundary

This is the **standalone documentation pass**, distinct from the inline doc edits already made
during implementation:

- The `implement` phase already made the tight, code-local edits that must ship with the code
  (doc-comments on new public APIs, in-app/usage text, the focused references the change toggles).
  Do not redo or fight those.
- Here, update the broader prose that benefits from seeing the finished change: project docs that
  exist once the stack lands (e.g. a `docs/` tree, a `README`, developer guides), and — when a
  change shifts product scope or an issue's status — the relevant entries in those docs and any
  cross-references that are now stale. If no `docs/` tree or README exists yet, confine prose
  updates to whatever durable docs the repository does have (and only when the change actually
  invalidates them).

## Instructions

- Only update documentation when the change is user-visible, alters a public API/CLI/protocol,
  or invalidates an existing documentation statement. If nothing needs updating, change nothing
  and report `docs_updated` false.
- Edit existing documentation in place. Do NOT create an `app_docs/` tree or a new
  per-feature documentation hierarchy.
- Describe only what this change actually implements; do not overstate planned or future behavior.
- Preserve the repository's documented invariants in any prose you write: respect the documented
  architecture and any security/privacy constraints the repository states. Do not document
  anything that would contradict or weaken these.
- Do not document secrets, tokens, credentials, or PII; preserve existing redaction conventions.

Because this is the last authoring phase when it runs, also author the final commit message and
PR body (see the output instructions below) so they reflect all changes — code, tests, and docs.
