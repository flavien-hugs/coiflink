/**
 * Parity tests for the TS control plane (port of adw/test_orchestrator.py):
 * the runner, git, and gh layers are injected via OrchestratorDeps; no real
 * agent/git/gh/cargo runs. run() is driven end to end with the mock-runner
 * seam to assert phase ordering, gating, resume semantics, secret
 * withholding, and the merge gate.
 */

import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AdwError } from '../src/errors.js';
import type { AgentRunner } from '../src/invoker.js';
import {
  ciFixLoop,
  confirmMerge,
  finalizeGates,
  patchLoop,
  renderFindings,
  resolveLoop,
  run,
  truncate,
  type OrchestratorDeps,
} from '../src/orchestrator.js';
import { commitMessagePath, prBodyPath } from '../src/phases.js';
import { runAgentPhase } from '../src/run-phase.js';
import { createMockRunner } from '../src/runners/runner-mock.js';
import { AdwState, setAgentsDir } from '../src/state.js';

let tmp: string;

beforeEach(() => {
  tmp = mkdtempSync(join(tmpdir(), 'adw-orch-'));
  setAgentsDir(tmp);
});

afterEach(() => {
  setAgentsDir(null);
  rmSync(tmp, { recursive: true, force: true });
});

const noop = () => {};

type DepsOverride = Partial<Omit<OrchestratorDeps, 'git'>> & { git?: Partial<OrchestratorDeps['git']> };

/** Full deps with inert stubs; tests override the seams they exercise. */
function testDeps(overrides: DepsOverride = {}): OrchestratorDeps {
  const base: OrchestratorDeps = {
    env: { PATH: '/bin' },
    isatty: () => false,
    confirm: async () => false,
    sleep: async () => {},
    runCmd: () => ({ rc: 0, output: '' }),
    capture: () => ({ returncode: 0, stdout: '', stderr: '' }),
    workingTreeDirty: () => false,
    changedFiles: () => ['src/lib.rs'],
    resolveGhBin: () => '/bin/gh',
    detectRepo: () => 'o/r',
    issueState: () => 'OPEN',
    postProgress: noop,
    fetchIssue: () => ({ title: 'T', body: 'B', labels: [] }),
    setStatus: noop,
    git: {
      createOrCheckoutBranch: () => ({ ok: true, error: null }),
      commitAll: () => ({ ok: true, error: null }),
      push: () => ({ ok: true, error: null }),
      pullRebase: () => ({ ok: true, error: null }),
      prForBranch: () => null,
      createPr: () => ({ number: 42, url: 'https://x/pull/42', error: null }),
      ciStatus: () => ({ state: 'success', failingJobs: [] }),
      squashMerge: () => ({ ok: true, error: null }),
    },
    runAgentPhase: (async () => {
      throw new Error('runAgentPhase not stubbed for this test');
    }) as typeof runAgentPhase,
    classify: async () => ({ value: { issue_class: 'feat', reason: 'r' }, usage: {} }),
  };
  return {
    ...base,
    ...overrides,
    git: { ...base.git, ...(overrides.git ?? {}) },
  };
}

/** A scripted runAgentPhase stub returning per-phase canned results. */
function agentStub(
  results: Record<string, unknown>,
  onCall?: (opts: Parameters<typeof runAgentPhase>[0]) => void,
): typeof runAgentPhase {
  return (async (opts: Parameters<typeof runAgentPhase>[0]) => {
    onCall?.(opts);
    const data = results[opts.phase];
    if (data === undefined) {
      throw new Error(`unexpected phase: ${opts.phase}`);
    }
    return { data, usage: {} };
  }) as typeof runAgentPhase;
}

function agentCtx(runner: AgentRunner) {
  return { runner, cliModel: '', env: { PATH: '/bin' }, timeoutMs: 0 };
}

const state5 = () => new AdwState({ adwId: 'a1b2c3d4' });

describe('truncate', () => {
  it('keeps short text unchanged', () => {
    expect(truncate('abc', 10)).toBe('abc');
  });

  it('keeps the tail of long text and marks the cut', () => {
    const out = truncate('x'.repeat(100), 10);
    expect(out.endsWith('x'.repeat(10))).toBe(true);
    expect(out).toContain('truncated');
  });
});

describe('confirmMerge', () => {
  it('passes with --yes', async () => {
    await confirmMerge({ yes: true, isatty: false, confirm: async () => false });
  });

  it('aborts unattended without --yes', async () => {
    await expect(confirmMerge({ yes: false, isatty: false, confirm: async () => true })).rejects.toThrow(
      AdwError,
    );
  });

  it('honors an interactive yes/no', async () => {
    await confirmMerge({ yes: false, isatty: true, confirm: async () => true });
    await expect(confirmMerge({ yes: false, isatty: true, confirm: async () => false })).rejects.toThrow(
      AdwError,
    );
  });
});

