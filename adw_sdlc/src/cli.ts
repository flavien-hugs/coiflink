#!/usr/bin/env node
/**
 * The /issue entry point that wires MX_AGENT_ENGINE + MX_AGENT_RUNNER
 * selection (PLAN.md roadmap step 10, D4).
 *
 * `MX_AGENT_ENGINE={py|ts}` (default `ts` in this standalone port, flag
 * `--engine`) picks which language drives the run, orthogonal to the runner
 * choice:
 *
 * - `py` — delegate to the unchanged Python pipeline: spawn
 *   `python3 adw/issue.py` with this CLI's argv forwarded verbatim (minus
 *   `--engine`) and the FULL parent env. The py engine parses its own flags,
 *   applies its own runner validation (pi|claude), and builds its own secret
 *   boundary (adw/_exec.py safe_subprocess_env), exactly as a direct
 *   invocation would.
 * - `ts` — parse the phased flags (mirroring adw/issue.py build_parser),
 *   resolve `--runner`/`MX_AGENT_RUNNER` over the four-runner registry, and
 *   bind the loaded adapter into `orchestrator.run()`.
 *
 * Unknown engine or runner values throw, mirroring the Python validation at
 * adw/_orchestrator.py:557-559 — fail loud, never guess.
 */

import { spawn } from 'node:child_process';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

import { REPO_ROOT } from './common.js';
import { AdwError } from './errors.js';
import { note } from './exec.js';
import type { AgentRunner, RunnerId } from './invoker.js';
import { run, type RunOptions } from './orchestrator.js';
import { loadRunner, resolveRunnerId } from './registry.js';

// --- engine selection ---------------------------------------------------------

export const ENGINE_IDS = ['py', 'ts'] as const;
export type EngineId = (typeof ENGINE_IDS)[number];

/**
 * Standalone port: the cutover (PLAN.md roadmap step 12) is done —
 * `ts` is the default. The `py` engine is still selectable via
 * `--engine py` / `MX_AGENT_ENGINE=py`, but it delegates to a Python `adw/`
 * sibling that is NOT included in this standalone port, so it will fail loudly
 * unless that sibling is added.
 */
export const DEFAULT_ENGINE: EngineId = 'ts';

/**
 * Validate a `--engine` / `MX_AGENT_ENGINE` value. Unset/empty falls back to
 * the default; anything unknown throws (the engine analogue of
 * registry.resolveRunnerId).
 */
export function resolveEngineId(raw?: string | null): EngineId {
  if (raw === undefined || raw === null || raw === '') {
    return DEFAULT_ENGINE;
  }
  if ((ENGINE_IDS as readonly string[]).includes(raw)) {
    return raw as EngineId;
  }
  throw new AdwError(`unknown engine: '${raw}' (valid: ${ENGINE_IDS.join(', ')})`);
}

// --- argv handling ------------------------------------------------------------

/** Split argv at the first `--` (the TS twin of adw.common.partition_on_double_dash). */
export function splitPassthru(argv: readonly string[]): [string[], string[]] {
  const cut = argv.indexOf('--');
  if (cut === -1) {
    return [[...argv], []];
  }
  return [argv.slice(0, cut), argv.slice(cut + 1)];
}

/**
 * Pull every `--engine <value>` / `--engine=<value>` out of `args` so the
 * remainder can be forwarded verbatim to the py engine (whose parser does not
 * know the flag). The last occurrence wins, like argparse.
 */
export function extractEngineFlag(args: readonly string[]): { engine?: string; rest: string[] } {
  const rest: string[] = [];
  let engine: string | undefined;
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i]!;
    if (arg === '--engine') {
      const value = args[i + 1];
      if (value === undefined || value === '') {
        throw new AdwError('--engine requires a value (py or ts)');
      }
      engine = value;
      i += 1;
    } else if (arg.startsWith('--engine=')) {
      engine = arg.slice('--engine='.length);
      if (engine === '') {
        // An explicit-but-empty flag must fail loud, not mask MX_AGENT_ENGINE
        // and silently pick the built-in default.
        throw new AdwError('--engine requires a value (py or ts)');
      }
    } else {
      rest.push(arg);
    }
  }
  return engine === undefined ? { rest } : { engine, rest };
}

// --- ts-engine flag parsing (mirrors adw/issue.py build_parser) ----------------

export interface ParsedCli {
  /** -h/--help was requested; print usage and exit 0 (the rest is unset). */
  help?: true;
  issue: number;
  /** Free-form notes after the issue number (accepted for CLI parity; the
   * phased pipeline derives context from the issue itself, as in Python). */
  notes: string[];
  /** Raw --runner value; undefined falls back to MX_AGENT_RUNNER/default. */
  runner?: string;
  options: RunOptions;
}

