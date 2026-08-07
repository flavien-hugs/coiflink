"""Tests de régression pour le déploiement production (issue #54, ADR-0038).

Couvre les invariants *statiques* et *unitaires* introduits par #54 :

1. Artefacts documentaires (ADR-0038, docs/mise-en-production.md) — existence,
   statut, sections obligatoires, cross-liens.
2. Décision liveness-only (ADR-0038 §3) — ``/health/ready`` n'est pas ajouté à
   ``PUBLIC_ROUTE_PATHS`` ; ``health.py`` n'expose qu'un endpoint ``/health`` pur
   (pas d'accès base, pas d'import de session).
3. Suivi d'erreurs différé (ADR-0038 §4) — ``SENTRY_DSN`` absent de tous les
   ``*.env.example`` et du code applicatif (#54 déclare explicitement ne pas câbler
   Sentry).
4. Config Railway inchangée (ADR-0038 §3) — ``deploy/railway/backend.json`` et
   ``deploy/railway/web.json`` conservent les valeurs décidées (``healthcheckPath``,
   ``restartPolicyType``, ``restartPolicyMaxRetries``).
5. HTTP : ``GET /health`` reste une sonde de liveness (200 + ``{"status":"ok"}``)
   accessible **sans** jeton (deny-by-default non cassé par #54).

Aucune infrastructure live n'est requise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constantes de chemin
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"
ADR_DIR = DOCS_DIR / "adr"
DEPLOY_DIR = REPO_ROOT / "deploy"
BACKEND_DIR = REPO_ROOT / "backend"
HEALTH_PY = BACKEND_DIR / "coiflink_api" / "adapters" / "inbound" / "health.py"
SECURITY_PY = BACKEND_DIR / "coiflink_api" / "adapters" / "inbound" / "security.py"

ADR_0038 = ADR_DIR / "0038-observabilite-monitoring-rollback.md"
MISE_EN_PROD = DOCS_DIR / "mise-en-production.md"


# ===========================================================================
# 1. Artefacts documentaires — ADR-0038
# ===========================================================================


class TestAdr0038Exists:
    """ADR-0038 doit exister, être accepté et couvrir les décisions de #54."""

    def test_adr_0038_file_exists(self) -> None:
        assert ADR_0038.exists(), (
            "docs/adr/0038-observabilite-monitoring-rollback.md doit être créé par #54."
        )

    def test_adr_0038_status_accepted(self) -> None:
        content = ADR_0038.read_text()
        assert re.search(r"Accepté", content), (
            "ADR-0038 doit porter le statut « Accepté »."
        )

    def test_adr_0038_indexed_in_adr_readme(self) -> None:
        readme = (ADR_DIR / "README.md").read_text()
        assert "0038" in readme, (
            "docs/adr/README.md doit référencer ADR-0038 dans son index."
        )

    def test_adr_0038_references_issue_54(self) -> None:
        content = ADR_0038.read_text()
        assert "#54" in content, (
            "ADR-0038 doit référencer l'issue #54 (Déploiement production)."
        )

    def test_adr_0038_covers_liveness_only_decision(self) -> None:
        content = ADR_0038.read_text().lower()
        assert "liveness" in content, (
            "ADR-0038 doit documenter la décision liveness-only (Option A, §3)."
        )

    def test_adr_0038_covers_rollback_strategy(self) -> None:
        content = ADR_0038.read_text().lower()
        assert "rollback" in content, (
            "ADR-0038 doit documenter la stratégie de rollback."
        )

    def test_adr_0038_covers_alerting_non_pii(self) -> None:
        """Le monitoring ne doit jamais exposer de PII ni de secret dans les alertes."""
        content = ADR_0038.read_text().lower()
        assert "pii" in content or "jamais" in content, (
            "ADR-0038 doit affirmer l'invariant non-PII / non-secret des alertes (§11.3/§11.4)."
        )

    def test_adr_0038_does_not_announce_sentry_as_delivered(self) -> None:
        """ADR-0038 différé Sentry — il ne doit pas l'annoncer comme livré (#54 §4)."""
        content = ADR_0038.read_text().lower()
        # L'ADR mentionne Sentry comme optionnel/différé, jamais comme livré.
        # On cherche la présence de l'invariant « non livré » ou « optionnel ».
        assert "optionnel" in content or "différé" in content or "non livr" in content, (
            "ADR-0038 doit qualifier le suivi d'erreurs applicatif de « optionnel/différé » "
            "et non de livré — ne pas impliquer une intégration inexistante."
        )

    def test_adr_0038_references_mise_en_production(self) -> None:
        content = ADR_0038.read_text()
        assert "mise-en-production" in content, (
            "ADR-0038 doit cross-linker docs/mise-en-production.md."
        )

    def test_adr_readme_monitoring_decision_is_resolved(self) -> None:
        """docs/adr/README.md doit marquer monitoring/alerting §12.2 comme tranché."""
        content = (ADR_DIR / "README.md").read_text().lower()
        assert "0038" in content, (
            "docs/adr/README.md doit indiquer qu'ADR-0038 tranche monitoring/alerting §12.2."
        )


