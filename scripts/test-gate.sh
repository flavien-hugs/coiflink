#!/usr/bin/env bash
# Test gate agrégé du pipeline ADW (issue #6).
#
# Point d'entrée unique, « argv-safe », enchaînant les tests unitaires des trois
# paquets du monorepo avec les MÊMES commandes que la CI applicative
# (.github/workflows/ci.yml) pour éviter toute divergence local <-> CI :
#   backend/        : pytest
#   web-dashboard/  : npm test   (soit vitest run)
#   app-mobile/     : flutter test
#
# Pourquoi un script wrapper plutôt qu'un one-liner dans MX_AGENT_TEST_CMD :
# l'orchestrateur (adw_sdlc/) découpe la commande du gate par simple séparation
# argv honorant seulement les guillemets (shellSplit, common.ts) PUIS la lance
# SANS shell (spawnSync, exec.ts). Aucun opérateur shell (`&&`, `;`, `|`, `>`,
# glob, `$VAR`) n'est donc interprété : un enchaînement multi-paquets ne peut
# vivre que dans un script committé. Ce script encapsule toute la logique shell
# et n'est invoqué que via une commande argv triviale (`bash .../test-gate.sh`).
#
# Répertoire courant : l'orchestrateur hérite du cwd de son point d'entrée
# (scripts/run-issue.sh fait `cd adw_sdlc/` avant de lancer le CLI). Ce script
# se réancre systématiquement à la racine du dépôt (voir repo_root ci-dessous),
# de sorte que son comportement est IDENTIQUE quel que soit le cwd d'appel.
#
# Sélection des paquets : variable d'environnement TEST_GATE_PACKAGES
# (mots séparés par des espaces ; défaut = les trois, parité avec la CI).
#   TEST_GATE_PACKAGES="backend"          # backend seul
#   TEST_GATE_PACKAGES="backend web"      # backend + web
# « Fail-closed » : si le toolchain d'un paquet SÉLECTIONNÉ est absent, le gate
# ÉCHOUE (rc != 0) — il n'est jamais « silencieusement vert ». Retirez le paquet
# de TEST_GATE_PACKAGES sur les machines dépourvues de son toolchain.
#
# Code de sortie : 0 si tous les paquets sélectionnés passent ; != 0 si au moins
# un échoue (on n'interrompt pas au premier échec : tous les paquets sont
# exécutés et chaque rc est rapporté, pour un diagnostic complet en une passe).
#
# Sécurité : les tests ne doivent JAMAIS journaliser de secret ni de PII — leur
# sortie est tronquée et transmise à l'agent en cas d'échec (phase resolve).
# Voir docs/strategie-de-tests.md et backend/tests/test_secrets_policy.py.
#
# Usage :
#   scripts/test-gate.sh                          # depuis la racine
#   bash ../scripts/test-gate.sh                  # depuis adw_sdlc/ (run-issue.sh)
#   TEST_GATE_PACKAGES="backend" scripts/test-gate.sh

# NB : PAS de `set -e`. On collecte explicitement le rc de chaque paquet pour
# tous les exécuter et agréger les échecs ; `set -e` interromprait au premier.
set -uo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

# Défaut = parité CI (les trois paquets). Une valeur explicite restreint le gate.
packages="${TEST_GATE_PACKAGES:-backend web mobile}"

# Exécute la commande de test d'un paquet dans son répertoire et renvoie son rc.
# Fail-closed : un binaire absent renvoie 127 (échec), jamais un vert silencieux.
#   $1 = libellé lisible   $2 = répertoire du paquet   $3.. = commande (argv)
run_one() {
  local label="$1" dir="$2"
  shift 2
  local bin="$1"

  if ! command -v "$bin" >/dev/null 2>&1; then
    echo ">> test-gate: [$label] outil « $bin » introuvable — ÉCHEC (fail-closed)." >&2
    echo "   → installez le toolchain, ou retirez « $label » de TEST_GATE_PACKAGES." >&2
    return 127
  fi

  echo ">> test-gate: [$label] $* (dans $dir/)" >&2
  (cd "$dir" && "$@")
  local rc=$?
  if [ "$rc" -eq 0 ]; then
    echo ">> test-gate: [$label] OK" >&2
  else
    echo ">> test-gate: [$label] ÉCHEC (rc=$rc)" >&2
  fi
  return "$rc"
}

overall_rc=0
ran_any=0

for pkg in $packages; do
  ran_any=1
  case "$pkg" in
    backend) run_one "backend" "backend"       pytest ;;
    web)     run_one "web"     "web-dashboard" npm test ;;
    mobile)  run_one "mobile"  "app-mobile"    flutter test ;;
    *)
      echo ">> test-gate: paquet inconnu « $pkg » (attendus : backend web mobile)." >&2
      false
      ;;
  esac
  rc=$?
  if [ "$rc" -ne 0 ]; then
    overall_rc=1
  fi
done

if [ "$ran_any" -eq 0 ]; then
  echo ">> test-gate: aucun paquet sélectionné (TEST_GATE_PACKAGES vide) — ÉCHEC." >&2
  exit 2
fi

if [ "$overall_rc" -eq 0 ]; then
  echo ">> test-gate: tous les paquets sélectionnés sont verts." >&2
else
  echo ">> test-gate: au moins un paquet a échoué." >&2
fi
exit "$overall_rc"
