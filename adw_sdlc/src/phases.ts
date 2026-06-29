/**
 * Phase catalog, conditional gates, and phased prompt composition, ported
 * from adw/_phases.py. The orchestrator drives this catalog; templates under
 * .pi/prompts/ and .claude/commands/ are shared verbatim with the Python
 * pipeline (PLAN.md D4), so the composed prompt must match adw/ byte for
 * byte — except the fenced-JSON output-contract footer, which is gated off
 * for native-schema backends (PLAN.md Section 7).
 *
 * Model-tier routing lives in models.ts; per-phase result schemas (the
 * to_result analogue) live in schemas.ts.
 */

import { existsSync } from 'node:fs';
import { join } from 'node:path';

import { REPO_ROOT, renderPromptFile } from './common.js';
import { AdwError } from './errors.js';
import type { AdwState } from './state.js';

// --- phase catalog -----------------------------------------------------------

/**
 * Configurable agent-phase chain (Python-only setup/finalize/ci-fix/merge/
 * report always wrap this in the orchestrator and are not listed here).
 */
export const AGENT_PHASES = [
  'classify',
  'plan',
  'implement',
  'tests',
  'resolve',
  'e2e',
  'review',
  'patch',
  'document',
] as const;

export type AgentPhase = (typeof AGENT_PHASES)[number];

export const DEFAULT_PHASES: readonly AgentPhase[] = AGENT_PHASES;
export const CONDITIONAL_PHASES: ReadonlySet<AgentPhase> = new Set(['e2e', 'document']);
export const LOOP_PHASES: ReadonlySet<AgentPhase> = new Set(['resolve', 'patch']);

/** Phase -> prompt-template basename (without .md). */
export const TEMPLATE: Record<AgentPhase, string> = {
  classify: 'classify',
  plan: 'plan',
  implement: 'implement',
  tests: 'tests',
  resolve: 'resolve_failed_test',
  e2e: 'e2e_tests',
  // review uses a dedicated phased body (the PR-oriented review.md stays for
  // interactive use).
  review: 'review_phase',
  patch: 'patch',
  document: 'document',
};

/** Parse a `--phases` CSV into a validated ordered phase list. */
export function parsePhases(csv: string | null | undefined): AgentPhase[] {
  if (!csv) {
    return [...DEFAULT_PHASES];
  }
  const items = csv
    .split(',')
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
  if (items.length === 0) {
    throw new AdwError('no phases given');
  }
  for (const phase of items) {
    if (!(AGENT_PHASES as readonly string[]).includes(phase)) {
      throw new AdwError(`unknown phase: ${phase} (known: ${AGENT_PHASES.join(', ')})`);
    }
  }
  return items as AgentPhase[];
}

/** Resolve a phase template path, preferring .claude/commands for claude. */
export function templatePath(runner: string, name: string): string {
  if (runner === 'claude') {
    const claude = join(REPO_ROOT, '.claude', 'commands', `${name}.md`);
    if (existsSync(claude)) {
      return claude;
    }
  }
  return join(REPO_ROOT, '.pi', 'prompts', `${name}.md`);
}

// --- conditional gates -----------------------------------------------------------

// Whole words in the change signal (issue text + changed paths) that mean a
// change crosses a user-visible boundary worth end-to-end coverage. Matched on
// word boundaries (see hintIn), so the helper file path adw/_exec.py does NOT
// trip "exec" and "design"/"assignee" do NOT trip a signing hint. Ambiguous
// short stems are spelled out as their meaningful forms for the same reason.
const CROSS_BOUNDARY_HINTS = [
  'ipc',
  'daemon',
  'matrix',
  'signing',
  'signed',
  'signature',
  'trust',
  'policy',
  'sandbox',
  'pty',
  'stream',
  'artifact',
  'exec',
  'login',
  'sync',
  'scheduler',
  // Security / data-boundary surfaces worth e2e coverage.
  'crypto',
  'encryption',
  'decryption',
  'auth',
  'authentication',
  'offline',
  'backup',
  'recovery',
] as const;

// Whole words meaning the change is user-visible / API / protocol and warrants docs.
const DOC_HINTS = [
  'cli',
  'help',
  'public api',
  'protocol',
  'schema',
  'user-visible',
  'user facing',
  'user-facing',
  'config',
  'command',
  'flag',
  'endpoint',
  'migration',
] as const;

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Return the first hint that occurs as a whole word in `text`, else null.
 * Word-boundary matching (not bare substring) prevents incidental-substring
 * false positives (adw/_phases.py:151-162).
 */