describe('finalizeGates', () => {
  it('puts the test gate first, then the extra gates', () => {
    const gates = finalizeGates('pytest -q', ['lint', 'build']);
    expect(gates).toEqual(['pytest -q', 'lint', 'build']);
  });

  it('contributes no test gate when the test command is empty', () => {
    expect(finalizeGates('')).toEqual([]);
    expect(finalizeGates('', ['check'])).toEqual(['check']);
  });
});

describe('renderFindings', () => {
  it('renders numbered severity-tagged lines with optional locations', () => {
    const text = renderFindings([
      { severity: 'blocker', description: 'bug', location: 'a.rs:1' },
      { severity: 'tech_debt', description: 'later', location: '' },
    ]);
    expect(text).toBe('1. [blocker] (a.rs:1) bug\n2. [tech_debt] later');
  });
});

describe('resolveLoop', () => {
  it('skips the gate entirely when testCmd is empty', async () => {
    const runCmd = vi.fn(() => ({ rc: 1, output: 'should not be called' }));
    const deps = testDeps({ runCmd });
    const ok = await resolveLoop(
      state5(),
      agentCtx(createMockRunner()),
      { testCmd: '', maxAttempts: 3, progress: noop },
      deps,
    );
    expect(ok).toBe(true);
    expect(runCmd).not.toHaveBeenCalled();
  });

  it('skips the gate when testCmd is whitespace-only', async () => {
    const runCmd = vi.fn(() => ({ rc: 1, output: 'should not be called' }));
    const deps = testDeps({ runCmd });
    const ok = await resolveLoop(
      state5(),
      agentCtx(createMockRunner()),
      { testCmd: '   ', maxAttempts: 3, progress: noop },
      deps,
    );
    expect(ok).toBe(true);
    expect(runCmd).not.toHaveBeenCalled();
  });

  it('splits testCmd into argv before passing to runCmd (no shell expansion)', async () => {
    const capturedArgv: Array<readonly string[]> = [];
    const runCmd = vi.fn((cmd: readonly string[]) => {
      capturedArgv.push(cmd);
      return { rc: 0, output: '' };
    });
    const deps = testDeps({ runCmd });
    await resolveLoop(
      state5(),
      agentCtx(createMockRunner()),
      { testCmd: 'bash ../scripts/test-gate.sh', maxAttempts: 3, progress: noop },
      deps,
    );
    expect(capturedArgv[0]).toEqual(['bash', '../scripts/test-gate.sh']);
  });

  it('returns immediately when the gate is green', async () => {
    const runCmd = vi.fn(() => ({ rc: 0, output: '' }));
    const agent = vi.fn();
    const deps = testDeps({ runCmd, runAgentPhase: agent as unknown as typeof runAgentPhase });
    const ok = await resolveLoop(
      state5(),
      agentCtx(createMockRunner()),
      { testCmd: 'cargo test', maxAttempts: 3, progress: noop },
      deps,
    );
    expect(ok).toBe(true);
    expect(agent).not.toHaveBeenCalled();
    expect(runCmd).toHaveBeenCalledTimes(1);
  });

  it('fixes then goes green', async () => {
    const runCmd = vi
      .fn()
      .mockReturnValueOnce({ rc: 1, output: 'fail' })
      .mockReturnValueOnce({ rc: 0, output: '' });
    const calls: string[] = [];
    const deps = testDeps({
      runCmd,
      runAgentPhase: agentStub({ resolve: { resolved: 1, remaining: 0, summary: '' } }, (o) =>
        calls.push(o.phase),
      ),
    });
    const ok = await resolveLoop(
      state5(),
      agentCtx(createMockRunner()),
      { testCmd: 'cargo test', maxAttempts: 3, progress: noop },
      deps,
    );
    expect(ok).toBe(true);
    expect(calls).toEqual(['resolve']);
  });

  it('stops when the agent makes no progress', async () => {
    const deps = testDeps({
      runCmd: () => ({ rc: 1, output: 'fail' }),
      runAgentPhase: agentStub({ resolve: { resolved: 0, remaining: 2, summary: '' } }),
    });
    const ok = await resolveLoop(
      state5(),
      agentCtx(createMockRunner()),
      { testCmd: 'cargo test', maxAttempts: 3, progress: noop },
      deps,
    );
    expect(ok).toBe(false);
  });

  it('caps attempts (initial gate + one per resolve)', async () => {
    const runCmd = vi.fn(() => ({ rc: 1, output: 'fail' }));
    let agentCalls = 0;
    const deps = testDeps({
      runCmd,
      runAgentPhase: agentStub({ resolve: { resolved: 1, remaining: 1, summary: '' } }, () => {
        agentCalls += 1;
      }),
    });
    const ok = await resolveLoop(
      state5(),
      agentCtx(createMockRunner()),
      { testCmd: 'cargo test', maxAttempts: 2, progress: noop },
      deps,
    );
    expect(ok).toBe(false);
    expect(agentCalls).toBe(2);
    expect(runCmd).toHaveBeenCalledTimes(3); // initial + after each resolve
  });

  it('passes the truncated gate failure output to the resolve agent as templateArgs', async () => {
    const runCmd = vi
      .fn()
      .mockReturnValueOnce({ rc: 1, output: 'gate failure details' })
      .mockReturnValueOnce({ rc: 0, output: '' });
    const capturedTemplateArgs: Array<readonly string[]> = [];
    const deps = testDeps({
      runCmd,
      runAgentPhase: agentStub({ resolve: { resolved: 1, remaining: 0, summary: '' } }, (o) => {
        capturedTemplateArgs.push(o.templateArgs);
      }),
    });
    const ok = await resolveLoop(
      state5(),
      agentCtx(createMockRunner()),
      { testCmd: 'cargo test', maxAttempts: 3, progress: noop },
      deps,
    );
    expect(ok).toBe(true);
    // The agent must receive the gate output so it can diagnose and fix the failure.
    expect(capturedTemplateArgs).toHaveLength(1);
    expect(capturedTemplateArgs[0]![0]).toContain('gate failure details');
  });
});

