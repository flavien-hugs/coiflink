#!/usr/bin/env bash
# Wrapper around the adw_sdlc CLI: loads local run config from scripts/adw.env
# (gitignored) and forwards every argument verbatim to `tsx src/cli.ts`.
#
# Usage:
#   scripts/run-issue.sh <issue-number> [flags...]
#
# Examples:
#   scripts/run-issue.sh 12 --dry-run
#   scripts/run-issue.sh 12 --runner claude --yes
#
# Local config (credentials, test gate, runner, repo) goes in scripts/adw.env —
# copy scripts/adw.env.example to scripts/adw.env and fill it in. Anything
# already exported in your shell still wins / is passed through.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
adw_dir="$repo_root/adw_sdlc"
env_file="$script_dir/adw.env"

if [ "$#" -eq 0 ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  if [ "$#" -eq 0 ]; then
    echo "usage: scripts/run-issue.sh <issue-number> [flags...]" >&2
    echo "       scripts/run-issue.sh --help        # full CLI flag list" >&2
    exit 2
  fi
  cd "$adw_dir" && exec npx tsx src/cli.ts --help
fi

# Load local config/secrets if present (never committed; see .gitignore).
if [ -f "$env_file" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
fi

if [ ! -d "$adw_dir/node_modules" ]; then
  echo "error: dependencies not installed. Run: (cd adw_sdlc && npm install)" >&2
  exit 1
fi

# Echo the resolved, non-secret run context.
runner="${MX_AGENT_RUNNER:-claude}"
echo ">> adw_sdlc run: issue=$1 runner=$runner repo=${REPO:-<current>}" >&2
if [ -n "${MX_AGENT_TEST_CMD:-}" ]; then
  echo ">> test gate: $MX_AGENT_TEST_CMD" >&2
else
  echo ">> test gate: (none configured — gate will be skipped)" >&2
fi

cd "$adw_dir"
exec npx tsx src/cli.ts "$@"
