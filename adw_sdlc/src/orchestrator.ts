/**
 * Phased ADW delivery driver, ported from adw/_orchestrator.py with
 * byte-for-byte-equivalent control-flow semantics (PLAN.md D4): the TS
 * control plane runs a sequence of discrete, single-purpose agent phases
 * (each one runner invocation through the AgentRunner seam), threads
 * AdwState between them, and performs all git/GitHub mechanics itself — the
 * coding agent never sees GH_TOKEN in this mode. Setup, finalize, CI-watch,
 * and the squash-merge gate live here; the agent authors only the commit
 * message and PR body.
 *
 * Differences from the Python driver are exactly the planned ones:
 * - phases run through runner.runPhase via run-phase.ts (not a CLI spawn);
 * - classify runs on the shared Anthropic-SDK structured call by default
 *   (opt-out MX_AGENT_CLASSIFY_ON_RUNNER=1 routes it through the runner);
 * - per-phase cost/usage is accumulated additively into state.
 *
 * Every external effect is injected via OrchestratorDeps (defaulting to the
 * real implementations) — the TS analogue of the module seams the Python
 * tests patch — so the parity suite drives run() with no real agent/git/gh.
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { shellSplit } from './common.js';
import { AdwError } from './errors.js';
import { safeSubprocessEnv } from './env.js';
import {
  assumeYes,
  capture,
  confirm,
  detectRepo,
  issueState,
  note,
  postProgress,
  resolveGhBin,
  workingTreeDirty,
  type Captured,
} from './exec.js';
import * as git from './git.js';
import { prNumberFromUrl } from './git.js';
import type { AgentRunner } from './invoker.js';
import { deriveBranch, fetchIssue, setStatus, type IssueContext } from './issue.js';
import {
  commitMessagePath,
  composePhasePrompt,
  CONDITIONAL_PHASES,
  gateConditional,
  parsePhases,
  prBodyPath,
  type AgentPhase,
} from './phases.js';
import { runAgentPhase, type AgentPhaseOutcome } from './run-phase.js';
import {
  ClassifySchema,
  type ClassifyResult,
  type ImplementResult,
  type PlanResult,
  type ReviewFinding,
  type ReviewResult,
} from './schemas.js';
import { AdwState, makeAdwId } from './state.js';
import { structuredCall, type StructuredCallOptions, type StructuredCallResult } from './structured-call.js';
import type { PhaseUsage } from './invoker.js';

/** Cap failure text fed into prompts/comments (adw/_orchestrator.py:38). */
export const MAX_OUTPUT_CHARS = 8000;

/**
 * How many times to re-poll an empty check rollup before concluding the PR
 * genuinely has no checks (vs. checks merely not registered yet right after
 * `gh pr create`).
 */
const NO_CHECKS_SETTLE_POLLS = 3;

/**
 * Default test gate. Empty in this standalone port — the project has not yet
 * chosen its stack/test command, so nothing is assumed. Configure
 * a real command via `--test-cmd` / `MX_AGENT_TEST_CMD` once the stack lands;
 * an empty gate is skipped (treated as green) rather than run.
 */
export const DEFAULT_TEST_CMD = '';

/**
 * Extra pre-merge verification gates beyond the test gate (e.g. format/lint/
 * build). Empty by default — no toolchain is assumed. Populate at runtime via
 * `MX_AGENT_FINALIZE_GATES` (newline-separated) in finalizeAndMerge.
 */
export const DEFAULT_FINALIZE_GATES: readonly string[] = [];

// --- options & injected seams -------------------------------------------------

export interface RunOptions {
  base?: string;
  /** Comma-separated phase subset/order; default: the full chain. */
  phases?: string;
  adwId?: string;
  resume?: boolean;
  noProgress?: boolean;
  /**
   * EXPLICIT OPT-OUT of the D5 secret boundary: forwards the FULL parent
   * environment — including GH_TOKEN and MATRIX_*-/MX_AGENT_*-prefixed
   * secrets — to the runner child. The faithful port of Python's
   * --inherit-env (adw/_orchestrator.py:594, env=None → full inherit),
   * documented there as "less isolated". Never set this in unattended runs.
   */
  inheritEnv?: boolean;
  maxResolve?: number;
  maxPatch?: number;
  maxCiFix?: number;
  ciPollIntervalMs?: number;
  ciMaxPolls?: number;
  testCmd?: string;
  /** --model override; per-phase MX_AGENT_MODEL_<PHASE> still applies under it. */
  model?: string;
  repo?: string;
  /** Per-phase runner timeout in milliseconds (0 = none). */
  timeoutMs?: number;
  verify?: boolean;
  force?: boolean;
  allowDirty?: boolean;
  yes?: boolean;
  dryRun?: boolean;
  maxBudgetUsd?: number;
}

