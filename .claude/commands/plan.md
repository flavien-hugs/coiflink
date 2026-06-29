---
description: Create a detailed implementation spec in specs/ without implementing it
argument-hint: "<prompt>"
---
Create a detailed implementation specification for this request:

$ARGUMENTS

Do not implement the requested feature. Only create a planning/spec document.

Workflow:
1. Read enough repository context to make the plan accurate:
   - the repository's `README` and any relevant spec under `specs/`
   - any Architecture Decision Records under `docs/adr/` that bear on the request
   - the specific GitHub issue being worked, if the request maps to one
   - the existing application source tree for the affected area — if no source exists yet for this request, say so explicitly
2. Think through the request carefully and identify the owning package(s)/module(s), existing patterns, security/privacy constraints, and likely edge cases.
3. Create the `specs/` directory if it does not already exist.
4. Write a new Markdown spec file in `specs/`.
   - Derive a short, descriptive, kebab-case filename from the prompt when possible.
   - Prefer a stable name like `specs/<descriptive-slug>.md`.
   - If a file with that name already exists, choose a non-conflicting variant.
5. After writing the spec, report the spec path and a short summary. Do not make code changes beyond the spec file.

The spec must include these sections:

# <Descriptive Title>

## Problem Statement
Explain the user need and current gap.

## Goals
List concrete outcomes this implementation should achieve.

## Non-Goals
List related work that should remain out of scope.

## Relevant Repository Context
Summarize the relevant architecture, packages, modules, current status, and conventions. If the stack or a relevant design decision is not finalized yet, state which decisions are still open rather than assuming a language, framework, or build tool.

## Proposed Implementation
Describe the recommended implementation approach in enough detail for a coding agent to execute later.

## Affected Files / Packages / Modules
List likely files and modules to read or modify.

## API / Interface Changes
Describe any command-line, public API, network endpoint, or other interface surface changes. State "none" if none are expected.

## Data Model / Protocol Changes
Describe schema, storage format, persistence, or serialization changes. State "none" if none are expected.

## Security & Privacy Considerations
Call out any documented security/privacy constraints the change touches (data handling, key/credential management, authentication/authorization, residency or hosting requirements, size/latency budgets), and logging/redaction concerns (never log secrets or PII) as applicable. If the repository documents no constraint here, state that.

## Testing Plan
List unit, integration, end-to-end, resilience, or documentation tests that should be added or updated.

## Documentation Updates
List README, spec, ADR, or help-text updates needed.

## Risks and Open Questions
Identify ambiguities, blockers, compatibility concerns, and decisions needing confirmation.

## Implementation Checklist
Provide a step-by-step checklist suitable for a coding agent to follow later.

Important constraints to preserve:
- Respect the documented architecture and any security/privacy invariants the repository states; never weaken them in the plan.
- Never log or persist secrets, credentials, or PII.
- If the stack, build tool, or test command are not finalized yet, do not assume a particular language, framework, or toolchain in the plan; flag stack-dependent choices as decisions to confirm.
- Document new public APIs.
- Do not imply unimplemented behavior exists unless the later implementation actually adds it.