/**
 * Flags only the py engine understands: the one-shot/legacy modes, plus pi's
 * --thinking — which the phased Python path DOES forward to the runner CLI;
 * the ts engine has no runner command line, so it is rejected loudly here.
 */
const PY_ONLY_FLAGS = new Set([
  '--one-shot',
  '--template',
  '--json',
  '--print-prompt',
  '--log-dir',
  '--thinking',
]);

const BOOLEAN_FLAGS = new Set([
  '--resume',
  '--no-progress',
  '--inherit-env',
  '--no-verify',
  '--force',
  '--allow-dirty',
  '-y',
  '--yes',
  '--dry-run',
]);

const VALUE_FLAGS = new Set([
  '--runner',
  '--phases',
  '--adw-id',
  '--max-resolve',
  '--max-patch',
  '--max-ci-fix',
  '--ci-poll-interval',
  '--ci-max-polls',
  '--test-cmd',
  '--model',
  '--repo',
  '--base',
  '--timeout',
  '--max-budget-usd',
]);

function parseIntFlag(flag: string, value: string): number {
  if (!/^-?\d+$/.test(value)) {
    throw new AdwError(`${flag} expects an integer, got: ${value}`);
  }
  return Number(value);
}

function parseFloatFlag(flag: string, value: string): number {
  const parsed = Number(value);
  if (value === '' || !Number.isFinite(parsed)) {
    throw new AdwError(`${flag} expects a number, got: ${value}`);
  }
  return parsed;
}

export const CLI_USAGE = `usage: adw-sdlc issue [--engine {py,ts}] <issue-number> [notes...] [flags]

Run the phased /issue delivery workflow. --engine / MX_AGENT_ENGINE picks the
driving language (default: ts). --engine py delegates to a python3 adw/issue.py
sibling, which is NOT bundled in this standalone port. Flags below apply to the
ts engine:

  --runner <id>            agent runner: claude (default) | codex | opencode | pi
                           Env: MX_AGENT_RUNNER
  --phases <list>          comma-separated phase subset/order (default: full chain)
  --adw-id <id>            reuse/resume a run by its 8-char id
  --resume                 resume from saved state (requires --adw-id)
  --no-progress            do not post [MX-ADW] issue comments
  --inherit-env            give the agent the full env (less isolated)
  --max-resolve <n>        max self-heal test attempts (default: 3)
  --max-patch <n>          max review-blocker patch attempts (default: 2)
  --max-ci-fix <n>         max CI-fix attempts (default: 3)
  --ci-poll-interval <s>   seconds between CI polls (default: 30)
  --ci-max-polls <n>       max CI status polls (default: 40)
  --test-cmd <cmd>         test gate command. Env: MX_AGENT_TEST_CMD
  --model <id>             model override (overrides per-phase routing)
  --repo <owner/repo>      repo for issue lookups. Env: REPO
  --base <branch>          base branch to fork from / merge into (default: main)
  --timeout <s>            abort a runner call after N seconds (0 = none)
  --max-budget-usd <usd>   native budget cap (runners that support it)
  --no-verify              skip the post-run CLOSED check
  --force                  run even if the issue is already CLOSED
  --allow-dirty            skip the clean-working-tree precondition
  -y, --yes                do not prompt for confirmation
  --dry-run                preview the plan; do not run
  -h, --help               show this help and exit`;

/**
 * Parse the ts-engine argv (post `--engine` extraction, pre `--` split) into
 * the issue number plus orchestrator RunOptions. Defaults mirror
 * adw/issue.py build_parser, including the MX_AGENT_TEST_CMD / REPO env
 * fallbacks; second-based CLI flags become the milliseconds RunOptions uses.
 */
