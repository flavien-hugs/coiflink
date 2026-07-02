/**
 * Shell integration tests for scripts/test-gate.sh (issue #6).
 *
 * These tests exercise the gate wrapper as a black box: they create fake
 * tool executables in a temp directory, inject them into PATH, and assert
 * the script's exit code and stderr output — without touching a real Flutter,
 * Node, or Python toolchain.
 *
 * Coverage:
 *  - Empty TEST_GATE_PACKAGES → rc 2
 *  - Unknown package name → rc != 0
 *  - All selected packages pass → rc 0
 *  - One package fails → rc != 0, but all packages still run (aggregation)
 *  - Missing toolchain (fail-closed) → rc 127
 *  - cwd independence: same result from repo root and from adw_sdlc/
 *  - Invoked as "bash ../scripts/test-gate.sh" from adw_sdlc/ (adw.env.example pattern)
 */

import { spawnSync } from 'node:child_process';
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const GATE_SCRIPT = join(REPO_ROOT, 'scripts', 'test-gate.sh');
const ADW_SDLC_DIR = join(REPO_ROOT, 'adw_sdlc');

let fakeBin: string;

beforeEach(() => {
  fakeBin = mkdtempSync(join(tmpdir(), 'adw-fake-bin-'));
});

afterEach(() => {
  rmSync(fakeBin, { recursive: true, force: true });
});

/** Install a fake tool in the temp bin dir that exits with the given rc. */
function makeFakeTool(name: string, rc: number): void {
  const path = join(fakeBin, name);
  writeFileSync(path, `#!/bin/sh\nexit ${rc}\n`);
  chmodSync(path, 0o755);
}

/**
 * Run test-gate.sh with a controlled PATH and environment.
 *
 * The base PATH always includes /usr/bin:/bin so that bash can resolve
 * system utilities (dirname, pwd) regardless of any extraEnv override.
 * spawnSync resolves the executable itself via the provided env.PATH, so
 * we use an absolute bash path when restricting PATH to a custom value.
 */
const BASH = '/bin/bash';
const SYSTEM_UTILS = '/usr/bin:/bin';

function runGate(
  packages: string,
  { extraEnv = {}, cwd = REPO_ROOT, scriptInvocation = [BASH, GATE_SCRIPT] }: {
    extraEnv?: Record<string, string>;
    cwd?: string;
    scriptInvocation?: string[];
  } = {},
) {
  const [bin, ...args] = scriptInvocation;
  return spawnSync(bin!, args, {
    encoding: 'utf8',
    env: {
      PATH: `${fakeBin}:${process.env['PATH'] ?? SYSTEM_UTILS}`,
      TEST_GATE_PACKAGES: packages,
      ...extraEnv,
    },
    cwd,
  });
}

