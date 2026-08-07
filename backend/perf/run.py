"""Orchestration d'un run de charge §12.1 (#52) — point d'entrée unique.

Enchaîne : vérification de l'environnement (skip propre sinon) → `alembic upgrade
head` → **seed** représentatif → démarrage d'un **uvicorn local** (serveur réel) *ou*
ciblage d'une **URL externe** (`PERF_TARGET_URL`, p. ex. staging Railway) → **charge**
(pilote intégré `driver.py`) → **rapport** (p50/p95/p99, débit, erreurs + table de
verdict vs budgets §12.1, en CSV+JSON+Markdown) → **teardown** FK-safe.

Modes :
- **local** (défaut) : requiert `DATABASE_URL` ; démarre uvicorn avec un **secret JWT
  de test local** (jamais un secret de prod), seede et nettoie la base directement.
- **externe** (`PERF_TARGET_URL` défini) : cible un serveur déjà déployé ; le nettoyage
  SQL n'a lieu que si `PERF_DB_URL`/`DATABASE_URL` pointe une base joignable.

Comportement **informatif par défaut** : un verdict `WARN`/`FAIL` **n'échoue pas** le
processus (code 0) — sauf `--strict`, réservé à un environnement de référence stable.

Usage :
    cd backend
    DATABASE_URL=postgresql://coif:pw@localhost:55433/coif python -m perf.run
    PERF_TARGET_URL=https://staging.example python -m perf.run --skip-seed
    python -m perf.run --teardown-only   # nettoyage seul (plage réservée)

**Hygiène §11** : aucun secret ni PII n'est journalisé — on compte, on n'affiche jamais
un numéro, un nom, un jeton ni un montant nominatif ; le rapport passe `assert_no_pii`.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .report import PerfReport, Verdict, assert_no_pii

logger = logging.getLogger("perf.run")

_PERF_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _PERF_DIR.parent
_DEFAULT_OUTPUT_DIR = _PERF_DIR / "reports"


# ─── Vérification de l'extra `perf` (skip propre) ─────────────────────────────


def _perf_extra_available() -> bool:
    try:
        import httpx  # noqa: F401
    except ImportError:
        return False
    return True


# ─── Serveur local uvicorn ────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run_alembic_upgrade(database_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(_BACKEND_DIR),
        env=env,
        check=True,
    )


def _start_local_server(database_url: str, port: int) -> subprocess.Popen:
    """Démarre uvicorn (serveur **réel**) avec un secret JWT **de test local**."""

    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        # Secret JWT **de test**, local et jetable — jamais un secret de prod (§11.3).
        # `run.py` ne l'utilise que pour cet uvicorn local ; les jetons de charge sont
        # ensuite obtenus par login HTTP réel (le seed ne trace aucun jeton).
        config.JWT_SECRET_ENV: os.environ.get(config.JWT_SECRET_ENV)
        or config.DEFAULT_TEST_JWT_SECRET,
        "APP_ENV": "perf",
    }
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "coiflink_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(_BACKEND_DIR),
        env=env,
    )


def _wait_healthy(base_url: str, *, attempts: int = 60, delay: float = 0.5) -> bool:
    import httpx

    for _ in range(attempts):
        try:
            resp = httpx.get(f"{base_url}/health", timeout=2.0)
            if resp.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(delay)
    return False


# ─── Écriture du rapport (CSV + JSON + Markdown, sans PII) ─────────────────────


def _write_report(report: PerfReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    serialized = {
        "perf-report.json": report.to_json(),
        "perf-report.csv": report.to_csv(),
        "perf-report.md": report.to_markdown(),
    }
    for filename, content in serialized.items():
        # Garde §11.3/§11.4 : aucune PII ne doit fuiter dans un artefact de perf.
        assert_no_pii(content)
        (output_dir / filename).write_text(content, encoding="utf-8")
    logger.info("Rapport écrit dans %s (json/csv/md).", output_dir)


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _cleanup(database_url: str | None) -> None:
    if not database_url:
        logger.warning(
            "Aucune base de nettoyage (PERF_DB_URL/DATABASE_URL) : teardown SQL ignoré. "
            "Les données de charge de la plage réservée restent à nettoyer côté cible."
        )
        return
    from .seed import build_cleanup_engine, wipe_perf_data

    engine = build_cleanup_engine(database_url)
    try:
        wipe_perf_data(engine)
        logger.info("Teardown FK-safe effectué (plage réservée).")
    finally:
        engine.dispose()


# ─── Programme principal ──────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="perf.run", description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Échoue (code 1) si un budget §12.1 est dépassé (FAIL). Réservé à un "
        "environnement de référence stable (staging).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help="Répertoire des artefacts de rapport (défaut : perf/reports).",
    )
    parser.add_argument(
        "--no-migrate",
        action="store_true",
        help="Ne pas exécuter `alembic upgrade head` (base déjà migrée).",
    )
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Ne pas seeder (cible déjà peuplée) — utile contre une URL externe.",
    )
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Seeder puis s'arrêter (prépare une cible pour le moteur Locust).",
    )
    parser.add_argument(
        "--teardown-only",
        action="store_true",
        help="Nettoyer la plage réservée puis s'arrêter (aucune charge).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)

    database_url = os.environ.get("DATABASE_URL", "").strip()
    cleanup_db_url = os.environ.get("PERF_DB_URL", "").strip() or database_url
    target_url = os.environ.get("PERF_TARGET_URL", "").strip()

    # Teardown seul : ne requiert que la base (aucune charge, aucun extra `perf`).
    if args.teardown_only:
        _cleanup(cleanup_db_url)
        return 0

    if not _perf_extra_available():
        logger.warning(
            "Extra `perf` absent (httpx introuvable) : run de charge ignoré. "
            "Installez-le : pip install -e '.[perf]'."
        )
        return 0

    load_profile = config.load_profile_from_env()
    dataset = config.dataset_profile_from_env()

    if target_url:
        return _run_external(args, target_url, cleanup_db_url, load_profile, dataset)
    if not database_url:
        logger.warning(
            "Ni PERF_TARGET_URL ni DATABASE_URL : rien à mesurer, skip propre. "
            "Fournissez DATABASE_URL (serveur local) ou PERF_TARGET_URL (cible externe)."
        )
        return 0
    return _run_local(args, database_url, cleanup_db_url, load_profile, dataset)


def _run_external(
    args: argparse.Namespace,
    target_url: str,
    cleanup_db_url: str,
    load_profile: config.LoadProfile,
    dataset: config.DatasetProfile,
) -> int:
    from . import seed as seed_mod
    from .driver import run_load

    base_url = target_url.rstrip("/")
    if cleanup_db_url:
        _cleanup(cleanup_db_url)
    ctx = None
    if not args.skip_seed:
        ctx = seed_mod.seed(base_url, dataset)
    if args.seed_only:
        logger.info("Seed-only terminé contre la cible externe.")
        return 0
    if ctx is None:
        logger.error(
            "Sans --skip-seed le seed fournit le contexte ; avec --skip-seed la charge "
            "a besoin d'un contexte déjà matérialisé (Locust). Rien à exécuter ici."
        )
        return 0
    report = run_load(base_url, ctx, load_profile)
    _finish(report, args, cleanup_db_url)
    return _exit_code(report, args)


def _run_local(
    args: argparse.Namespace,
    database_url: str,
    cleanup_db_url: str,
    load_profile: config.LoadProfile,
    dataset: config.DatasetProfile,
) -> int:
    from . import seed as seed_mod
    from .driver import run_load

    if not args.no_migrate:
        _run_alembic_upgrade(database_url)
    _cleanup(cleanup_db_url)

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = _start_local_server(database_url, port)
    try:
        if not _wait_healthy(base_url):
            logger.error("Le serveur local n'a pas démarré (health check KO).")
            return 1
        ctx = seed_mod.seed(base_url, dataset)
        if args.seed_only:
            logger.info("Seed-only terminé contre le serveur local.")
            return 0
        report = run_load(base_url, ctx, load_profile)
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    _finish(report, args, cleanup_db_url)
    return _exit_code(report, args)


def _finish(report: PerfReport, args: argparse.Namespace, cleanup_db_url: str) -> None:
    _write_report(report, args.output_dir)
    # Résumé Markdown en clair (sans PII) sur stdout pour les logs CI.
    print(report.to_markdown())
    _cleanup(cleanup_db_url)


def _exit_code(report: PerfReport, args: argparse.Namespace) -> int:
    if args.strict and report.overall is Verdict.FAIL:
        logger.error("Budget §12.1 dépassé (FAIL) et --strict : sortie en échec.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