export function parseCliArgs(
  argv: readonly string[],
  env: Record<string, string | undefined> = {},
): ParsedCli {
  const tokens: string[] = [];
  const flags = new Map<string, string | true>();
  let inTokenRun = false;
  let tokenRunDone = false;

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]!;
    if (!arg.startsWith('-') || /^-?\d+$/.test(arg)) {
      if (tokenRunDone) {
        // argparse parity: the nargs='*' positional consumes ONE contiguous
        // chunk; a second positional run is an error there, and a silent
        // note-demotion here would hide typos like a space-separated
        // --phases list.
        throw new AdwError(`unrecognized argument: ${arg}`);
      }
      inTokenRun = true;
      tokens.push(arg);
      continue;
    }
    if (inTokenRun) {
      inTokenRun = false;
      tokenRunDone = true;
    }
    const eq = arg.indexOf('=');
    const name = eq === -1 ? arg : arg.slice(0, eq);
    if (name === '-h' || name === '--help') {
      return { help: true, issue: 0, notes: [], options: {} };
    }
    if (PY_ONLY_FLAGS.has(name)) {
      throw new AdwError(`${name} is a py-engine option; rerun with --engine py (or MX_AGENT_ENGINE=py)`);
    }
    if (BOOLEAN_FLAGS.has(name)) {
      if (eq !== -1) {
        throw new AdwError(`${name} does not take a value`);
      }
      flags.set(name, true);
      continue;
    }
    if (VALUE_FLAGS.has(name)) {
      let value: string;
      if (eq !== -1) {
        value = arg.slice(eq + 1);
      } else {
        const next = argv[i + 1];
        // argparse parity: an option-looking token (negative numbers
        // excepted) is never swallowed as a value — `--model --yes` must
        // fail loud, not silently consume the user's --yes.
        if (next === undefined || (next.startsWith('-') && !/^-\d/.test(next))) {
          throw new AdwError(`${name} requires a value`);
        }
        value = next;
        i += 1;
      }
      if (name === '--runner' && value === '') {
        // Loudness parity with adw/issue.py ("unknown --runner: ''"); an
        // empty flag must not mask MX_AGENT_RUNNER and default silently.
        throw new AdwError('--runner requires a non-empty value');
      }
      flags.set(name, value);
      continue;
    }
    throw new AdwError(`unknown flag: ${name}`);
  }

  if (tokens.length === 0) {
    throw new AdwError('missing issue number; usage: issue <number> [notes]');
  }
  const issueStr = tokens[0]!;
  if (!/^\d+$/.test(issueStr)) {
    throw new AdwError(`issue must be a number, got: ${issueStr}`);
  }

  const str = (name: string): string | undefined => {
    const v = flags.get(name);
    return typeof v === 'string' ? v : undefined;
  };
  const has = (name: string): boolean => flags.has(name);

  const testCmd = str('--test-cmd') ?? env['MX_AGENT_TEST_CMD'];
  const repo = str('--repo') ?? env['REPO'];
  const maxResolve = str('--max-resolve');
  const maxPatch = str('--max-patch');
  const maxCiFix = str('--max-ci-fix');
  const ciPollInterval = str('--ci-poll-interval');
  const ciMaxPolls = str('--ci-max-polls');
  const timeout = str('--timeout');
  const maxBudgetUsd = str('--max-budget-usd');

  const options: RunOptions = {
    ...(str('--phases') !== undefined ? { phases: str('--phases')! } : {}),
    ...(str('--adw-id') !== undefined ? { adwId: str('--adw-id')! } : {}),
    ...(has('--resume') ? { resume: true } : {}),
    ...(has('--no-progress') ? { noProgress: true } : {}),
    ...(has('--inherit-env') ? { inheritEnv: true } : {}),
    ...(maxResolve !== undefined ? { maxResolve: parseIntFlag('--max-resolve', maxResolve) } : {}),
    ...(maxPatch !== undefined ? { maxPatch: parseIntFlag('--max-patch', maxPatch) } : {}),
    ...(maxCiFix !== undefined ? { maxCiFix: parseIntFlag('--max-ci-fix', maxCiFix) } : {}),
    ...(ciPollInterval !== undefined
      ? { ciPollIntervalMs: parseIntFlag('--ci-poll-interval', ciPollInterval) * 1000 }
      : {}),
    ...(ciMaxPolls !== undefined ? { ciMaxPolls: parseIntFlag('--ci-max-polls', ciMaxPolls) } : {}),
    ...(testCmd !== undefined ? { testCmd } : {}),
    ...(str('--model') !== undefined ? { model: str('--model')! } : {}),
    ...(repo !== undefined ? { repo } : {}),
    ...(str('--base') !== undefined ? { base: str('--base')! } : {}),
    ...(timeout !== undefined ? { timeoutMs: parseIntFlag('--timeout', timeout) * 1000 } : {}),
    ...(has('--no-verify') ? { verify: false } : {}),
    ...(has('--force') ? { force: true } : {}),
    ...(has('--allow-dirty') ? { allowDirty: true } : {}),
    ...(has('-y') || has('--yes') ? { yes: true } : {}),
    ...(has('--dry-run') ? { dryRun: true } : {}),
    ...(maxBudgetUsd !== undefined
      ? { maxBudgetUsd: parseFloatFlag('--max-budget-usd', maxBudgetUsd) }
      : {}),
  };

  const runner = str('--runner');
  return {
    issue: Number(issueStr),
    notes: tokens.slice(1),
    ...(runner !== undefined ? { runner } : {}),
    options,
  };
}