function hintIn(text: string, hints: readonly string[]): string | null {
  for (const hint of hints) {
    if (new RegExp(`\\b${escapeRegExp(hint)}\\b`).test(text)) {
      return hint;
    }
  }
  return null;
}

export interface GateDecision {
  runIt: boolean;
  reason: string;
}

/** Decide whether the e2e phase should run, with a recorded reason. */
export function gateE2e(signal: string): GateDecision {
  const low = (signal || '').toLowerCase();
  const hit = hintIn(low, CROSS_BOUNDARY_HINTS);
  if (hit !== null) {
    return { runIt: true, reason: `change touches cross-boundary flows (${hit})` };
  }
  return { runIt: false, reason: 'no cross-boundary surface detected' };
}

/** Decide whether the document phase should run, with a recorded reason. */
export function gateDocument(signal: string, changedFiles: readonly string[] = []): GateDecision {
  const low = (signal || '').toLowerCase();
  const docLike = changedFiles.some(
    (f) => f === 'README.md' || f.startsWith('docs/') || f.startsWith('wiki/') || f.endsWith('.md'),
  );
  if (docLike) {
    return { runIt: true, reason: 'documentation files changed' };
  }
  const hit = hintIn(low, DOC_HINTS);
  if (hit !== null) {
    return { runIt: true, reason: `user-visible/API/protocol surface affected (${hit})` };
  }
  return { runIt: false, reason: 'internal-only change; no docs update needed' };
}

/**
 * Decide a conditional phase via its gate. Throws AdwError for any
 * non-conditional phase so a miswired caller fails loudly instead of
 * silently running it.
 */
export function gateConditional(
  phase: string,
  signal: string,
  changedFiles: readonly string[] = [],
): GateDecision {
  if (phase === 'e2e') {
    return gateE2e(signal);
  }
  if (phase === 'document') {
    return gateDocument(signal, changedFiles);
  }
  throw new AdwError(`not a conditional phase: ${phase}`);
}

// --- phased envelope -----------------------------------------------------------
//
// The reused templates were written for interactive/one-shot use and are also
// consumed by the Python pipeline, so they must not be edited for phased mode.
// Instead the orchestrator composes each phase prompt as:
//
//     [shared preamble] + [per-phase reframing] + [domain template body] + [footer]
//
// The preamble/footer (owned here, in code) supply the phased rules — the
// orchestrator owns git/gh; no GitHub access; emit a trailing JSON contract —
// and override stale framing in the reused bodies. The preamble is the
// prompt-level half of the D5 secret boundary (engine-neutral wording: the
// orchestrator, not "Python", owns git/gh in this standalone port).

export const PHASE_PREAMBLE_SHARED =
  'You are running as a single automated phase of the ADW pipeline.\n' +
  'The orchestrator performs ALL git and GitHub work for this run: do NOT run git or gh, do NOT ' +
  'create/switch/commit/push branches, and do NOT open, merge, or comment on pull requests. ' +
  'If the task section below tells you to do any of that, skip those steps.\n' +
  'You have no GitHub access in this phase; all issue context you need is provided inline.\n';

// Per-phase reframing prepended after the shared preamble; overrides stale
// framing carried by the reused interactive templates.
export const PHASE_CONTEXT: Partial<Record<AgentPhase, string>> = {
  implement:
    'Scope for this phase: make the code change only. Focused tests are added in a ' +
    'separate `tests` phase — do not do broad test work here. If $1 names a spec file that exists, ' +
    'treat it as the source of truth; otherwise (e.g. $1 is a placeholder note, not a path) treat ' +
    'the inline issue context as the spec and implement directly — do NOT stop merely because no ' +
    'spec file path was provided.\n',
  tests: 'Scope for this phase: add or strengthen focused, non-e2e tests for the change.\n',
  e2e:
    'The orchestrator already decided this phase should run; do the work rather than ' +
    're-deciding whether e2e coverage is warranted.\n',
  // review uses a dedicated phased template (review_phase.md) that is already
  // working-tree-oriented, so it needs no reframing here.
  document:
    'The orchestrator already decided documentation is warranted; update the existing ' +
    'docs surface (README/docs/wiki/help) only. Do not create an app_docs/ tree.\n',
};