describe('patchLoop', () => {
  it('skips when there are no blockers', async () => {
    const agent = vi.fn();
    const deps = testDeps({ runAgentPhase: agent as unknown as typeof runAgentPhase });
    const ok = await patchLoop(
      state5(),
      [
        { severity: 'skippable', description: 'nit', location: '' },
        { severity: 'tech_debt', description: 'later', location: '' },
      ],
      agentCtx(createMockRunner()),
      { maxAttempts: 2, progress: noop },
      deps,
    );
    expect(ok).toBe(true);
    expect(agent).not.toHaveBeenCalled();
  });

  it('resolves blockers', async () => {
    let calls = 0;
    const deps = testDeps({
      runAgentPhase: agentStub({ patch: { resolved: 1, remaining: 0, summary: '' } }, () => {
        calls += 1;
      }),
    });
    const ok = await patchLoop(
      state5(),
      [{ severity: 'blocker', description: 'bug', location: '' }],
      agentCtx(createMockRunner()),
      { maxAttempts: 2, progress: noop },
      deps,
    );
    expect(ok).toBe(true);
    expect(calls).toBe(1);
  });

  it('breaks on no progress', async () => {
    const deps = testDeps({
      runAgentPhase: agentStub({ patch: { resolved: 0, remaining: 1, summary: '' } }),
    });
    const ok = await patchLoop(
      state5(),
      [{ severity: 'blocker', description: 'bug', location: '' }],
      agentCtx(createMockRunner()),
      { maxAttempts: 3, progress: noop },
      deps,
    );
    expect(ok).toBe(false);
  });
});