type ResolvedOptions = Required<Omit<RunOptions, 'phases' | 'adwId' | 'repo' | 'maxBudgetUsd'>> &
  Pick<RunOptions, 'phases' | 'adwId' | 'repo' | 'maxBudgetUsd'>;

/** Defaults mirror adw/issue.py build_parser. */
function resolveOptions(options: RunOptions): ResolvedOptions {
  return {
    base: options.base ?? 'main',
    resume: options.resume ?? false,
    noProgress: options.noProgress ?? false,
    inheritEnv: options.inheritEnv ?? false,
    maxResolve: options.maxResolve ?? 3,
    maxPatch: options.maxPatch ?? 2,
    maxCiFix: options.maxCiFix ?? 3,
    ciPollIntervalMs: options.ciPollIntervalMs ?? 30_000,
    ciMaxPolls: options.ciMaxPolls ?? 40,
    testCmd: options.testCmd ?? '',
    model: options.model ?? '',
    timeoutMs: options.timeoutMs ?? 0,
    verify: options.verify ?? true,
    force: options.force ?? false,
    allowDirty: options.allowDirty ?? false,
    yes: options.yes ?? false,
    dryRun: options.dryRun ?? false,
    phases: options.phases,
    adwId: options.adwId,
    repo: options.repo,
    maxBudgetUsd: options.maxBudgetUsd,
  };
}

export interface RunCmdResult {
  rc: number;
  output: string;
}

export type ProgressFn = (phase: string, message: string) => void;

export interface GitOps {
  createOrCheckoutBranch: typeof git.createOrCheckoutBranch;
  commitAll: typeof git.commitAll;
  push: typeof git.push;
  pullRebase: typeof git.pullRebase;
  prForBranch: typeof git.prForBranch;
  createPr: typeof git.createPr;
  ciStatus: typeof git.ciStatus;
  squashMerge: typeof git.squashMerge;
}

/**
 * Every external effect run() touches, injectable for tests (the analogue of
 * the seams adw/test_orchestrator.py patches).
 */
export interface OrchestratorDeps {
  env: Record<string, string | undefined>;
  isatty: () => boolean;
  confirm: (prompt: string) => Promise<boolean>;
  sleep: (ms: number) => Promise<void>;
  /**
   * Run a local gate command with the inherited env; gate commands are build
   * tools (e.g. cargo test), not the coding agent, so they legitimately use
   * the normal environment.
   */
  runCmd: (cmd: readonly string[]) => RunCmdResult;
  capture: (cmd: readonly string[]) => Captured;
  workingTreeDirty: () => boolean;
  changedFiles: (base: string) => string[];
  resolveGhBin: () => string | null;
  detectRepo: (ghBin: string | null) => string;
  issueState: (ghBin: string | null, issue: number, repo: string) => string;
  postProgress: typeof postProgress;
  fetchIssue: (ghBin: string | null, issue: number, repo: string) => IssueContext | null;
  setStatus: (ghBin: string, owner: string, issue: number, status: string) => void;
  git: GitOps;
  runAgentPhase: typeof runAgentPhase;
  classify: (
    prompt: string,
    options?: StructuredCallOptions,
  ) => Promise<StructuredCallResult<ClassifyResult>>;
}

export function defaultDeps(): OrchestratorDeps {
  return {
    env: process.env,
    isatty: () => process.stdin.isTTY === true,
    confirm,
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    runCmd: (cmd) => {
      const result = capture(cmd);
      return { rc: result.returncode, output: (result.stdout || '') + (result.stderr || '') };
    },
    capture,
    workingTreeDirty,
    changedFiles,
    resolveGhBin,
    detectRepo,
    issueState,
    postProgress,
    fetchIssue,
    setStatus,
    git: {
      createOrCheckoutBranch: git.createOrCheckoutBranch,
      commitAll: git.commitAll,
      push: git.push,
      pullRebase: git.pullRebase,
      prForBranch: git.prForBranch,
      createPr: git.createPr,
      ciStatus: git.ciStatus,
      squashMerge: git.squashMerge,
    },
    runAgentPhase,
    classify: (prompt, options) => structuredCall(prompt, ClassifySchema, options),
  };
}

/** The per-run agent invocation context threaded into every phase call. */
interface AgentCtx {
  runner: AgentRunner;
  cliModel: string;
  env: Record<string, string>;
  timeoutMs: number;
  maxBudgetUsd?: number;
}

// --- helpers (unit-testable) ------------------------------------------------------

