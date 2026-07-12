"""Tests e2e pour #12 — autorisation RBAC + isolation inter-salons.

Groupe TestRbacFullStackE2E (PostgreSQL requis) :
    pile complète : HTTP (TestClient) → gardes → dépôt SQL réel + JWT réel.

Scénarios :
    1. Inscription gérant → connexion → GET /auth/me → 200, role=MANAGER,
       aucun secret dans le corps.
    2. Isolation inter-salons : jeton du gérant A sur le salon du gérant B → 403 ;
       corps du refus sans donnée de B (SqlSalonScopeRepository réel).
    3. Jeton altéré (un caractère de signature modifié) → 401 générique.
    4. Refresh token présenté comme jeton d'accès sur route protégée → 401 ;
       message identique à l'absence de jeton (anti-énumération).
    5. Compte suspendu **après** émission du jeton → la requête suivante → 403
       (preuve que la relecture en base fait autorité, pas le claim JWT).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_rbac_e2e.py -v

Nettoyage : données supprimées avant et après chaque test
(plage réservée : +225073999xxxx ; salons nommés "rbac-e2e-*").
"""

from __future__ import annotations

import datetime
import os
import uuid as _uuid_mod
from collections.abc import Generator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from coiflink_api.adapters.inbound.security import (
    require_authenticated,
    require_salon_scope,
)
from coiflink_api.adapters.outbound.persistence.session import get_engine
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.domain.access import SalonScope
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-rbac-e2e-jwt-secret-not-for-production"

# Plage de numéros réservée aux tests e2e RBAC (formes normalisées +225073999xxxx).
_E2E_PHONE_PREFIX = "+225073999"
_PHONE_A_LOCAL = "0739990001"   # gérant A — scénarios 1, 3, 4, 5
_PHONE_B_LOCAL = "0739990002"   # gérant B — scénario 2 (porteur du salon isolé)
_PASSWORD = "rbac-e2e-strong-password-2024"


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Supprime salons puis comptes de test (FK : salons avant users)."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "DELETE FROM salons WHERE owner_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix)"
            ),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.execute(
            text("DELETE FROM users WHERE phone LIKE :prefix"),
            {"prefix": f"{_E2E_PHONE_PREFIX}%"},
        )
        conn.commit()


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète (PostgreSQL + argon2 + JWT).

    - Injecte un JwtTokenService de test (secret local, jamais en production) sur app.state.
    - Supprime les données de test (plage +225073999) avant et après chaque test.
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e RBAC.")

    orig_token_service = getattr(main_app.state, "token_service", None)
    orig_rate_limiter = getattr(main_app.state, "login_rate_limiter", None)

    main_app.state.token_service = JwtTokenService(
        _TEST_JWT_SECRET,
        access_ttl=datetime.timedelta(minutes=15),
        refresh_ttl=datetime.timedelta(days=30),
    )
    main_app.state.login_rate_limiter = InMemoryLoginRateLimiter(
        max_attempts=5,
        window=datetime.timedelta(minutes=5),
        lockout=datetime.timedelta(minutes=15),
    )

    _wipe_test_data()
    try:
        yield TestClient(main_app)
    finally:
        _wipe_test_data()
        main_app.state.token_service = orig_token_service
        main_app.state.login_rate_limiter = orig_rate_limiter


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _register_manager(client: TestClient, *, phone: str = _PHONE_A_LOCAL) -> str:
    """Inscrit un compte gérant via l'API et retourne son UUID."""
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant E2E RBAC", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription échouée : {resp.text}"
    return resp.json()["id"]


def _login(client: TestClient, *, phone: str = _PHONE_A_LOCAL) -> dict:
    """Connecte un compte et retourne le corps de la réponse (paire de jetons)."""
    resp = client.post(
        "/auth/login", json={"identifier": phone, "password": _PASSWORD}
    )
    assert resp.status_code == 200, f"Connexion échouée : {resp.text}"
    return resp.json()


def _insert_salon(owner_id: str) -> str:
    """Insère un salon pour `owner_id` directement en base (aucune route salon avant #15).

    Retourne l'UUID du salon inséré (format chaîne). Le statut est mis à ACTIVE par
    la valeur par défaut de la colonne.
    """
    engine = get_engine()
    salon_id = str(_uuid_mod.uuid4())
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO salons (id, owner_id, name) "
                "VALUES (:id, :owner_id, :name)"
            ),
            {
                "id": salon_id,
                "owner_id": owner_id,
                "name": f"rbac-e2e-{salon_id[:8]}",
            },
        )
        conn.commit()
    return salon_id


def _make_scope_test_app() -> FastAPI:
    """Mini-app FastAPI avec `require_salon_scope` branchée sur le vrai dépôt SQL.

    Exercice de l'isolation inter-salons avant l'existence de routes salon
    en production (#15). Session DB via `get_session` (lit `DATABASE_URL`) —
    aucun override, toute la chaîne est réelle.
    """
    mini = FastAPI(dependencies=[Depends(require_authenticated)])

    @mini.get("/salons/{salon_id}/rbac-test")
    def _scope_handler(
        scope: Annotated[SalonScope, Depends(require_salon_scope)],
    ) -> dict:
        return {"in_scope": True}

    return mini