describe('ciFixLoop', () => {
  const cfg = { ghBin: '/bin/gh', repo: 'o/r', maxAttempts: 2, pollIntervalMs: 0, maxPolls: 3, progress: noop };
  const st = () => new AdwState({ adwId: 'a1b2c3d4', branchName: 'feat/5-x' });

  it('returns true immediately on success', async () => {
    const deps = testDeps({ git: { ciStatus: () => ({ state: 'success', failingJobs: [] }) } });
    expect(await ciFixLoop(st(), 7, agentCtx(createMockRunner()), cfg, deps)).toBe(true);
  });

  it('returns false on unknown', async () => {
    const deps = testDeps({ git: { ciStatus: () => ({ state: 'unknown', failingJobs: [] }) } });
    expect(await ciFixLoop(st(), 7, agentCtx(createMockRunner()), cfg, deps)).toBe(false);
  });

  it('settles a persistent empty rollup to success', async () => {
    const ciStatus = vi.fn(() => ({ state: 'none' as const, failingJobs: [] }));
    const deps = testDeps({ git: { ciStatus } });
    expect(await ciFixLoop(st(), 7, agentCtx(createMockRunner()), cfg, deps)).toBe(true);
    expect(ciStatus.mock.calls.length).toBeGreaterThan(3); // settled, not instant
  });

  it('exhausts the poll budget on persistent pending', async () => {
    const deps = testDeps({ git: { ciStatus: () => ({ state: 'pending', failingJobs: [] }) } });
    expect(await ciFixLoop(st(), 7, agentCtx(createMockRunner()), cfg, deps)).toBe(false);
  });

  it('fixes a red check, commits, pushes, and goes green', async () => {
    const ciStatus = vi
      .fn()
      .mockReturnValueOnce({ state: 'failure', failingJobs: [{ name: 'ci', logExcerpt: '' }] })
      .mockReturnValueOnce({ state: 'success', failingJobs: [] });
    const commitAll = vi.fn(() => ({ ok: true, error: null }));
    const push = vi.fn(() => ({ ok: true, error: null }));
    const deps = testDeps({
      workingTreeDirty: () => true,
      git: { ciStatus, commitAll, push },
      runAgentPhase: agentStub({ resolve: { resolved: 1, remaining: 0, summary: '' } }),
    });
    expect(await ciFixLoop(st(), 7, agentCtx(createMockRunner()), cfg, deps)).toBe(true);
    expect(commitAll).toHaveBeenCalledWith('fix: address CI failures (ci)');
    expect(push).toHaveBeenCalledWith('feat/5-x');
  });

  it('stops when the agent claims a fix but changed nothing', async () => {
    const deps = testDeps({
      workingTreeDirty: () => false,
      git: { ciStatus: () => ({ state: 'failure', failingJobs: [{ name: 'ci', logExcerpt: '' }] }) },
      runAgentPhase: agentStub({ resolve: { resolved: 1, remaining: 0, summary: '' } }),
    });
    expect(await ciFixLoop(st(), 7, agentCtx(createMockRunner()), cfg, deps)).toBe(false);
  });
});

