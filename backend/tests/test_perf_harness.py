"""Tests d'hygiène et de cohérence du harnais de charge `perf/` (#52).

Ces tests vérifient des invariants **statiques et comportementaux déterministes**
sans déclencher de charge ni se connecter à une base ou un serveur :

- Unicité de la plage de téléphones `RESERVED_PHONE_PREFIX` (`+225059990`) parmi
  toutes les suites e2e — protection contre les collisions de nettoyage FK.
- Hygiène du `DEFAULT_TEST_JWT_SECRET` (clairement synthétique, pas un vrai secret).
- `pyproject.toml` déclare l'extra `perf` séparé de `dev` et hors prod.
- Le répertoire `backend/perf/` n'est pas dans `testpaths` (test gate non pollué).
- Tous les modules purs du harnais sont importables sans l'extra `perf`.
- `run._parse_args()` retourne les bonnes valeurs par défaut.
- `run.main([])` sans `DATABASE_URL` ni `PERF_TARGET_URL` retourne 0 (skip propre).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from perf import config

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_TESTS_DIR = _BACKEND_DIR / "tests"
_PYPROJECT = _BACKEND_DIR / "pyproject.toml"
_PERF_DIR = _BACKEND_DIR / "perf"


# ─── Unicité de la plage de téléphones réservée ───────────────────────────────


class TestPhonePrefixUniqueness:
    """La plage `+225059990` est distincte de toutes les autres suites e2e."""

    def test_reserved_prefix_not_in_any_e2e_file(self) -> None:
        conflicts = [
            p.name
            for p in _TESTS_DIR.glob("test_*_e2e.py")
            if config.RESERVED_PHONE_PREFIX in p.read_text()
        ]
        assert not conflicts, (
            f"Le préfixe {config.RESERVED_PHONE_PREFIX!r} est déjà utilisé dans "
            f"{conflicts!r}. Une collision de préfixe peut corrompre le nettoyage "
            "FK en CI (DELETE par préfixe, mémoire notifications-fk-restrict-cleanup)."
        )

    def test_reserved_prefix_not_in_integration_tests(self) -> None:
        conflicts = [
            p.name
            for p in _TESTS_DIR.glob("test_*_integration.py")
            if config.RESERVED_PHONE_PREFIX in p.read_text()
        ]
        assert not conflicts, (
            f"Le préfixe {config.RESERVED_PHONE_PREFIX!r} est utilisé dans "
            f"{conflicts!r} — collision possible."
        )

    def test_reserved_prefix_is_used_in_perf_config(self) -> None:
        """Vérification inverse : le préfixe réservé est bien défini dans perf/config.py."""
        assert config.RESERVED_PHONE_PREFIX in (_PERF_DIR / "config.py").read_text(), (
            "RESERVED_PHONE_PREFIX doit figurer littéralement dans perf/config.py "
            "pour servir de source de vérité."
        )


# ─── Hygiène du secret JWT de test ───────────────────────────────────────────


class TestJwtSecretHygiene:
    _SUSPICIOUS = re.compile(
        r"ghp_[A-Za-z0-9]{20,}"       # GitHub PAT
        r"|sk-[A-Za-z0-9]{20,}"        # OpenAI / Stripe
        r"|ey[A-Za-z0-9+/]{40,}"       # JWT encodé en base64
        r"|Bearer [A-Za-z0-9]{20,}"    # Bearer token en clair
    )

    def test_default_test_jwt_secret_not_suspicious(self) -> None:
        assert not self._SUSPICIOUS.search(config.DEFAULT_TEST_JWT_SECRET), (
            "DEFAULT_TEST_JWT_SECRET ressemble à un vrai jeton de production — "
            "utiliser une chaîne clairement synthétique."
        )

    def test_default_test_jwt_secret_contains_test_marker(self) -> None:
        lower = config.DEFAULT_TEST_JWT_SECRET.lower()
        assert any(kw in lower for kw in ("perf", "test", "local", "seed", "fake")), (
            "DEFAULT_TEST_JWT_SECRET doit contenir un marqueur ('perf', 'test', "
            "'local', 'seed' ou 'fake') indiquant qu'il n'est pas un secret de prod."
        )

    def test_jwt_secret_env_var_is_jwt_secret(self) -> None:
        assert config.JWT_SECRET_ENV == "JWT_SECRET", (
            "config.JWT_SECRET_ENV doit être 'JWT_SECRET' pour s'aligner sur la "
            "variable d'environnement applicative (cf. backend/.env.example)."
        )

    def test_seed_password_not_suspicious(self) -> None:
        assert not self._SUSPICIOUS.search(config.SEED_PASSWORD), (
            "SEED_PASSWORD ne doit pas ressembler à un vrai mot de passe ou token."
        )


# ─── pyproject.toml — extra `perf` isolé ─────────────────────────────────────


class TestPyprojectPerfExtra:
    @staticmethod
    def _optional() -> dict[str, list[str]]:
        data = tomllib.loads(_PYPROJECT.read_text())
        return data.get("project", {}).get("optional-dependencies", {})

    def test_perf_extra_declared(self) -> None:
        assert "perf" in self._optional(), (
            "pyproject.toml doit déclarer [project.optional-dependencies.perf] "
            "pour les dépendances de charge (httpx, locust)."
        )

    def test_perf_extra_contains_httpx(self) -> None:
        deps = self._optional()["perf"]
        assert any("httpx" in dep for dep in deps), (
            "L'extra `perf` doit inclure httpx (client HTTP du seed et du pilote)."
        )

    def test_perf_extra_contains_locust(self) -> None:
        deps = self._optional()["perf"]
        assert any("locust" in dep for dep in deps), (
            "L'extra `perf` doit inclure locust (moteur de charge Locust opt-in)."
        )

    def test_locust_not_in_dev_extra(self) -> None:
        """locust est un outil de charge, pas une dépendance du test gate `dev`."""
        dev_deps = self._optional().get("dev", [])
        assert not any("locust" in dep for dep in dev_deps), (
            "locust ne doit pas figurer dans l'extra `dev` — il appartient à `perf` "
            "uniquement (hors test gate ADW)."
        )

    def test_locust_not_in_main_dependencies(self) -> None:
        data = tomllib.loads(_PYPROJECT.read_text())
        main_deps = data.get("project", {}).get("dependencies", [])
        assert not any("locust" in dep for dep in main_deps), (
            "locust ne doit pas figurer dans les dépendances de production "
            "(hors image Docker)."
        )

    def test_perf_extra_is_distinct_from_dev(self) -> None:
        optional = self._optional()
        assert "dev" in optional
        assert "perf" in optional
        # Aucune dépendance de perf exclusive ne doit déborder dans dev.
        dev_set = set(optional["dev"])
        perf_set = set(optional["perf"])
        # httpx peut figurer dans les deux (test gate + charge), mais locust non.
        perf_only = {d for d in perf_set if "locust" in d}
        assert not perf_only.intersection(dev_set), (
            f"Des dépendances de charge exclusives ({perf_only!r}) figurent aussi "
            "dans `dev` — les isoler dans `perf` uniquement."
        )


# ─── Le répertoire `perf/` est hors du test gate ─────────────────────────────


class TestPerfIsolationFromTestGate:
    def test_testpaths_does_not_include_perf(self) -> None:
        data = tomllib.loads(_PYPROJECT.read_text())
        testpaths = (
            data.get("tool", {})
            .get("pytest", {})
            .get("ini_options", {})
            .get("testpaths", [])
        )
        assert "perf" not in testpaths, (
            "Le répertoire `perf/` ne doit pas figurer dans `testpaths` de pytest : "
            "le harnais de charge est opt-in et hors du test gate ADW."
        )

    def test_testpaths_includes_tests(self) -> None:
        data = tomllib.loads(_PYPROJECT.read_text())
        testpaths = (
            data.get("tool", {})
            .get("pytest", {})
            .get("ini_options", {})
            .get("testpaths", [])
        )
        assert "tests" in testpaths, (
            "Le répertoire `tests/` doit figurer dans `testpaths` de pytest."
        )


# ─── Structure du répertoire `perf/` ─────────────────────────────────────────


class TestPerfDirectoryStructure:
    def test_perf_directory_exists(self) -> None:
        assert _PERF_DIR.is_dir(), (
            "Le répertoire `backend/perf/` doit exister (harnais de charge #52)."
        )

    def test_perf_has_init_py(self) -> None:
        assert (_PERF_DIR / "__init__.py").exists()

    def test_perf_has_config_module(self) -> None:
        assert (_PERF_DIR / "config.py").exists()

    def test_perf_has_report_module(self) -> None:
        assert (_PERF_DIR / "report.py").exists()

    def test_perf_has_scenarios_module(self) -> None:
        assert (_PERF_DIR / "scenarios.py").exists()

    def test_perf_has_run_module(self) -> None:
        assert (_PERF_DIR / "run.py").exists()

    def test_perf_has_seed_module(self) -> None:
        assert (_PERF_DIR / "seed.py").exists()

    def test_perf_has_driver_module(self) -> None:
        assert (_PERF_DIR / "driver.py").exists()

    def test_perf_has_locustfile(self) -> None:
        assert (_PERF_DIR / "locustfile.py").exists()


# ─── Importabilité des modules purs sans extra `perf` ─────────────────────────


class TestPerfModuleImportability:
    """config, report, scenarios et run sont importables sans `locust` (stdlib + app)."""

    def test_config_importable(self) -> None:
        from perf import config as _c  # noqa: F401

        assert _c.BUDGETS_MS

    def test_report_importable(self) -> None:
        from perf import report as _r  # noqa: F401

        assert callable(_r.percentile)

    def test_scenarios_importable(self) -> None:
        from perf import scenarios as _s  # noqa: F401

        assert callable(_s.run_salon_search)

    def test_run_importable(self) -> None:
        from perf import run as _ru  # noqa: F401

        assert callable(_ru.main)


# ─── Parsing des arguments de `run.py` ────────────────────────────────────────


class TestRunArgParsing:
    """Tests de `run._parse_args()` — déterministes, aucun I/O."""

    def test_default_strict_is_false(self) -> None:
        from perf.run import _parse_args

        assert _parse_args([]).strict is False

    def test_strict_flag_activates_strict(self) -> None:
        from perf.run import _parse_args

        assert _parse_args(["--strict"]).strict is True

    def test_default_teardown_only_is_false(self) -> None:
        from perf.run import _parse_args

        assert _parse_args([]).teardown_only is False

    def test_teardown_only_flag(self) -> None:
        from perf.run import _parse_args

        assert _parse_args(["--teardown-only"]).teardown_only is True

    def test_default_no_migrate_is_false(self) -> None:
        from perf.run import _parse_args

        assert _parse_args([]).no_migrate is False

    def test_default_skip_seed_is_false(self) -> None:
        from perf.run import _parse_args

        assert _parse_args([]).skip_seed is False

    def test_default_seed_only_is_false(self) -> None:
        from perf.run import _parse_args

        assert _parse_args([]).seed_only is False

    def test_skip_seed_flag(self) -> None:
        from perf.run import _parse_args

        assert _parse_args(["--skip-seed"]).skip_seed is True

    def test_seed_only_flag(self) -> None:
        from perf.run import _parse_args

        assert _parse_args(["--seed-only"]).seed_only is True

    def test_no_migrate_flag(self) -> None:
        from perf.run import _parse_args

        assert _parse_args(["--no-migrate"]).no_migrate is True


# ─── Skip propre sans infrastructure ─────────────────────────────────────────


class TestRunSkipClean:
    """Sans `DATABASE_URL` ni `PERF_TARGET_URL`, `run.main([])` retourne 0 (skip propre)."""

    def test_main_returns_0_when_no_target_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("PERF_TARGET_URL", raising=False)
        monkeypatch.delenv("PERF_DB_URL", raising=False)
        from perf.run import main

        result = main([])
        assert result == 0

    def test_main_returns_0_on_teardown_only_without_db(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--teardown-only sans base disponible ne plante pas (avertissement et retour 0)."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("PERF_TARGET_URL", raising=False)
        monkeypatch.delenv("PERF_DB_URL", raising=False)
        from perf.run import main

        result = main(["--teardown-only"])
        assert result == 0