describe('test-gate.sh', () => {
  it('exits 2 when TEST_GATE_PACKAGES is whitespace-only (no packages selected)', () => {
    // Empty string ('') triggers the ${:-default} fallback in the script and
    // runs all three packages. Whitespace-only (' ') expands to zero tokens
    // via word-splitting, so the for loop never runs → ran_any=0 → exit 2.
    const r = runGate(' ');
    expect(r.status).toBe(2);
    expect(r.stderr).toContain('aucun paquet sélectionné');
  });

  it('exits non-zero for an unknown package name', () => {
    const r = runGate('totally-unknown-package');
    expect(r.status).not.toBe(0);
  });

  it('exits 0 when the single selected package passes', () => {
    makeFakeTool('pytest', 0);
    const r = runGate('backend');
    expect(r.status).toBe(0);
    expect(r.stderr).toContain('[backend] OK');
  });

  it('exits non-zero when the selected package fails', () => {
    makeFakeTool('pytest', 1);
    const r = runGate('backend');
    expect(r.status).not.toBe(0);
    expect(r.stderr).toContain('[backend] ÉCHEC');
  });

  it('exits 0 when all selected packages pass', () => {
    makeFakeTool('pytest', 0);
    makeFakeTool('npm', 0);
    const r = runGate('backend web');
    expect(r.status).toBe(0);
    expect(r.stderr).toContain('[backend] OK');
    expect(r.stderr).toContain('[web] OK');
  });

  it('runs all packages even when the first one fails (aggregates, does not short-circuit)', () => {
    makeFakeTool('pytest', 1);
    makeFakeTool('npm', 0);
    const r = runGate('backend web');
    // Both packages must have been attempted
    expect(r.stderr).toContain('[backend]');
    expect(r.stderr).toContain('[web]');
    expect(r.status).not.toBe(0);
    expect(r.stderr).toContain('au moins un paquet a échoué');
  });

  it('fails (fail-closed) when the toolchain binary is absent from PATH', () => {
    // PATH = /usr/bin:/bin only (system utils) + empty fakeBin.
    // pytest lives nowhere in /usr/bin or /bin, so command -v pytest fails →
    // run_one prints "introuvable" and returns 127, making overall_rc = 1.
    // We use /bin/bash explicitly so spawnSync can resolve the executable even
    // with this restricted PATH.
    const r = runGate('backend', {
      extraEnv: { PATH: `${SYSTEM_UTILS}:${fakeBin}` },
    });
    expect(r.status).not.toBe(0);
    expect(r.stderr).toContain('introuvable');
  });

  it('exits 0 when called from the repo root (absolute script path)', () => {
    makeFakeTool('pytest', 0);
    const r = runGate('backend', { cwd: REPO_ROOT });
    expect(r.status).toBe(0);
  });

  it('exits 0 when called from adw_sdlc/ (absolute script path, cwd independence)', () => {
    makeFakeTool('pytest', 0);
    const r = runGate('backend', { cwd: ADW_SDLC_DIR });
    expect(r.status).toBe(0);
  });

  it('works when invoked as "bash ../scripts/test-gate.sh" from adw_sdlc/ (adw.env.example pattern)', () => {
    makeFakeTool('pytest', 0);
    const r = runGate('backend', {
      cwd: ADW_SDLC_DIR,
      scriptInvocation: [BASH, '../scripts/test-gate.sh'],
    });
    expect(r.status).toBe(0);
  });

  it('fails deterministically when a mobile package has no flutter binary', () => {
    // flutter is absent from /usr/bin and /bin → gate fails, never silently green
    const r = runGate('mobile', {
      extraEnv: { PATH: `${SYSTEM_UTILS}:${fakeBin}` },
    });
    expect(r.status).not.toBe(0);
    expect(r.stderr).toContain('introuvable');
  });

  it('exits non-zero (not rc 2) when TEST_GATE_PACKAGES is empty string — bash ${:-default} runs all three packages', () => {
    // EMPTY string ('') is distinct from whitespace-only (' '):
    // bash's ${TEST_GATE_PACKAGES:-backend web mobile} expands an empty value
    // to the default, so all three packages are attempted.  With PATH
    // restricted to system utils (no fake tools installed), all three fail with
    // "introuvable" (overall_rc=1).
    // rc 2 is reserved for "zero packages ran at all" — this run attempted 3.
    const r = runGate('', { extraEnv: { PATH: `${SYSTEM_UTILS}:${fakeBin}` } });
    expect(r.status).not.toBe(0);
    expect(r.status).not.toBe(2);
    expect(r.stderr).toContain('introuvable');
  });

  it('exits 0 when all three packages pass (backend web mobile)', () => {
    makeFakeTool('pytest', 0);
    makeFakeTool('npm', 0);
    makeFakeTool('flutter', 0);
    const r = runGate('backend web mobile');
    expect(r.status).toBe(0);
    expect(r.stderr).toContain('[backend] OK');
    expect(r.stderr).toContain('[web] OK');
    expect(r.stderr).toContain('[mobile] OK');
    expect(r.stderr).toContain('tous les paquets sélectionnés sont verts');
  });

  it('runs known packages before the unknown one and still fails the gate', () => {
    // Aggregation: a known passing package followed by an unknown name.
    // The gate must not short-circuit — backend runs, then "unknown-pkg" fails.
    makeFakeTool('pytest', 0);
    const r = runGate('backend unknown-pkg');
    expect(r.status).not.toBe(0);
    expect(r.stderr).toContain('[backend]');
    expect(r.stderr).toContain('unknown-pkg');
  });

  it('fails (fail-closed) when npm is absent from PATH for the web package', () => {
    // Symmetry with the backend and mobile fail-closed tests:
    // npm lives nowhere in /usr/bin or /bin → "introuvable" → rc != 0.
    const r = runGate('web', {
      extraEnv: { PATH: `${SYSTEM_UTILS}:${fakeBin}` },
    });
    expect(r.status).not.toBe(0);
    expect(r.stderr).toContain('introuvable');
  });

  it('aggregates failures across three packages — middle success does not mask outer failures', () => {
    // backend fails, web passes, mobile fails → all three run, overall non-zero.
    makeFakeTool('pytest', 1);   // backend: échec
    makeFakeTool('npm', 0);      // web: OK
    makeFakeTool('flutter', 1);  // mobile: échec
    const r = runGate('backend web mobile');
    expect(r.status).not.toBe(0);
    expect(r.stderr).toContain('[backend] ÉCHEC');
    expect(r.stderr).toContain('[web] OK');
    expect(r.stderr).toContain('[mobile] ÉCHEC');
    expect(r.stderr).toContain('au moins un paquet a échoué');
  });
});