describe('run() integration', () => {
  const PHASE_RESULTS: Record<string, unknown> = {
    plan: { plan_file: 'specs/x.md', spec_created: true, summary: '' },
    implement: { summary: 'did it', files_changed: ['src/lib.rs'] },
    tests: { tests_added: true, summary: '' },
    review: { findings: [], wrote_commit_message: true, wrote_pr_body: true },
  };

  function loadedId(): string {
    const ids = readdirSync(tmp, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => e.name);
    expect(ids).toHaveLength(1);
    return ids[0]!;
  }

  it('runs phases in order, withholds GH_TOKEN, absorbs artifacts, and merges', async () => {
    const order: string[] = [];
    const poisoned = { GH_TOKEN: 'ghp_secret', PATH: '/bin', MATRIX_TOKEN: 'x', MX_AGENT_FOO: 'x' };
    const issueStates = vi.fn().mockReturnValueOnce('OPEN').mockReturnValueOnce('CLOSED');
    const classify = vi.fn(async (prompt: string) => {
      order.push('classify');
      expect(prompt).toContain('GitHub issue #5');
      return { value: { issue_class: 'feat' as const, reason: 'r' }, usage: { costUsd: 0.01 } };
    });
    const deps = testDeps({
      env: poisoned,
      issueState: issueStates,
      fetchIssue: () => ({ title: 'T', body: 'B', labels: ['type:feature'] }),
      classify,
      runAgentPhase: agentStub(PHASE_RESULTS, (opts) => {
        order.push(opts.phase);
        // The phased agent env must never carry GH_TOKEN or denied prefixes.
        expect(opts.env).not.toHaveProperty('GH_TOKEN');
        expect(Object.keys(opts.env).some((k) => k.startsWith('MATRIX_') || k.startsWith('MX_AGENT_'))).toBe(
          false,
        );
        if (opts.phase === 'review') {
          // Simulate the agent authoring commit/PR text to workspace files.
          mkdirSync(opts.state.workspace(), { recursive: true });
          writeFileSync(commitMessagePath(opts.state), 'feat: phased pipeline\n\ncloses #5', 'utf8');
          writeFileSync(prBodyPath(opts.state), 'Closes #5\n\nImplements the thing.', 'utf8');
        }
      }),
    });

    const rc = await run(5, createMockRunner(), { yes: true, noProgress: true }, deps);
    expect(rc).toBe(0);
    // e2e and document are gated off for an internal feature touching src/lib.rs.
    expect(order).toEqual(['classify', 'plan', 'implement', 'tests', 'review']);

    const state = AdwState.load(loadedId());
    expect(state).not.toBeNull();
    expect(state?.completedPhases).toContain('merge');
    // The agent-authored commit message (artifact file) was absorbed into state.
    expect(state?.commitMessage).toBe('feat: phased pipeline\n\ncloses #5');
    expect(state?.prBody ?? '').toContain('Implements the thing.');
    // TS-additive observability fields are recorded.
    expect(state?.engine).toBe('ts');
    expect(state?.runner).toBe('claude');
    expect(state?.totalCostUsd).toBeCloseTo(0.01);
  });

  it('calls runner.start before the phases and runner.stop in a finally, even when a phase throws (D6 lifecycle)', async () => {
    const calls: string[] = [];
    const lifecycleRunner = (): AgentRunner => ({
      ...createMockRunner(),
      start: async () => {
        calls.push('start');
      },
      stop: async () => {
        calls.push('stop');
      },
    });

    const okDeps = testDeps({
      issueState: vi.fn().mockReturnValueOnce('OPEN').mockReturnValueOnce('CLOSED'),
      runAgentPhase: agentStub(PHASE_RESULTS, () => {}),
    });
    await run(5, lifecycleRunner(), { yes: true, noProgress: true }, okDeps);
    expect(calls).toEqual(['start', 'stop']);

    calls.length = 0;
    const failingDeps = testDeps({
      issueState: vi.fn().mockReturnValue('OPEN'),
      runAgentPhase: (() => {
        throw new AdwError('phase exploded');
      }) as unknown as typeof runAgentPhase,
    });
    await expect(run(6, lifecycleRunner(), { yes: true, noProgress: true }, failingDeps)).rejects.toThrow(
      'phase exploded',
    );
    expect(calls).toEqual(['start', 'stop']);
  });

  it('resumes by skipping completed phases', async () => {
    const pre = new AdwState({ adwId: 'a1b2c3d4', issueNumber: '5', branchName: 'feat/5-x' });
    for (const ph of ['setup', 'classify', 'plan', 'implement', 'tests', 'resolve', 'e2e', 'review', 'patch', 'document']) {
      pre.markDone(ph);
    }
    pre.commitMessage = 'feat: x\n\ncloses #5';
    pre.prNumber = 42;
    pre.save();

    const deps = testDeps({
      issueState: vi.fn().mockReturnValueOnce('OPEN').mockReturnValueOnce('CLOSED'),
      git: { prForBranch: () => 'https://x/pull/42' },
      classify: async () => {
        throw new Error('no phase should run on resume');
      },
    });
    const rc = await run(5, createMockRunner(), { adwId: 'a1b2c3d4', resume: true, yes: true, noProgress: true }, deps);
    expect(rc).toBe(0);
  });

  it('short-circuits finalize after a recorded merge (no re-merge, no commit)', async () => {
    const pre = new AdwState({ adwId: 'a1b2c3d4', issueNumber: '5', branchName: 'feat/5-x' });
    for (const ph of ['setup', 'classify', 'plan', 'implement', 'tests', 'resolve', 'e2e', 'review', 'patch', 'document', 'merge']) {
      pre.markDone(ph);
    }
    pre.prNumber = 42;
    pre.save();

    const squashMerge = vi.fn(() => ({ ok: true, error: null }));
    const commitAll = vi.fn(() => ({ ok: true, error: null }));
    const deps = testDeps({
      // OPEN at preflight (so the run proceeds), CLOSED at the re-verify.
      issueState: vi.fn().mockReturnValueOnce('OPEN').mockReturnValue('CLOSED'),
      git: { squashMerge, commitAll },
    });
    const rc = await run(5, createMockRunner(), { adwId: 'a1b2c3d4', resume: true, yes: true, noProgress: true }, deps);
    expect(rc).toBe(0);
    expect(squashMerge).not.toHaveBeenCalled();
    expect(commitAll).not.toHaveBeenCalled();
  });

  it('requires --adw-id with --resume', async () => {
    await expect(run(5, createMockRunner(), { resume: true, yes: true, noProgress: true }, testDeps())).rejects.toThrow(
      /--resume requires --adw-id/,
    );
  });

  it('refuses a bare --adw-id that would clobber existing state', async () => {
    new AdwState({ adwId: 'a1b2c3d4', issueNumber: '5' }).save();
    await expect(
      run(5, createMockRunner(), { adwId: 'a1b2c3d4', yes: true, noProgress: true }, testDeps()),
    ).rejects.toThrow(/already has saved state/);
  });

  it('rejects resuming a run that belongs to a different issue', async () => {
    const pre = new AdwState({ adwId: 'a1b2c3d4', issueNumber: '5' });
    pre.markDone('setup');
    pre.save();
    await expect(
      run(9, createMockRunner(), { adwId: 'a1b2c3d4', resume: true, yes: true, noProgress: true }, testDeps()),
    ).rejects.toThrow(/belongs to issue #5/);
  });

  it('rejects a dirty tree on a fresh run but tolerates it on resume', async () => {
    const deps = testDeps({ workingTreeDirty: () => true });
    await expect(run(5, createMockRunner(), { yes: true, noProgress: true }, deps)).rejects.toThrow(
      /working tree is dirty/,
    );
  });

  it('recovers persisted review findings for the patch phase on resume', async () => {
    // review done with a persisted blocker, patch NOT done -> on resume the
    // patch phase must still see the blocker (regression: findings were lost).
    const pre = new AdwState({ adwId: 'a1b2c3d4', issueNumber: '5', branchName: 'feat/5-x' });
    for (const ph of ['setup', 'classify', 'plan', 'implement', 'tests', 'resolve', 'e2e', 'review']) {
      pre.markDone(ph);
    }
    pre.reviewFindings = [{ severity: 'blocker', description: 'bug', location: 'a.rs:1' }];
    pre.commitMessage = 'feat: x\n\ncloses #5';
    pre.prNumber = 42;
    pre.save();

    const patchPrompts: string[] = [];
    const deps = testDeps({
      issueState: vi.fn().mockReturnValueOnce('OPEN').mockReturnValueOnce('CLOSED'),
      git: { prForBranch: () => 'https://x/pull/42' },
      runAgentPhase: agentStub(
        {
          patch: { resolved: 1, remaining: 0, summary: '' },
          document: { docs_updated: false, files: [], summary: '', wrote_commit_message: false, wrote_pr_body: false },
        },
        (opts) => {
          if (opts.phase === 'patch') {
            patchPrompts.push(String(opts.templateArgs[0]));
          }
        },
      ),
    });
    const rc = await run(5, createMockRunner(), { adwId: 'a1b2c3d4', resume: true, yes: true, noProgress: true }, deps);
    expect(rc).toBe(0);
    expect(patchPrompts).toHaveLength(1);
    expect(patchPrompts[0]).toContain('[blocker] (a.rs:1) bug');
  });

  it('tolerates additive/junk finding entries from a foreign writer', async () => {
    // state.json is the cross-language contract: finding objects may carry
    // additive keys, omit optional ones, or be junk. Resume must coerce,
    // never crash — write the document by hand to include a non-dict entry.
    const ws = join(tmp, 'a1b2c3d4');
    mkdirSync(ws, { recursive: true });
    writeFileSync(
      join(ws, 'state.json'),
      JSON.stringify({
        adw_id: 'a1b2c3d4',
        schema_version: 1,
        issue_number: '5',
        branch_name: 'feat/5-x',
        base: 'main',
        commit_message: 'feat: x\n\ncloses #5',
        pr_number: 42,
        review_findings: [
          { severity: 'blocker', description: 'bug', location: 'a.rs:1', file: 'a.rs' },
          { description: 'no severity recorded' },
          'not-a-dict',
        ],
        completed_phases: ['setup', 'classify', 'plan', 'implement', 'tests', 'resolve', 'e2e', 'review'],
      }),
      'utf8',
    );

    const patchPrompts: string[] = [];
    const deps = testDeps({
      issueState: vi.fn().mockReturnValueOnce('OPEN').mockReturnValueOnce('CLOSED'),
      git: { prForBranch: () => 'https://x/pull/42' },
      runAgentPhase: agentStub(
        {
          patch: { resolved: 1, remaining: 0, summary: '' },
          document: { docs_updated: false, files: [], summary: '', wrote_commit_message: false, wrote_pr_body: false },
        },
        (opts) => {
          if (opts.phase === 'patch') {
            patchPrompts.push(String(opts.templateArgs[0]));
          }
        },
      ),
    });
    const rc = await run(5, createMockRunner(), { adwId: 'a1b2c3d4', resume: true, yes: true, noProgress: true }, deps);
    expect(rc).toBe(0);
    // The blocker (additive key ignored) is patched; the severity-less
    // finding coerces to skippable; the non-dict entry is dropped.
    expect(patchPrompts).toHaveLength(1);
    expect(patchPrompts[0]).toContain('[blocker] (a.rs:1) bug');
    expect(patchPrompts[0]).not.toContain('no severity recorded');
  });

  it('refuses to merge when CI cannot go green', async () => {
    const deps = testDeps({
      issueState: vi.fn().mockReturnValue('OPEN'),
      classify: async () => ({ value: { issue_class: 'feat', reason: 'r' }, usage: {} }),
      runAgentPhase: agentStub(PHASE_RESULTS),
      git: { ciStatus: () => ({ state: 'unknown', failingJobs: [] }) },
    });
    await expect(run(5, createMockRunner(), { yes: true, noProgress: true }, deps)).rejects.toThrow(
      /CI is not green/,
    );
  });

  it('aborts before merge when a finalize gate fails', async () => {
    // Extra (non-test) pre-merge gates are configured via MX_AGENT_FINALIZE_GATES
    // in the standalone port; one that returns non-zero must block the merge.
    process.env['MX_AGENT_FINALIZE_GATES'] = 'check:fmt';
    try {
      const runCmd = vi.fn((cmd: readonly string[]) =>
        cmd.join(' ') === 'check:fmt' ? { rc: 1, output: 'fmt diff' } : { rc: 0, output: '' },
      );
      const squashMerge = vi.fn(() => ({ ok: true, error: null }));
      const deps = testDeps({
        issueState: vi.fn().mockReturnValue('OPEN'),
        runCmd,
        git: { squashMerge },
        runAgentPhase: agentStub(PHASE_RESULTS),
      });
      await expect(run(5, createMockRunner(), { yes: true, noProgress: true }, deps)).rejects.toThrow(
        /pre-merge gate failed: check:fmt/,
      );
      expect(squashMerge).not.toHaveBeenCalled();
    } finally {
      delete process.env['MX_AGENT_FINALIZE_GATES'];
    }
  });

  it('filters blank and whitespace-only lines from MX_AGENT_FINALIZE_GATES before running gates', async () => {
    // Ensures that "\ncheck:fmt\n  \n" produces exactly one gate call ('check:fmt')
    // and does not attempt to run empty-string commands via spawnSync.
    process.env['MX_AGENT_FINALIZE_GATES'] = '\ncheck:fmt\n  \n';
    try {
      const gateCalls: Array<string> = [];
      const runCmd = vi.fn((cmd: readonly string[]) => {
        gateCalls.push(cmd.join(' '));
        return { rc: 0, output: '' };
      });
      const issueStates = vi.fn().mockReturnValueOnce('OPEN').mockReturnValueOnce('CLOSED');
      const deps = testDeps({
        runCmd,
        issueState: issueStates,
        runAgentPhase: agentStub(PHASE_RESULTS, (opts) => {
          if (opts.phase === 'review') {
            mkdirSync(opts.state.workspace(), { recursive: true });
            writeFileSync(commitMessagePath(opts.state), 'feat: x\n\ncloses #5', 'utf8');
            writeFileSync(prBodyPath(opts.state), 'Closes #5', 'utf8');
          }
        }),
      });
      const rc = await run(5, createMockRunner(), { yes: true, noProgress: true }, deps);
      expect(rc).toBe(0);
      // Only 'check:fmt' must appear as a gate — blank lines must never become commands.
      expect(gateCalls).toContain('check:fmt');
      expect(gateCalls.some((c) => c.trim() === '')).toBe(false);
    } finally {
      delete process.env['MX_AGENT_FINALIZE_GATES'];
    }
  });

  it('persists classify prompt.txt and transcript.log on the structured-call path', async () => {
    const deps = testDeps({
      issueState: vi.fn().mockReturnValueOnce('OPEN').mockReturnValueOnce('CLOSED'),
      runAgentPhase: agentStub(PHASE_RESULTS),
    });
    await run(5, createMockRunner(), { yes: true, noProgress: true }, deps);
    const dir = join(tmp, loadedId(), 'classify');
    expect(readFileSync(join(dir, 'prompt.txt'), 'utf8')).toContain('GitHub issue #5');
    expect(JSON.parse(readFileSync(join(dir, 'transcript.log'), 'utf8'))).toEqual({
      issue_class: 'feat',
      reason: 'r',
    });
  });

  it('routes classify through the runner when MX_AGENT_CLASSIFY_ON_RUNNER=1', async () => {
    const order: string[] = [];
    const classify = vi.fn(async () => ({ value: { issue_class: 'feat' as const, reason: 'r' }, usage: {} }));
    const deps = testDeps({
      env: { PATH: '/bin', MX_AGENT_CLASSIFY_ON_RUNNER: '1' },
      issueState: vi.fn().mockReturnValueOnce('OPEN').mockReturnValueOnce('CLOSED'),
      classify,
      runAgentPhase: agentStub(
        { ...PHASE_RESULTS, classify: { issue_class: 'feat', reason: 'r' } },
        (opts) => order.push(opts.phase),
      ),
    });
    const rc = await run(5, createMockRunner(), { yes: true, noProgress: true }, deps);
    expect(rc).toBe(0);
    expect(classify).not.toHaveBeenCalled();
    expect(order).toEqual(['classify', 'plan', 'implement', 'tests', 'review']);
    expect(AdwState.load(loadedId())?.issueClass).toBe('feat');
  });

  it('inheritEnv is an explicit opt-out that forwards the full parent env (Python --inherit-env parity)', async () => {
    const poisoned = { GH_TOKEN: 'ghp_secret', PATH: '/bin', MX_AGENT_FOO: 'x' };
    const seenEnvs: Array<Record<string, string>> = [];
    const deps = testDeps({
      env: poisoned,
      issueState: vi.fn().mockReturnValueOnce('OPEN').mockReturnValueOnce('CLOSED'),
      runAgentPhase: agentStub(PHASE_RESULTS, (opts) => seenEnvs.push(opts.env)),
    });
    const rc = await run(5, createMockRunner(), { yes: true, noProgress: true, inheritEnv: true }, deps);
    expect(rc).toBe(0);
    // Opt-OUT: the documented less-isolated mode forwards everything…
    expect(seenEnvs[0]).toEqual(poisoned);
    // …and remains strictly opt-in: the same run without the flag is covered
    // by the 'runs phases in order' test, which asserts GH_TOKEN is absent.
  });

  it('poisons total_cost_usd to null once any phase cost is unknown', async () => {
    const costs: Array<number | null | undefined> = [0.02, null, 0.01, undefined];
    let call = 0;
    const deps = testDeps({
      issueState: vi.fn().mockReturnValueOnce('OPEN').mockReturnValueOnce('CLOSED'),
      classify: async () => ({ value: { issue_class: 'feat', reason: 'r' }, usage: { costUsd: 0.05 } }),
      runAgentPhase: (async (opts: Parameters<typeof runAgentPhase>[0]) => ({
        data: PHASE_RESULTS[opts.phase],
        usage: { costUsd: costs[call++ % costs.length] },
      })) as typeof runAgentPhase,
    });
    const rc = await run(5, createMockRunner(), { yes: true, noProgress: true }, deps);
    expect(rc).toBe(0);
    // 0.05 (classify) + 0.02 (plan) accumulate, then null (implement) poisons
    // the total for good — never a false partial sum.
    expect(AdwState.load(loadedId())?.totalCostUsd).toBeNull();
  });

  it('runs testCmd during resolveLoop AND during finalizeAndMerge — two gate executions per run', async () => {
    // Issue #6 criterion: the test gate must fire at two points in a full run:
    //   1. resolveLoop (resolve phase) — before opening a PR
    //   2. finalizeAndMerge — as a pre-merge gate, after all agent phases
    // This test verifies both calls carry the correctly argv-split command.
    const gateCalls: Array<readonly string[]> = [];
    const runCmd = vi.fn((cmd: readonly string[]) => {
      if (cmd[0] === 'bash') {
        gateCalls.push(cmd);
      }
      return { rc: 0, output: '' };
    });
    const issueStates = vi.fn().mockReturnValueOnce('OPEN').mockReturnValueOnce('CLOSED');
    const deps = testDeps({
      runCmd,
      issueState: issueStates,
      runAgentPhase: agentStub(PHASE_RESULTS, (opts) => {
        if (opts.phase === 'review') {
          mkdirSync(opts.state.workspace(), { recursive: true });
          writeFileSync(commitMessagePath(opts.state), 'feat: x\n\ncloses #5', 'utf8');
          writeFileSync(prBodyPath(opts.state), 'Closes #5', 'utf8');
        }
      }),
    });
    const rc = await run(5, createMockRunner(), {
      testCmd: 'bash ../scripts/test-gate.sh',
      yes: true,
      noProgress: true,
    }, deps);
    expect(rc).toBe(0);
    // resolveLoop fires once; finalizeAndMerge fires once → minimum 2 gate calls.
    expect(gateCalls.length).toBeGreaterThanOrEqual(2);
    // Every call must be the correctly-split argv (not a raw shell string).
    for (const call of gateCalls) {
      expect(call).toEqual(['bash', '../scripts/test-gate.sh']);
    }
  });

  it('previews the plan under dry-run without touching anything', async () => {
    const log = vi.spyOn(console, 'log').mockImplementation(() => {});
    const resolveGhBin = vi.fn(() => '/bin/gh');
    const rc = await run(5, createMockRunner(), { dryRun: true }, testDeps({ resolveGhBin }));
    expect(rc).toBe(0);
    expect(resolveGhBin).not.toHaveBeenCalled();
    expect(log.mock.calls.flat().join('\n')).toContain('GH_TOKEN withheld');
    expect(readdirSync(tmp)).toEqual([]); // no workspace minted
  });
});