# ===========================================================================
# 2. Artefacts documentaires — docs/mise-en-production.md
# ===========================================================================


class TestMiseEnProductionDoc:
    """docs/mise-en-production.md doit exister et couvrir toutes les sections obligatoires."""

    def test_mise_en_production_exists(self) -> None:
        assert MISE_EN_PROD.exists(), (
            "docs/mise-en-production.md doit être créé par #54."
        )

    def test_mise_en_production_has_monitoring_section(self) -> None:
        content = MISE_EN_PROD.read_text().lower()
        assert "monitoring" in content or "alerting" in content, (
            "docs/mise-en-production.md doit contenir une section monitoring & alerting."
        )

    def test_mise_en_production_has_backup_section(self) -> None:
        content = MISE_EN_PROD.read_text().lower()
        assert "sauvegardes" in content or "sauvegarde" in content, (
            "docs/mise-en-production.md doit contenir une section sauvegardes vérifiées."
        )

    def test_mise_en_production_has_rollback_section(self) -> None:
        content = MISE_EN_PROD.read_text().lower()
        assert "rollback" in content, (
            "docs/mise-en-production.md doit contenir un runbook de rollback."
        )

    def test_mise_en_production_has_smoke_tests(self) -> None:
        content = MISE_EN_PROD.read_text().lower()
        assert "smoke" in content or "/health" in content, (
            "docs/mise-en-production.md doit documenter les smoke tests production."
        )

    def test_mise_en_production_non_pii_alerting_invariant(self) -> None:
        """Les alertes ne doivent jamais contenir PII/secret (PRD §11.3/§11.4)."""
        content = MISE_EN_PROD.read_text().lower()
        assert "pii" in content or "jamais" in content, (
            "docs/mise-en-production.md doit rappeler l'invariant non-PII / non-secret "
            "des alertes (§11.3/§11.4)."
        )

    def test_mise_en_production_references_adr_0038(self) -> None:
        content = MISE_EN_PROD.read_text()
        assert "0038" in content, (
            "docs/mise-en-production.md doit cross-linker ADR-0038."
        )

    def test_mise_en_production_has_backup_verification_journal(self) -> None:
        """Le journal de vérification des sauvegardes doit être présent (#54 §3.3)."""
        content = MISE_EN_PROD.read_text().lower()
        assert "journal" in content or "rto" in content or "rpo" in content, (
            "docs/mise-en-production.md doit contenir le journal de vérification des "
            "sauvegardes (RPO/RTO, critère d'acceptation #54)."
        )

    def test_mise_en_production_liveness_only_mentioned(self) -> None:
        """La décision liveness-only (ADR-0038 §3) doit être documentée."""
        content = MISE_EN_PROD.read_text().lower()
        assert "liveness" in content or "readiness" in content, (
            "docs/mise-en-production.md doit mentionner la décision liveness-only."
        )

    def test_mise_en_production_no_real_secret_placeholder(self) -> None:
        """Le document ne doit contenir aucune valeur ressemblant à un vrai secret."""
        _SUSPICIOUS = re.compile(
            r"ghp_[A-Za-z0-9]{36,}"
            r"|ghs_[A-Za-z0-9]{36,}"
            r"|sk-[A-Za-z0-9]{20,}"
            r"|Bearer [A-Za-z0-9+/=]{20,}"
        )
        content = MISE_EN_PROD.read_text()
        assert not _SUSPICIOUS.search(content), (
            "docs/mise-en-production.md contient un motif ressemblant à un vrai token/secret."
        )

    def test_mise_en_production_cross_linked_from_environnements_doc(self) -> None:
        """docs/environnements-et-secrets.md doit cross-linker docs/mise-en-production.md."""
        env_doc = (DOCS_DIR / "environnements-et-secrets.md").read_text()
        assert "mise-en-production" in env_doc, (
            "docs/environnements-et-secrets.md doit renvoyer vers docs/mise-en-production.md "
            "(parité prod exécutée — §4/§5)."
        )

    def test_readme_references_mise_en_production(self) -> None:
        """README.md (racine) doit référencer docs/mise-en-production.md."""
        readme = (REPO_ROOT / "README.md").read_text()
        assert "mise-en-production" in readme, (
            "README.md doit cross-linker docs/mise-en-production.md (§4 Déploiement / §6 M6)."
        )