/** Tail-truncate noisy output for inclusion in a prompt or comment. */
export function truncate(text: string, limit: number = MAX_OUTPUT_CHARS): string {
  const t = text || '';
  if (t.length <= limit) {
    return t;
  }
  return `…(truncated)…\n${t.slice(t.length - limit)}`;
}

/**
 * Gate the irreversible squash-merge; throws AdwError to abort. When stdin
 * is not a terminal and the run was not pre-authorized (--yes /
 * MX_AGENT_YES=1), refuse rather than silently merge.
 */
export async function confirmMerge(options: {
  yes: boolean;
  isatty: boolean;
  confirm: (prompt: string) => Promise<boolean>;
}): Promise<void> {
  if (options.yes) {
    return;
  }
  if (!options.isatty) {
    throw new AdwError('refusing to merge unattended without --yes / MX_AGENT_YES=1');
  }
  if (!(await options.confirm('>> About to squash-merge this PR to main. Continue? [y/N] '))) {
    throw new AdwError('aborted');
  }
}

/** Best-effort list of files changed vs origin/<base>. */
export function changedFiles(base: string): string[] {
  const result = capture(['git', 'diff', `origin/${base}`, '--name-only']);
  if (result.returncode !== 0) {
    return [];
  }
  return result.stdout
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** Render review findings into a prompt-friendly block. */
export function renderFindings(findings: readonly ReviewFinding[]): string {
  return findings
    .map((f, idx) => {
      const loc = f.location ? ` (${f.location})` : '';
      return `${idx + 1}. [${f.severity}]${loc} ${f.description}`;
    })
    .join('\n');
}

/**
 * Accumulate a phase's dollars into the run's additive total. A null cost
 * means "could not be priced", which poisons the whole accumulation: the
 * total sticks to null rather than silently becoming a false partial sum.
 * An absent (undefined) cost carries no information and is a no-op.
 */
function recordUsage(state: AdwState, usage: PhaseUsage): void {
  if (usage.costUsd === null) {
    state.totalCostUsd = null;
  } else if (usage.costUsd !== undefined && state.totalCostUsd !== null) {
    state.totalCostUsd = (state.totalCostUsd ?? 0) + usage.costUsd;
  }
}

// --- bounded loops -----------------------------------------------------------------

/**
 * Run the test gate, asking the agent to fix failures, until green. Returns
 * true if the gate is green, false if it is still failing after the bound or
 * the agent makes no progress.
 */
export async function resolveLoop(
  state: AdwState,
  agent: AgentCtx,
  config: { testCmd: string; maxAttempts: number; progress: ProgressFn },
  deps: OrchestratorDeps,
): Promise<boolean> {
  if (config.testCmd.trim() === '') {
    config.progress('resolve', 'no test command configured; skipping test gate');
    return true;
  }
  const gate = shellSplit(config.testCmd);
  let attempt = 0;
  for (;;) {
    const { rc, output } = deps.runCmd(gate);
    if (rc === 0) {
      config.progress('resolve', 'test gate is green');
      return true;
    }
    if (attempt >= config.maxAttempts) {
      config.progress('resolve', `test gate still failing after ${config.maxAttempts} attempt(s)`);
      return false;
    }
    attempt += 1;
    config.progress('resolve', `test gate failed; resolve attempt ${attempt}/${config.maxAttempts}`);
    const outcome = await invokeAgent(deps, 'resolve', [truncate(output)], state, agent);
    recordUsage(state, outcome.usage);
    if (outcome.data.resolved === 0) {
      config.progress('resolve', 'agent resolved nothing; stopping');
      return false;
    }
  }
}

/** Patch blocker findings (only) until none remain. Returns true when clear. */
export async function patchLoop(
  state: AdwState,
  findings: readonly ReviewFinding[],
  agent: AgentCtx,
  config: { maxAttempts: number; progress: ProgressFn },
  deps: OrchestratorDeps,
): Promise<boolean> {
  const blockers = findings.filter((f) => f.severity === 'blocker');
  const others = findings.length - blockers.length;
  if (others > 0) {
    config.progress('patch', `${others} non-blocker finding(s) reported, not auto-fixed`);
  }
  if (blockers.length === 0) {
    config.progress('patch', 'no blocker findings');
    return true;
  }

  let remaining = blockers.length;
  const blockersText = renderFindings(blockers);
  // On retries the count, not the list, shrinks; tell the agent the full list
  // may be partly fixed so it re-checks each instead of re-editing fixed ones.
  const retryNote =
    'Some of these may already be resolved by a previous attempt. Re-check each ' +
    'against the current working tree and only fix the ones that still apply.\n\n';
  let attempt = 0;
  while (remaining > 0 && attempt < config.maxAttempts) {
    attempt += 1;
    config.progress('patch', `resolving ${remaining} blocker(s); attempt ${attempt}/${config.maxAttempts}`);
    const promptText = attempt === 1 ? blockersText : retryNote + blockersText;
    const outcome = await invokeAgent(deps, 'patch', [promptText], state, agent);
    recordUsage(state, outcome.usage);
    const result = outcome.data;
    if (result.resolved === 0 || result.remaining >= remaining) {
      remaining = result.remaining;
      break;
    }
    remaining = result.remaining;
  }
  return remaining === 0;
}

/** Watch CI and ask the agent to fix red checks until green. Returns success. */
export async function ciFixLoop(
  state: AdwState,
  pr: number | string,
  agent: AgentCtx,
  config: {
    ghBin: string;
    repo: string;
    maxAttempts: number;
    pollIntervalMs: number;
    maxPolls: number;
    progress: ProgressFn;
  },
  deps: OrchestratorDeps,
): Promise<boolean> {
  let attempt = 0;
  let polls = 0;
  // Tolerate a short window where no checks have registered yet. Like the
  // Python original, this settle counter is deliberately NOT reset after a
  // fix-push (only `polls` is) — fixing that quirk in one engine would break
  // the byte-for-byte semantics parity (D4); change both engines together
  // post-cutover if it ever matters in practice.
  let nonePolls = 0;
  for (;;) {
    const status = deps.git.ciStatus(pr, config.ghBin, config.repo);
    if (status.state === 'success') {
      config.progress('ci-fix', 'CI is green');
      return true;
    }
    if (status.state === 'none') {
      // Query succeeded but the PR has no checks. Right after `gh pr create`
      // they may not be registered yet, so settle briefly before concluding
      // there is genuinely nothing to gate on (treated as green).
      nonePolls += 1;
      if (nonePolls > NO_CHECKS_SETTLE_POLLS) {
        config.progress('ci-fix', 'no CI checks registered; treating as green');
        return true;
      }
      if (config.pollIntervalMs > 0) {
        await deps.sleep(config.pollIntervalMs);
      }
      continue;
    }
    if (status.state === 'unknown') {
      config.progress('ci-fix', 'could not determine CI status');
      return false;
    }
    if (status.state === 'pending') {
      polls += 1;
      if (polls > config.maxPolls) {
        config.progress('ci-fix', 'CI still pending after polling budget');
        return false;
      }
      if (config.pollIntervalMs > 0) {
        await deps.sleep(config.pollIntervalMs);
      }
      continue;
    }
    // failure
    if (attempt >= config.maxAttempts) {
      config.progress('ci-fix', `CI still red after ${config.maxAttempts} fix attempt(s)`);
      return false;
    }
    attempt += 1;
    const names = status.failingJobs.map((j) => j.name).join(', ') || 'unknown jobs';
    config.progress('ci-fix', `CI red (${names}); fix attempt ${attempt}/${config.maxAttempts}`);
    const outcome = await invokeAgent(
      deps,
      'resolve',
      [`CI is failing for these checks: ${names}. Fix the cause.`],
      state,
      agent,
    );
    recordUsage(state, outcome.usage);
    if (outcome.data.resolved === 0) {
      config.progress('ci-fix', 'agent resolved nothing; stopping');
      return false;
    }
    // An agent claiming a fix that left no committable change can't move CI;
    // stop instead of re-pushing the same tree and burning the poll budget.
    if (!deps.workingTreeDirty()) {
      config.progress('ci-fix', 'agent reported a fix but changed nothing; stopping');
      return false;
    }
    const { ok } = deps.git.commitAll(`fix: address CI failures (${names})`);
    if (ok) {
      deps.git.push(state.branchName ?? '');
      polls = 0; // a new commit kicks off a fresh CI run; reset the budget
    }
  }
}

/** One agent-phase call through the injected run-phase seam. */
function invokeAgent<P extends 'resolve' | 'patch'>(
  deps: OrchestratorDeps,
  phase: P,
  templateArgs: readonly string[],
  state: AdwState,
  agent: AgentCtx,
): Promise<AgentPhaseOutcome<P>> {
  return deps.runAgentPhase({
    phase,
    templateArgs,
    state,
    runner: agent.runner,
    cliModel: agent.cliModel,
    env: agent.env,
    timeoutMs: agent.timeoutMs,
    ...(agent.maxBudgetUsd !== undefined ? { maxBudgetUsd: agent.maxBudgetUsd } : {}),
  });
}

// --- phase argument assembly -----------------------------------------------------

function issueBlob(issue: number, ctx: IssueContext): string {
  return `GitHub issue #${issue}: ${ctx.title}\nLabels: ${ctx.labels.join(' ')}\n\n${ctx.body}`.trim();
}

/** Assemble template arguments, injecting context the token-less agent lacks. */
function phaseArgs(
  phase: AgentPhase,
  issue: number,
  state: AdwState,
  ctx: IssueContext,
  files: readonly string[],
): string[] {
  const blob = issueBlob(issue, ctx);
  switch (phase) {
    case 'classify':
      return [String(issue), blob];
    case 'plan':
      return [blob];
    case 'implement':
      return [state.planFile ?? '(no spec; implement directly from the issue)', blob];
    case 'tests':
      return [`Issue #${issue} on branch ${state.branchName}: add focused coverage for this change.\n\n${blob}`];
    case 'e2e':
      return [`Issue #${issue} on branch ${state.branchName}: add e2e coverage if warranted.\n\n${blob}`];
    case 'review':
      // review_phase.md: $1 = spec file (may be empty), ${@:2} = issue/change context.
      return [state.planFile ?? '', blob];
    case 'document':
      return [`Change for issue #${issue}; files changed: ${files.join(', ') || 'n/a'}.\n\n${blob}`];
    default:
      return [blob];
  }
}

/**
 * Read the agent-authored commit message / PR body artifacts into state.
 * Free-form text is authored to workspace files (not inlined in JSON) by the
 * review and document phases; document overwrites review, so the last
 * authoring phase wins. Best effort — a missing/unreadable file is ignored.
 */
export function absorbAuthoredText(state: AdwState): void {
  const targets: Array<[string, 'commitMessage' | 'prBody']> = [
    [commitMessagePath(state), 'commitMessage'],
    [prBodyPath(state), 'prBody'],
  ];
  for (const [path, attr] of targets) {
    try {
      const text = readFileSync(path, 'utf8').trim();
      if (text) {
        state[attr] = text;
      }
    } catch {
      // best effort
    }
  }
}

/** Fold a phase result back into run state. */
function applyResult(state: AdwState, phase: AgentPhase, result: unknown): void {
  if (phase === 'classify') {
    state.issueClass = (result as ClassifyResult).issue_class;
  } else if (phase === 'plan') {
    const plan = result as PlanResult;
    if (plan.plan_file) {
      state.planFile = plan.plan_file;
    }
  }
}

// --- setup / finalize -----------------------------------------------------------

/** Setup phase: branch from base, assign, move board to In Progress. */
function setup(
  state: AdwState,
  ghBin: string | null,
  repo: string,
  issue: number,
  ctx: IssueContext,
  base: string,
  progress: ProgressFn,
  deps: OrchestratorDeps,
): void {
  const branch = deriveBranch(issue, ctx.title, ctx.labels, state.adwId);
  state.branchName = branch;
  const { ok, error } = deps.git.createOrCheckoutBranch(branch, base);
  if (!ok) {
    throw new AdwError(`failed to create/checkout branch ${branch}: ${error}`);
  }
  progress('setup', `on branch ${branch}`);
  if (ghBin) {
    const edit = [ghBin, 'issue', 'edit', String(issue), '--add-assignee', '@me'];
    if (repo) {
      edit.push('--repo', repo);
    }
    deps.capture(edit);
    const owner = repo ? (repo.split('/')[0] ?? '') : '';
    if (owner) {
      try {
        deps.setStatus(ghBin, owner, issue, 'In Progress');
      } catch {
        note('could not update board status'); // board update is best effort
      }
    }
  }
}

/**
 * Pre-merge gate commands: the test gate (when configured) followed by any
 * extra quality gates. An empty `testCmd` contributes no test gate (the
 * standalone port assumes no toolchain until one is configured); `extraGates`
 * are additional format/lint/build commands sourced from MX_AGENT_FINALIZE_GATES.
 */
export function finalizeGates(testCmd: string, extraGates: readonly string[] = []): string[] {
  const gates: string[] = [...DEFAULT_FINALIZE_GATES, ...extraGates];
  return testCmd ? [testCmd, ...gates] : [...gates];
}

/** Run gates, commit, push, open PR, watch CI, gate-merge, verify, report. */
async function finalizeAndMerge(
  state: AdwState,
  opts: ResolvedOptions,
  context: {
    ghBin: string | null;
    repo: string;
    issue: number;
    agent: AgentCtx;
    progress: ProgressFn;
  },
  deps: OrchestratorDeps,
): Promise<number> {
  const { ghBin, repo, issue, agent, progress } = context;

  // Resume guard: if this run already merged, the branch is gone and the PR is
  // closed — re-running finalize would fail on push or re-merge. Just re-verify.
  if (state.isDone('merge')) {
    progress('report', `merge already completed for ${state.adwId}; nothing to finalize`);
    if (opts.verify && ghBin) {
      const st = deps.issueState(ghBin, issue, repo);
      if (st !== 'CLOSED') {
        throw new AdwError(`issue #${issue} is ${st} despite a recorded merge; treating as failure`);
      }
    }
    return 0;
  }

  // Final verification gates (orchestrator-owned). Merge only on green.
  // Extra (non-test) gates are configured per-repo via MX_AGENT_FINALIZE_GATES
  // (newline-separated); empty by default so a freshly-ported repo can merge.
  const extraGates = (process.env['MX_AGENT_FINALIZE_GATES'] ?? '')
    .split('\n')
    .map((g) => g.trim())
    .filter((g) => g.length > 0);
  for (const gate of finalizeGates(opts.testCmd, extraGates)) {
    const { rc } = deps.runCmd(shellSplit(gate));
    if (rc !== 0) {
      progress('finalize', `gate failed: ${gate}; not merging`);
      throw new AdwError(`pre-merge gate failed: ${gate}`);
    }
  }
  progress('finalize', 'all pre-merge gates green');

  const commitMessage = state.commitMessage ?? `feat: implement issue #${issue}\n\ncloses #${issue}`;
  const committed = deps.git.commitAll(commitMessage);
  if (!committed.ok) {
    throw new AdwError(`commit failed: ${committed.error}`);
  }
  const pushed = deps.git.push(state.branchName ?? '');
  if (!pushed.ok) {
    throw new AdwError(`push failed: ${pushed.error}`);
  }

  if (!ghBin) {
    throw new AdwError('gh not found; cannot open or merge a PR (install gh or set GH_BIN)');
  }

  const prUrl = deps.git.prForBranch(state.branchName ?? '', ghBin, repo);
  if (prUrl) {
    state.prUrl = prUrl;
    state.prNumber = prNumberFromUrl(prUrl);
  } else {
    const title = (state.commitMessage ?? `Implement issue #${issue}`).split('\n')[0] ?? '';
    const body = state.prBody ?? `Closes #${issue}`;
    const created = deps.git.createPr(state.branchName ?? '', title, body, opts.base, ghBin, repo);
    if (created.error) {
      throw new AdwError(`failed to open PR: ${created.error}`);
    }
    state.prNumber = created.number;
    state.prUrl = created.url;
  }
  state.save();
  progress('finalize', `PR ready: ${state.prUrl}`);

  // CI watch + fix loop.
  if (state.prNumber !== null) {
    const ciOk = await ciFixLoop(
      state,
      state.prNumber,
      agent,
      {
        ghBin,
        repo,
        maxAttempts: opts.maxCiFix,
        pollIntervalMs: opts.ciPollIntervalMs,
        maxPolls: opts.ciMaxPolls,
        progress,
      },
      deps,
    );
    if (!ciOk) {
      throw new AdwError('CI is not green; refusing to merge');
    }
  }

  // Merge gate — confirmation; non-tty without --yes aborts.
  await confirmMerge({
    yes: assumeYes(opts.yes, deps.env),
    isatty: deps.isatty(),
    confirm: deps.confirm,
  });
  const merged = deps.git.squashMerge(state.prNumber ?? state.prUrl ?? '', ghBin, repo);
  if (!merged.ok) {
    throw new AdwError(`merge failed: ${merged.error}`);
  }
  deps.git.pullRebase(opts.base);
  state.markDone('merge');
  state.save();

  // Verify.
  if (opts.verify) {
    const st = deps.issueState(ghBin, issue, repo);
    if (st !== 'CLOSED') {
      throw new AdwError(`issue #${issue} is still ${st} after merge; treating as failure`);
    }
    progress('report', `verified: issue #${issue} is CLOSED`);
  }
  progress('report', `phased run ${state.adwId} complete`);
  return 0;
}

// --- plan rendering / entry ---------------------------------------------------------

function printPlan(issue: number, runner: AgentRunner, phases: readonly string[], opts: ResolvedOptions): void {
  const chain = ['setup(ts)', ...phases, 'finalize(ts)', 'ci-fix(ts)', 'merge(ts)', 'report(ts)'];
  console.log(`[dry-run] phased run for issue #${issue} via ${runner.id}`);
  console.log(`[dry-run] phases: ${chain.join(' -> ')}`);
  console.log(
    `[dry-run] agent env: GH_TOKEN withheld (allowGhToken=false)${opts.inheritEnv ? '; inherited (--inherit-env)' : ''}`,
  );
  console.log(`[dry-run] test gate: ${opts.testCmd || '(none configured)'}`);
}

/**
 * Mint a fresh run state or resume an existing one. --resume requires
 * --adw-id and loads the saved state (starting fresh, with a note, if none
 * is found). A bare --adw-id without --resume must not clobber existing
 * state. A resumed run is bound to its original issue and refuses a
 * mismatched number rather than retargeting the wrong issue onto the
 * existing branch.
 */
function resolveState(opts: ResolvedOptions, issue: number): { state: AdwState; resumed: boolean } {
  if (opts.resume && !opts.adwId) {
    throw new AdwError('--resume requires --adw-id <id>');
  }
  const existing = opts.adwId ? AdwState.load(opts.adwId) : null;
  let state: AdwState | null = null;
  if (opts.resume) {
    state = existing;
    if (state === null) {
      note(`no state for adw_id ${opts.adwId}; starting fresh`);
    }
  } else if (existing !== null) {
    throw new AdwError(`adw_id ${opts.adwId} already has saved state; pass --resume to continue it`);
  }
  const resumed = state !== null;
  if (state === null) {
    state = new AdwState({ adwId: opts.adwId || makeAdwId(), issueNumber: String(issue), base: opts.base });
  }
  if (resumed && state.issueNumber && state.issueNumber !== String(issue)) {
    throw new AdwError(`adw_id ${state.adwId} belongs to issue #${state.issueNumber}, not #${issue}`);
  }
  state.issueNumber = String(issue);
  state.save();
  return { state, resumed };
}

/** Tolerant reconstruction of persisted findings (mirrors the Python reader). */
function findingsFromState(state: AdwState): ReviewFinding[] {
  return state.reviewFindings.map((f) => ({
    severity: String(f['severity'] ?? 'skippable'),
    description: String(f['description'] ?? ''),
    location: String(f['location'] ?? ''),
  }));
}

/** Execute the phased pipeline for one issue through `runner`. */
export async function run(
  issue: number,
  runner: AgentRunner,
  options: RunOptions = {},
  depsOverride: Partial<OrchestratorDeps> = {},
): Promise<number> {
  const opts = resolveOptions(options);
  const deps: OrchestratorDeps = {
    ...defaultDeps(),
    ...depsOverride,
    git: { ...defaultDeps().git, ...(depsOverride.git ?? {}) },
  };

  const phases = parsePhases(opts.phases);

  if (opts.dryRun) {
    printPlan(issue, runner, phases, opts);
    return 0;
  }

  const ghBin = deps.resolveGhBin();
  const repo = opts.repo || deps.detectRepo(ghBin);

  // Preflight: skip already-closed issues; fail fast on unknown numbers.
  if (opts.verify || !opts.force) {
    if (!ghBin) {
      if (opts.verify) {
        throw new AdwError('gh not found but verification is on; install gh, set GH_BIN, or pass --no-verify');
      }
    } else {
      const st = deps.issueState(ghBin, issue, repo);
      if (st === 'CLOSED' && !opts.force) {
        note(`issue #${issue} is already CLOSED; skipping (use --force to run anyway)`);
        return 0;
      }
      if (st === 'UNKNOWN') {
        throw new AdwError(`issue #${issue} not found in ${repo || 'the current repo'} (is gh authenticated?)`);
      }
    }
  }

  // State: mint a fresh run or resume an existing one (rules in resolveState).
  const { state, resumed } = resolveState(opts, issue);
  state.engine = 'ts';
  state.runner = runner.id;
  state.save();
  note(`phased run id: ${state.adwId} (workspace: ${state.workspace()})`);

  // A resumed run legitimately carries the prior run's uncommitted edits (the
  // orchestrator only commits at finalize), so the clean-tree precondition
  // applies to fresh runs only.
  if (!opts.allowDirty && !resumed && deps.workingTreeDirty()) {
    throw new AdwError('working tree is dirty; commit/stash first or pass --allow-dirty');
  }

  const agentEnv = opts.inheritEnv
    ? definedEnv(deps.env)
    : safeSubprocessEnv({ allowGhToken: false, runner: runner.id, source: deps.env });

  const post = !opts.noProgress;
  const progress: ProgressFn = (phase, message) => {
    if (post) {
      deps.postProgress(ghBin, issue, repo, state.adwId, phase, message);
    }
  };

  progress('ops', `starting phased run ${state.adwId}`);

  // Issue context (fetched by the orchestrator; injected into token-less agent phases).
  const ctx = deps.fetchIssue(ghBin, issue, repo) ?? { title: '', body: '', labels: [] };

  if (!state.isDone('setup')) {
    setup(state, ghBin, repo, issue, ctx, opts.base, progress, deps);
    state.markDone('setup');
    state.save();
  }

  let files = deps.changedFiles(opts.base);
  let signal = [ctx.title, ctx.body, ctx.labels.join(' '), files.join(' ')].join(' ');

  const agent: AgentCtx = {
    runner,
    cliModel: opts.model,
    env: agentEnv,
    timeoutMs: opts.timeoutMs,
    ...(opts.maxBudgetUsd !== undefined ? { maxBudgetUsd: opts.maxBudgetUsd } : {}),
  };

  // Runner lifecycle (D6): start/stop are no-ops for the in-process backends;
  // opencode tears down its self-spawned server in stop(), so it runs in a
  // finally — a leaked server child would otherwise outlive the run.
  await runner.start?.();
  try {
    let reviewResult: ReviewResult | null = null;
    for (const phase of phases) {
      if (state.isDone(phase)) {
        note(`skipping ${phase} (already completed)`);
        continue;
      }

      if (CONDITIONAL_PHASES.has(phase)) {
        const { runIt, reason } = gateConditional(phase, signal, files);
        if (!runIt) {
          progress(phase, `skipped: ${reason}`);
          state.markDone(phase);
          state.save();
          continue;
        }
      }

      if (phase === 'resolve') {
        await resolveLoop(
          state,
          agent,
          { testCmd: opts.testCmd, maxAttempts: opts.maxResolve, progress },
          deps,
        );
        state.markDone(phase);
        state.save();
        continue;
      }

      if (phase === 'patch') {
        // On a resume the review phase is skipped, so reconstruct its findings
        // from persisted state rather than silently patching nothing.
        const findings = reviewResult !== null ? reviewResult.findings : findingsFromState(state);
        await patchLoop(state, findings, agent, { maxAttempts: opts.maxPatch, progress }, deps);
        state.markDone(phase);
        state.save();
        continue;
      }

      if (phase === 'classify' && deps.env['MX_AGENT_CLASSIFY_ON_RUNNER'] !== '1') {
        // D1: classify is the only pure structured phase; it runs on the shared
        // Anthropic-SDK structured call regardless of the selected runner.
        const prompt = composePhasePrompt(phase, phaseArgs(phase, issue, state, ctx, files), state, runner.id, false);
        const phaseDir = state.phaseDir(phase);
        writeFileSync(join(phaseDir, 'prompt.txt'), prompt, 'utf8');
        const { value, usage } = await deps.classify(prompt, {
          ...(opts.timeoutMs > 0 ? { signal: AbortSignal.timeout(opts.timeoutMs) } : {}),
        });
        writeFileSync(join(phaseDir, 'transcript.log'), `${JSON.stringify(value, null, 2)}\n`, 'utf8');
        recordUsage(state, usage);
        applyResult(state, phase, value);
        state.markDone(phase);
        state.save();
        progress(phase, 'done');
        continue;
      }

      // Normal agent phase (including classify when MX_AGENT_CLASSIFY_ON_RUNNER=1).
      const outcome = await deps.runAgentPhase({
        phase,
        templateArgs: phaseArgs(phase, issue, state, ctx, files),
        state,
        runner: agent.runner,
        cliModel: agent.cliModel,
        env: agent.env,
        timeoutMs: agent.timeoutMs,
        ...(agent.maxBudgetUsd !== undefined ? { maxBudgetUsd: agent.maxBudgetUsd } : {}),
      });
      recordUsage(state, outcome.usage);
      const result = outcome.data;
      applyResult(state, phase, result);
      if (phase === 'review' || phase === 'document') {
        absorbAuthoredText(state);
      }
      if (phase === 'review') {
        const review = result as ReviewResult;
        reviewResult = review;
        // Persist findings so a later --resume can still drive the patch phase.
        state.reviewFindings = review.findings.map((f) => ({
          severity: f.severity,
          description: f.description,
          location: f.location,
        }));
      }
      if (phase === 'implement') {
        const implemented = result as ImplementResult;
        files = implemented.files_changed.length > 0 ? implemented.files_changed : files;
        signal = `${signal} ${files.join(' ')}`;
      }
      state.markDone(phase);
      state.save();
      progress(phase, 'done');
    }

    return await finalizeAndMerge(state, opts, { ghBin, repo, issue, agent, progress }, deps);
  } finally {
    await runner.stop?.();
  }
}

/** Copy the parent env, dropping undefined values (inherit-env mode only). */
function definedEnv(env: Record<string, string | undefined>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(env)) {
    if (value !== undefined) {
      out[key] = value;
    }
  }
  return out;
}