/**
 * Per-phase JSON output shape, rendered into the fenced-JSON footer. Kept in
 * sync with schemas.ts (the parsing source of truth) — the contract-drift
 * test asserts every key here appears in the matching Zod schema.
 */
export const OUTPUT_CONTRACT: Record<AgentPhase, string> = {
  classify: '{"issue_class": "feat|fix|docs|chore|ci|test|refactor", "reason": "<one sentence>"}',
  plan: '{"plan_file": "specs/<file>.md", "spec_created": true, "summary": "<short>"}',
  implement: '{"summary": "<short>", "files_changed": ["<path>", "..."]}',
  tests: '{"tests_added": true, "summary": "<short>"}',
  resolve: '{"resolved": 0, "remaining": 0, "summary": "<short>"}',
  e2e: '{"e2e_added": true, "summary": "<short>"}',
  review:
    '{"findings": [{"severity": "blocker|tech_debt|skippable", "description": "<what>", ' +
    '"location": "<file:line>"}], "wrote_commit_message": true, "wrote_pr_body": true}',
  patch: '{"resolved": 0, "remaining": 0, "summary": "<short>"}',
  document:
    '{"docs_updated": true, "files": ["docs/<file>"], "wrote_commit_message": true, "wrote_pr_body": true}',
};

/** Phases that author free-form text to workspace files instead of inlining it in JSON. */
export const ARTIFACT_PHASES: ReadonlySet<AgentPhase> = new Set(['review', 'document']);

/** Workspace path where the authoring phase writes the commit message. */
export function commitMessagePath(state: AdwState): string {
  return join(state.workspace(), 'commit_message.txt');
}

/** Workspace path where the authoring phase writes the PR body. */
export function prBodyPath(state: AdwState): string {
  return join(state.workspace(), 'pr_body.md');
}

/**
 * Build the per-phase footer. Artifact-file instructions are independent of
 * the output mechanism and always emitted for artifact phases; the fenced-
 * JSON contract block exists solely for stdout parsing, so it is gated off
 * when the backend constrains output to a schema natively (PLAN.md Section 7
 * — the footer and a native outputFormat must never both be active).
 */
export function buildFooter(phase: AgentPhase, state: AdwState, emitJsonContract: boolean): string {
  const lines: string[] = [];
  if (ARTIFACT_PHASES.has(phase)) {
    lines.push(
      'Author these files first (this keeps large free-form text out of the JSON, which',
      'the pipeline parses mechanically):',
      '- Write the full commit message (subject + body, ending with a line `closes #<issue>`) to: ' +
        commitMessagePath(state),
      `- Write the complete PR body (Markdown) to: ${prBodyPath(state)}`,
      'Set the matching wrote_* booleans to true once each file is written.',
      '',
    );
  }
  if (emitJsonContract) {
    lines.push(
      '## Required output',
      '',
      'End your reply with EXACTLY one fenced ```json block matching this shape, and nothing after it:',
      '',
      '```json',
      OUTPUT_CONTRACT[phase],
      '```',
    );
  }
  return lines.join('\n');
}

/**
 * Compose the full phased prompt for `phase` (pure): shared preamble +
 * per-phase reframing + the (reused or new) domain template body + the
 * footer. With emitJsonContract=false (native-schema backends) the JSON
 * contract block is omitted; an entirely empty footer drops its separator.
 */
export function composePhasePrompt(
  phase: AgentPhase,
  templateArgs: readonly string[],
  state: AdwState,
  runner = 'pi',
  emitJsonContract = true,
): string {
  const tpath = templatePath(runner, TEMPLATE[phase]);
  if (!existsSync(tpath)) {
    throw new AdwError(`prompt template not found for phase ${phase}: ${tpath}`);
  }
  const body = renderPromptFile(tpath, templateArgs);
  const preamble = PHASE_PREAMBLE_SHARED + (PHASE_CONTEXT[phase] ?? '');
  const footer = buildFooter(phase, state, emitJsonContract);
  if (!footer) {
    return `${preamble}\n---\n\n${body}\n`;
  }
  return `${preamble}\n---\n\n${body}\n\n---\n\n${footer}\n`;
}