# ===========================================================================
# 3. Décision liveness-only — /health/ready n'est PAS ajouté (Option A)
# ===========================================================================


class TestLivenessOnlyDecision:
    """Régression : #54 a retenu l'Option A (liveness-only).

    Aucune sonde de readiness (``/health/ready``, ``/health/db``) ne doit être
    introduite ni listée dans ``PUBLIC_ROUTE_PATHS`` — sauf décision explicite
    inverse documentée dans un ADR de suivi.
    """

    def test_health_ready_not_in_public_route_paths(self) -> None:
        """/health/ready ne figure pas dans PUBLIC_ROUTE_PATHS (Option B non retenue)."""
        from coiflink_api.adapters.inbound.security import PUBLIC_ROUTE_PATHS

        for path in PUBLIC_ROUTE_PATHS:
            assert "/health/ready" not in path, (
                f"/health/ready a été ajouté à PUBLIC_ROUTE_PATHS ({path!r}) alors que "
                "l'Option A (liveness-only) est retenue par ADR-0038 §3. "
                "Mettre à jour l'ADR avant d'élargir la surface publique."
            )

    def test_health_db_not_in_public_route_paths(self) -> None:
        """/health/db (alias readiness) ne figure pas dans PUBLIC_ROUTE_PATHS."""
        from coiflink_api.adapters.inbound.security import PUBLIC_ROUTE_PATHS

        for path in PUBLIC_ROUTE_PATHS:
            assert "/health/db" not in path, (
                f"/health/db a été ajouté à PUBLIC_ROUTE_PATHS ({path!r}) — "
                "variante de readiness non retenue (ADR-0038 §3, Option A)."
            )

    def test_health_py_only_exposes_health_endpoint(self) -> None:
        """health.py ne déclare qu'une seule route GET /health (pas /health/ready)."""
        source = HEALTH_PY.read_text()
        # Aucune mention d'une route /health/ready ou /health/db
        assert "/health/ready" not in source, (
            "health.py déclare /health/ready — l'Option B (readiness) n'est pas retenue "
            "(ADR-0038 §3). Mettre à jour l'ADR avant d'ajouter cette route."
        )
        assert "/health/db" not in source, (
            "health.py déclare /health/db — variante readiness non retenue (ADR-0038 §3)."
        )

    def test_health_py_has_no_db_session_import(self) -> None:
        """health.py (liveness pure) ne doit importer aucun module de session/ORM."""
        source = HEALTH_PY.read_text()
        # Un import de session ou de SQLAlchemy indiquerait un accès base → readiness
        db_imports = re.findall(
            r"(?:from|import)\s+[^\n]*(?:session|sqlalchemy|Session|get_session)",
            source,
        )
        assert not db_imports, (
            f"health.py importe un module de session DB : {db_imports} — "
            "/health doit rester une liveness pure sans accès base (ADR-0038 §3)."
        )

    def test_health_py_has_no_select_statement(self) -> None:
        """health.py ne doit contenir aucun SELECT (pas d'accès base, liveness pure)."""
        source = HEALTH_PY.read_text()
        assert "SELECT" not in source.upper(), (
            "health.py contient un SELECT — /health ne doit pas accéder à la base "
            "(liveness pure, ADR-0038 §3, Option A)."
        )

    def test_health_endpoint_accessible_without_token(self) -> None:
        """/health est public (dans PUBLIC_ROUTE_PATHS) et répond 200 sans jeton."""
        from fastapi.testclient import TestClient

        from coiflink_api.main import app

        with TestClient(app, raise_server_exceptions=True) as client:
            response = client.get("/health")

        assert response.status_code == 200, (
            f"/health a retourné {response.status_code} au lieu de 200 — "
            "la sonde de liveness doit rester accessible (deny-by-default non cassé)."
        )

    def test_health_endpoint_returns_status_ok(self) -> None:
        """/health renvoie {\"status\": \"ok\"} — contrat inchangé après #54."""
        from fastapi.testclient import TestClient

        from coiflink_api.main import app

        with TestClient(app, raise_server_exceptions=True) as client:
            response = client.get("/health")

        assert response.json() == {"status": "ok"}, (
            f"Payload /health inattendu : {response.json()!r} — "
            "le contrat de la sonde de liveness ne doit pas changer."
        )

    def test_health_in_public_route_paths(self) -> None:
        """/health est bien listé dans PUBLIC_ROUTE_PATHS (exemption deny-by-default)."""
        from coiflink_api.adapters.inbound.security import PUBLIC_ROUTE_PATHS

        assert "/health" in PUBLIC_ROUTE_PATHS, (
            "/health a disparu de PUBLIC_ROUTE_PATHS — la sonde de liveness serait "
            "bloquée par le deny-by-default (ADR-0015)."
        )