# ─── Groupe principal : pile complète (PostgreSQL requis) ─────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestRbacFullStackE2E:
    """RBAC + isolation inter-salons avec JWT réel, argon2 réel et dépôt SQL réel."""

    # ── Scénario 1 : GET /auth/me → 200, role=MANAGER, aucun secret ──────────

    def test_get_me_returns_200_for_manager(self, _e2e_client: TestClient) -> None:
        """Inscription gérant → connexion → GET /auth/me → 200."""
        _register_manager(_e2e_client)
        tokens = _login(_e2e_client)
        resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert resp.status_code == 200

    def test_get_me_role_is_manager(self, _e2e_client: TestClient) -> None:
        """GET /auth/me retourne role=MANAGER (rôle relu en base, pas depuis le claim)."""
        _register_manager(_e2e_client)
        tokens = _login(_e2e_client)
        resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert resp.json()["role"] == "MANAGER"

    def test_get_me_id_matches_registered_account(self, _e2e_client: TestClient) -> None:
        """Le champ id de GET /auth/me correspond à l'UUID de l'inscription."""
        registered_id = _register_manager(_e2e_client)
        tokens = _login(_e2e_client)
        resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert resp.json()["id"] == registered_id

    def test_get_me_contains_no_secret(self, _e2e_client: TestClient) -> None:
        """GET /auth/me ne retourne ni password_hash ni aucun secret (PRD §11.1)."""
        _register_manager(_e2e_client)
        tokens = _login(_e2e_client)
        resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        body = resp.json()
        assert "password" not in body
        assert "password_hash" not in body

    def test_get_me_without_token_returns_401(self, _e2e_client: TestClient) -> None:
        """GET /auth/me sans jeton → 401 (deny-by-default vérifié sur route réelle)."""
        resp = _e2e_client.get("/auth/me")
        assert resp.status_code == 401

    # ── Scénario 2 : isolation inter-salons → 403 ─────────────────────────────

    def test_cross_salon_access_returns_403(self, _e2e_client: TestClient) -> None:
        """Gérant A tente d'accéder au salon de B → 403 (SqlSalonScopeRepository réel).

        Exercice bout-en-bout de `require_salon_scope` sur PostgreSQL :
        `SqlSalonScopeRepository` interroge `salons.owner_id` et refuse A l'accès
        au salon de B, dont il n'est pas propriétaire.
        """
        id_a = _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)  # noqa: F841
        id_b = _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        tokens_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)

        # Insérer un salon pour B directement en base (aucune route salon avant #15)
        salon_b_id = _insert_salon(id_b)

        # Mini-app avec le même token_service que main_app (même secret de test)
        scope_app = _make_scope_test_app()
        scope_app.state.token_service = main_app.state.token_service

        with TestClient(scope_app, raise_server_exceptions=False) as c:
            resp = c.get(
                f"/salons/{salon_b_id}/rbac-test",
                headers={"Authorization": f"Bearer {tokens_a['access_token']}"},
            )

        assert resp.status_code == 403

    def test_cross_salon_403_body_has_no_b_data(self, _e2e_client: TestClient) -> None:
        """Le corps du 403 inter-salons ne contient aucune donnée sur le salon B."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        id_b = _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        tokens_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        salon_b_id = _insert_salon(id_b)

        scope_app = _make_scope_test_app()
        scope_app.state.token_service = main_app.state.token_service

        with TestClient(scope_app, raise_server_exceptions=False) as c:
            resp = c.get(
                f"/salons/{salon_b_id}/rbac-test",
                headers={"Authorization": f"Bearer {tokens_a['access_token']}"},
            )

        body = resp.text
        # Le corps du refus ne doit révéler ni l'ID du salon ni l'ID de B
        assert id_b not in body
        assert salon_b_id not in body

    def test_cross_salon_403_message_is_generic(self, _e2e_client: TestClient) -> None:
        """Le message du 403 inter-salons est identique à celui d'un rôle insuffisant."""
        _register_manager(_e2e_client, phone=_PHONE_A_LOCAL)
        id_b = _register_manager(_e2e_client, phone=_PHONE_B_LOCAL)
        tokens_a = _login(_e2e_client, phone=_PHONE_A_LOCAL)
        salon_b_id = _insert_salon(id_b)

        scope_app = _make_scope_test_app()
        scope_app.state.token_service = main_app.state.token_service

        with TestClient(scope_app, raise_server_exceptions=False) as c:
            resp = c.get(
                f"/salons/{salon_b_id}/rbac-test",
                headers={"Authorization": f"Bearer {tokens_a['access_token']}"},
            )

        assert resp.json()["detail"] == "Accès refusé."

    # ── Scénario 3 : jeton altéré → 401 ──────────────────────────────────────

    def test_tampered_token_returns_401(self, _e2e_client: TestClient) -> None:
        """Jeton dont la signature est modifiée → 401 (HMAC invalide)."""
        _register_manager(_e2e_client)
        tokens = _login(_e2e_client)
        access = tokens["access_token"]
        # Modifier le dernier caractère de la partie signature (après le 2e '.')
        header_payload, signature = access.rsplit(".", 1)
        bad_char = "A" if signature[-1] != "A" else "B"
        tampered = header_payload + "." + signature[:-1] + bad_char

        resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tampered}"}
        )
        assert resp.status_code == 401

    def test_tampered_token_401_includes_www_authenticate(
        self, _e2e_client: TestClient
    ) -> None:
        """Le 401 sur jeton altéré inclut l'en-tête WWW-Authenticate: Bearer."""
        _register_manager(_e2e_client)
        tokens = _login(_e2e_client)
        access = tokens["access_token"]
        header_payload, signature = access.rsplit(".", 1)
        bad_char = "A" if signature[-1] != "A" else "B"
        tampered = header_payload + "." + signature[:-1] + bad_char

        resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tampered}"}
        )
        assert "WWW-Authenticate" in resp.headers

    def test_tampered_token_401_message_is_generic(self, _e2e_client: TestClient) -> None:
        """Le message du 401 est générique — motif exact (signature invalide) non divulgué."""
        _register_manager(_e2e_client)
        tokens = _login(_e2e_client)
        access = tokens["access_token"]
        header_payload, signature = access.rsplit(".", 1)
        bad_char = "A" if signature[-1] != "A" else "B"
        tampered = header_payload + "." + signature[:-1] + bad_char

        resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tampered}"}
        )
        detail = resp.json().get("detail", "")
        assert "signature" not in detail.lower()
        assert "token" not in detail.lower()

    # ── Scénario 4 : refresh token → 401 ─────────────────────────────────────

    def test_refresh_token_used_as_access_returns_401(
        self, _e2e_client: TestClient
    ) -> None:
        """Refresh token présenté en Bearer sur route protégée → 401 (type invalide)."""
        _register_manager(_e2e_client)
        tokens = _login(_e2e_client)
        resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
        )
        assert resp.status_code == 401

    def test_refresh_token_401_message_identical_to_missing_token(
        self, _e2e_client: TestClient
    ) -> None:
        """Le 401 refresh-en-accès et le 401 sans jeton ont le même message (anti-énumération)."""
        _register_manager(_e2e_client)
        tokens = _login(_e2e_client)

        r_refresh = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
        )
        r_none = _e2e_client.get("/auth/me")

        assert r_refresh.json()["detail"] == r_none.json()["detail"]

    # ── Scénario 5 : suspension après émission → 403 ─────────────────────────

    def test_suspended_after_token_issued_returns_403(
        self, _e2e_client: TestClient
    ) -> None:
        """Compte suspendu APRÈS émission → 403 (relecture base fait autorité, pas le claim)."""
        user_id = _register_manager(_e2e_client)
        tokens = _login(_e2e_client)

        # Jeton encore valide avant suspension
        r_before = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert r_before.status_code == 200

        # Suspension en base après émission — le jeton est toujours cryptographiquement valide
        with get_engine().connect() as conn:
            conn.execute(
                text("UPDATE users SET status = 'SUSPENDED' WHERE id = :uid"),
                {"uid": user_id},
            )
            conn.commit()

        # Même jeton → 403 (statut relu en base, pas depuis le claim JWT)
        r_after = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert r_after.status_code == 403

    def test_suspended_account_403_message_is_inactive_account(
        self, _e2e_client: TestClient
    ) -> None:
        """Le 403 pour compte suspendu porte le message 'Compte désactivé.'."""
        user_id = _register_manager(_e2e_client)
        tokens = _login(_e2e_client)

        with get_engine().connect() as conn:
            conn.execute(
                text("UPDATE users SET status = 'SUSPENDED' WHERE id = :uid"),
                {"uid": user_id},
            )
            conn.commit()

        resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert resp.json()["detail"] == "Compte désactivé."

    def test_suspended_account_403_does_not_reveal_pii(
        self, _e2e_client: TestClient
    ) -> None:
        """Le corps du 403 compte suspendu ne divulgue aucune PII (téléphone, e-mail)."""
        user_id = _register_manager(_e2e_client)
        tokens = _login(_e2e_client)

        with get_engine().connect() as conn:
            conn.execute(
                text("UPDATE users SET status = 'SUSPENDED' WHERE id = :uid"),
                {"uid": user_id},
            )
            conn.commit()

        resp = _e2e_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        body = resp.text
        assert _PHONE_A_LOCAL not in body
        assert _E2E_PHONE_PREFIX not in body