// --- dispatch -------------------------------------------------------------------

/** Every external effect main() touches, injectable for tests. */
export interface CliDeps {
  env: Record<string, string | undefined>;
  /** Run the py engine (`python3 adw/issue.py <argv>`) and return its rc. */
  runPyEngine: (argv: readonly string[]) => Promise<number>;
  loadRunner: typeof loadRunner;
  runIssue: typeof run;
}

function spawnPyEngine(argv: readonly string[]): Promise<number> {
  return new Promise((resolve, reject) => {
    // No `env:` option: the child inherits the full parent environment on
    // purpose — the py engine builds its own secret boundary, exactly as a
    // direct `python3 adw/issue.py` invocation would.
    const child = spawn('python3', [join(REPO_ROOT, 'adw', 'issue.py'), ...argv], {
      cwd: REPO_ROOT,
      stdio: 'inherit',
    });
    child.on('error', (err) => {
      reject(new AdwError(`could not launch the py engine (python3): ${err.message}`, { cause: err }));
    });
    child.on('exit', (code, signal) => {
      resolve(code ?? (signal !== null ? 1 : 0));
    });
  });
}

function defaultCliDeps(): CliDeps {
  return {
    env: process.env,
    runPyEngine: spawnPyEngine,
    loadRunner,
    runIssue: run,
  };
}

/**
 * --dry-run never invokes the runner (run() prints the plan and returns
 * before any runner use beyond `id`), so previewing a plan must not require
 * the selected runner's optional SDK — parity with adw/_orchestrator.py,
 * which prints the plan after a name-only check, never resolving the binary.
 */
function dryRunRunner(id: RunnerId): AgentRunner {
  return {
    id,
    caps: {
      nativeSchema: false,
      perToolHook: false,
      envIsolation: 'subprocess-allowlist',
      costUsd: false,
      nativeBudget: false,
      resume: false,
    },
    async runPhase(): Promise<never> {
      throw new AdwError('the dry-run runner cannot execute phases');
    },
  };
}

/**
 * CLI entry: resolve the engine, then delegate (py) or bind the selected
 * runner into orchestrator.run (ts). Expected failures (AdwError, including
 * RunnerNotInstalledError) print `error: …` and return 1, mirroring
 * adw/issue.py main(); anything else is a bug and propagates.
 */
export async function main(argv: readonly string[], depsOverride: Partial<CliDeps> = {}): Promise<number> {
  const deps: CliDeps = { ...defaultCliDeps(), ...depsOverride };
  try {
    const [ours, passthru] = splitPassthru(argv);
    const { engine: engineFlag, rest } = extractEngineFlag(ours);
    const engine = resolveEngineId(engineFlag ?? deps.env['MX_AGENT_ENGINE']);

    if (engine === 'py') {
      const forwarded = passthru.length > 0 ? [...rest, '--', ...passthru] : rest;
      return await deps.runPyEngine(forwarded);
    }

    if (passthru.length > 0) {
      // Python forwards post-`--` flags to the runner CLI invocation; the ts
      // engine drives SDK seams with no command line to splice them into.
      throw new AdwError(
        'runner passthru flags (after --) are a py-engine feature; the ts engine has no runner command line',
      );
    }
    const parsed = parseCliArgs(rest, deps.env);
    if (parsed.help === true) {
      console.log(CLI_USAGE);
      return 0;
    }
    if (deps.env['PI_THINKING']) {
      // Python's phased path forwards PI_THINKING to the pi CLI; the ts
      // engine routes models/effort per phase instead — say so rather than
      // silently dropping the knob.
      note('PI_THINKING is ignored by the ts engine (phased model routing applies); use --engine py for pi --thinking');
    }
    const runnerId = resolveRunnerId(parsed.runner ?? deps.env['MX_AGENT_RUNNER']);
    const runner =
      parsed.options.dryRun === true ? dryRunRunner(runnerId) : await deps.loadRunner(runnerId);
    return await deps.runIssue(parsed.issue, runner, parsed.options);
  } catch (err) {
    if (err instanceof AdwError) {
      console.error(`error: ${err.message}`);
      return 1;
    }
    throw err;
  }
}

const entry = process.argv[1];
if (entry !== undefined && import.meta.url === pathToFileURL(entry).href) {
  main(process.argv.slice(2)).then((rc) => {
    process.exitCode = rc;
  });
}