# ===========================================================================
# 4. Suivi d'erreurs différé — SENTRY_DSN absent de tous les env.example
# ===========================================================================


class TestSentryDsnNotIntroduced:
    """#54 ne câble pas Sentry — SENTRY_DSN ne doit figurer dans aucun .env.example.

    « Ne pas impliquer qu'une intégration existe si elle n'est pas câblée »
    (ADR-0038 §4, spec §2 Non-Goals).
    """

    @staticmethod
    def _has_sentry_var(path: Path) -> bool:
        if not path.exists():
            return False
        lines = path.read_text().splitlines()
        return any(
            re.match(r"^\s*SENTRY_DSN\s*=", line)
            for line in lines
            if not line.strip().startswith("#")
        )

    def test_backend_env_example_no_sentry_dsn(self) -> None:
        assert not self._has_sentry_var(BACKEND_DIR / ".env.example"), (
            "backend/.env.example contient SENTRY_DSN — #54 a explicitement différé "
            "le suivi d'erreurs (ADR-0038 §4) : ne pas le déclarer tant qu'il n'est "
            "pas réellement câblé."
        )

    def test_deploy_env_example_no_sentry_dsn(self) -> None:
        assert not self._has_sentry_var(DEPLOY_DIR / ".env.example"), (
            "deploy/.env.example contient SENTRY_DSN — idem ADR-0038 §4."
        )

    def test_health_py_no_sentry_import(self) -> None:
        """health.py ne doit pas importer de SDK Sentry (non câblé, non impliqué)."""
        source = HEALTH_PY.read_text()
        assert "sentry" not in source.lower(), (
            "health.py importe sentry — #54 n'introduit pas de suivi d'erreurs "
            "(ADR-0038 §4)."
        )

    def test_main_py_no_sentry_import(self) -> None:
        """main.py ne doit pas importer de SDK Sentry (non câblé, non impliqué)."""
        main_py = BACKEND_DIR / "coiflink_api" / "main.py"
        source = main_py.read_text()
        assert "sentry" not in source.lower(), (
            "main.py importe sentry — #54 n'introduit pas de suivi d'erreurs "
            "(ADR-0038 §4). Mettre à jour l'ADR si ce choix change."
        )


# ===========================================================================
# 5. Config Railway inchangée (ADR-0038 §3 — deploy/railway/*.json)
# ===========================================================================


class TestRailwayConfigUnchanged:
    """deploy/railway/backend.json et web.json conservent les valeurs décidées.

    ADR-0038 §3 : le ``healthcheckPath`` reste ``/health`` / ``/`` ; le
    ``restartPolicyType`` reste ``ON_FAILURE`` ; ``restartPolicyMaxRetries: 10``.
    Ces valeurs **ne doivent pas** être modifiées sans décision ADR explicite
    (notamment, ``healthcheckPath`` ne doit jamais pointer vers une sonde de
    readiness — risque de *restart storm*).
    """

    @pytest.fixture
    def backend_cfg(self) -> dict:
        return json.loads((DEPLOY_DIR / "railway" / "backend.json").read_text())

    @pytest.fixture
    def web_cfg(self) -> dict:
        return json.loads((DEPLOY_DIR / "railway" / "web.json").read_text())

    # backend.json

    def test_backend_healthcheck_path_is_health(self, backend_cfg: dict) -> None:
        assert backend_cfg["deploy"]["healthcheckPath"] == "/health", (
            "backend.json : healthcheckPath a changé — seul /health est autorisé "
            "comme sonde de déploiement (ADR-0038 §3 : ne pas y brancher /health/ready)."
        )

    def test_backend_restart_policy_is_on_failure(self, backend_cfg: dict) -> None:
        assert backend_cfg["deploy"]["restartPolicyType"] == "ON_FAILURE", (
            "backend.json : restartPolicyType a changé — ON_FAILURE est requis "
            "pour le redémarrage automatique (ADR-0038 §1)."
        )

    def test_backend_restart_policy_max_retries_is_10(self, backend_cfg: dict) -> None:
        assert backend_cfg["deploy"]["restartPolicyMaxRetries"] == 10, (
            "backend.json : restartPolicyMaxRetries a changé de 10 — valeur décidée "
            "par ADR-0011/ADR-0038 (protection contre les restart storms)."
        )

    def test_backend_num_replicas_is_1(self, backend_cfg: dict) -> None:
        assert backend_cfg["deploy"]["numReplicas"] == 1, (
            "backend.json : numReplicas a changé — valeur MVP décidée par ADR-0011."
        )

    def test_backend_builder_is_dockerfile(self, backend_cfg: dict) -> None:
        assert backend_cfg["build"]["builder"] == "DOCKERFILE", (
            "backend.json : builder a changé — DOCKERFILE est requis (deploy-from-source)."
        )

    # web.json

    def test_web_healthcheck_path_is_root(self, web_cfg: dict) -> None:
        assert web_cfg["deploy"]["healthcheckPath"] == "/", (
            "web.json : healthcheckPath a changé — / est le point de santé du frontend."
        )

    def test_web_restart_policy_is_on_failure(self, web_cfg: dict) -> None:
        assert web_cfg["deploy"]["restartPolicyType"] == "ON_FAILURE", (
            "web.json : restartPolicyType a changé — ON_FAILURE requis (ADR-0038 §1)."
        )

    def test_web_restart_policy_max_retries_is_10(self, web_cfg: dict) -> None:
        assert web_cfg["deploy"]["restartPolicyMaxRetries"] == 10, (
            "web.json : restartPolicyMaxRetries a changé de 10."
        )

    def test_web_builder_is_dockerfile(self, web_cfg: dict) -> None:
        assert web_cfg["build"]["builder"] == "DOCKERFILE", (
            "web.json : builder a changé — DOCKERFILE requis (deploy-from-source)."
        )

    # Invariant commun : aucun secret dans les JSONs Railway

    def test_backend_json_no_database_url_value(self, backend_cfg: dict) -> None:
        """backend.json ne doit pas contenir DATABASE_URL avec une vraie valeur."""
        raw = (DEPLOY_DIR / "railway" / "backend.json").read_text()
        assert "DATABASE_URL" not in raw or "postgres://" not in raw.lower(), (
            "backend.json contient une valeur DATABASE_URL — les secrets doivent "
            "vivre dans le magasin Railway, jamais dans le dépôt."
        )

    def test_web_json_no_jwt_secret_value(self, web_cfg: dict) -> None:
        """web.json ne doit pas contenir JWT_SECRET avec une vraie valeur."""
        raw = (DEPLOY_DIR / "railway" / "web.json").read_text()
        assert "JWT_SECRET" not in raw or '""' in raw or "= " not in raw, (
            "web.json contient JWT_SECRET — les secrets backend ne doivent jamais "
            "figurer dans la config Railway du frontend."
        )

    def test_web_num_replicas_is_1(self, web_cfg: dict) -> None:
        assert web_cfg["deploy"]["numReplicas"] == 1, (
            "web.json : numReplicas a changé — valeur MVP décidée par ADR-0011."
        )


# ===========================================================================
# 6. Invariant deny-by-default non cassé par #54
# ===========================================================================


class TestDenyByDefaultNotBroken:
    """#54 ne modifie pas le code applicatif (Option A) — unprotected_routes doit rester vide."""

    def test_no_new_unprotected_routes_after_54(self) -> None:
        """unprotected_routes(app) doit rester vide — #54 n'ajoute aucune route."""
        from coiflink_api.adapters.inbound.security import unprotected_routes
        from coiflink_api.main import app

        bad = unprotected_routes(app)
        assert bad == [], (
            f"Routes non protégées introduites après #54 : {bad} — "
            "toute nouvelle route doit être soit dans PUBLIC_ROUTE_PATHS (après revue) "
            "soit protégée par une garde de Principal."
        )

    def test_health_is_only_technical_public_route_for_54(self) -> None:
        """/health est la seule route publique technique de monitoring (#54 Option A).

        Si /health/ready ou /health/db apparaît dans PUBLIC_ROUTE_PATHS, la
        décision ADR-0038 §3 a changé sans mise à jour de l'ADR.
        """
        from coiflink_api.adapters.inbound.security import PUBLIC_ROUTE_PATHS

        readiness_paths = [
            p for p in PUBLIC_ROUTE_PATHS
            if p.startswith("/health") and p != "/health"
        ]
        assert readiness_paths == [], (
            f"Des chemins /health/* ont été ajoutés à PUBLIC_ROUTE_PATHS : "
            f"{readiness_paths} — l'Option B (readiness) n'est pas retenue "
            "par ADR-0038 §3. Mettre à jour l'ADR avant d'élargir la surface publique."
        )


# ===========================================================================
# 7. Structure de l'ADR-0038 — sections obligatoires
# ===========================================================================


class TestAdr0038Structure:
    """ADR-0038 doit respecter le format ADR-0000 (Contexte, Options, Décision, Conséquences)."""

    def test_adr_0038_has_contexte_section(self) -> None:
        content = ADR_0038.read_text()
        assert "## Contexte" in content or "## Contexte et problème" in content, (
            "ADR-0038 doit comporter une section Contexte (format ADR-0000)."
        )

    def test_adr_0038_has_options_section(self) -> None:
        content = ADR_0038.read_text()
        assert "## Options" in content, (
            "ADR-0038 doit comporter une section Options (format ADR-0000)."
        )

    def test_adr_0038_has_decision_section(self) -> None:
        content = ADR_0038.read_text()
        assert "## Décision" in content, (
            "ADR-0038 doit comporter une section Décision (format ADR-0000)."
        )

    def test_adr_0038_has_consequences_section(self) -> None:
        content = ADR_0038.read_text()
        assert "## Conséquences" in content, (
            "ADR-0038 doit comporter une section Conséquences (format ADR-0000)."
        )

    def test_adr_0038_references_adr_0011(self) -> None:
        """ADR-0038 s'appuie sur ADR-0011 (socle Railway) — doit le référencer."""
        content = ADR_0038.read_text()
        assert "0011" in content, (
            "ADR-0038 doit référencer ADR-0011 (socle de déploiement Railway)."
        )

    def test_adr_0038_references_adr_0015(self) -> None:
        """ADR-0038 touche PUBLIC_ROUTE_PATHS — doit référencer ADR-0015 (deny-by-default)."""
        content = ADR_0038.read_text()
        assert "0015" in content, (
            "ADR-0038 doit référencer ADR-0015 (deny-by-default, PUBLIC_ROUTE_PATHS)."
        )


# ===========================================================================
# 8. Scan de secrets sur tous les artefacts ajoutés/modifiés par #54
# ===========================================================================

_SECRET_PATTERNS = re.compile(
    r"ghp_[A-Za-z0-9]{36,}"            # GitHub Personal Access Token
    r"|ghs_[A-Za-z0-9]{36,}"           # GitHub Actions token
    r"|sk-[A-Za-z0-9]{20,}"            # OpenAI / Stripe style secret key
    r"|Bearer [A-Za-z0-9+/=]{20,}"     # Bearer token in plain text
    r"|postgresql://[^:]+:[^@]{4,}@"   # DSN with real credentials
    r"|redis://[^:]+:[^@]{4,}@"        # Redis DSN with password
)


class TestSecretScanNewArtefacts:
    """Aucun des artefacts ajoutés ou modifiés par #54 ne doit contenir de vrai secret.

    Scan sur les motifs les plus courants : tokens GitHub, clés SK-*, Bearer tokens
    en clair, DSN avec identifiants réels (postgresql://user:pass@...).
    L'absence de toute détection est un invariant non-PII / non-secret (PRD §11.3/§11.4).
    """

    def _scan(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        return _SECRET_PATTERNS.findall(path.read_text())

    def test_adr_0038_no_real_secret(self) -> None:
        hits = self._scan(ADR_0038)
        assert not hits, (
            f"docs/adr/0038-observabilite-monitoring-rollback.md contient un motif "
            f"ressemblant à un vrai secret : {hits}"
        )

    def test_adr_readme_no_real_secret(self) -> None:
        hits = self._scan(ADR_DIR / "README.md")
        assert not hits, (
            f"docs/adr/README.md contient un motif ressemblant à un vrai secret : {hits}"
        )

    def test_environnements_doc_no_real_secret(self) -> None:
        hits = self._scan(DOCS_DIR / "environnements-et-secrets.md")
        assert not hits, (
            f"docs/environnements-et-secrets.md contient un motif ressemblant à un vrai "
            f"secret : {hits}"
        )

    def test_backend_json_no_real_secret(self) -> None:
        hits = self._scan(DEPLOY_DIR / "railway" / "backend.json")
        assert not hits, (
            f"deploy/railway/backend.json contient un motif ressemblant à un vrai "
            f"secret : {hits}"
        )

    def test_web_json_no_real_secret(self) -> None:
        hits = self._scan(DEPLOY_DIR / "railway" / "web.json")
        assert not hits, (
            f"deploy/railway/web.json contient un motif ressemblant à un vrai "
            f"secret : {hits}"
        )


# ===========================================================================
# 9. Conformité des fichiers .env.example — SENTRY_DSN absent partout
# ===========================================================================


class TestAllEnvExamplesNoSentryDsn:
    """SENTRY_DSN ne doit figurer dans aucun des trois *.env.example du dépôt.

    Complète TestSentryDsnNotIntroduced qui ne couvre que backend/ et deploy/.
    web-dashboard/.env.example est vérifié ici (#54 n'introduit pas Sentry).
    """

    @staticmethod
    def _has_sentry_var(path: Path) -> bool:
        if not path.exists():
            return False
        return any(
            re.match(r"^\s*SENTRY_DSN\s*=", line)
            for line in path.read_text().splitlines()
            if not line.strip().startswith("#")
        )

    def test_web_dashboard_env_example_no_sentry_dsn(self) -> None:
        assert not self._has_sentry_var(REPO_ROOT / "web-dashboard" / ".env.example"), (
            "web-dashboard/.env.example contient SENTRY_DSN — #54 a explicitement "
            "différé le suivi d'erreurs (ADR-0038 §4) : ne pas le déclarer tant "
            "qu'il n'est pas réellement câblé."
        )


# ===========================================================================
# 10. Liens croisés complets — README, ADR, docs
# ===========================================================================


class TestCrossLinksComplete:
    """Vérifie les renvois bidirectionnels entre les nouveaux artefacts de #54."""

    def test_readme_references_adr_0038(self) -> None:
        """README.md doit référencer ADR-0038 (§4 Déploiement — observabilité/rollback)."""
        readme = (REPO_ROOT / "README.md").read_text()
        assert "0038" in readme, (
            "README.md doit cross-linker ADR-0038 dans la section Déploiement (§4)."
        )

    def test_mise_en_production_references_adr_0011(self) -> None:
        """docs/mise-en-production.md doit référencer ADR-0011 (socle Railway)."""
        content = MISE_EN_PROD.read_text()
        assert "0011" in content, (
            "docs/mise-en-production.md doit référencer ADR-0011 (socle Railway, "
            "région europe-west4, politique de sauvegardes)."
        )

    def test_adr_readme_references_mise_en_production(self) -> None:
        """docs/adr/README.md doit pointer vers docs/mise-en-production.md."""
        content = (ADR_DIR / "README.md").read_text()
        assert "mise-en-production" in content, (
            "docs/adr/README.md doit cross-linker docs/mise-en-production.md "
            "(section décisions différées — sauvegardes & monitoring tranchés par #54)."
        )
