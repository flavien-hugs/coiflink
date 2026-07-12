"""Tests e2e pour US-1.2 — connexion JWT + refresh + anti-bruteforce (#10).

Deux groupes de scénarios :

• TestLoginFullStackE2E (PostgreSQL requis) — exercent la pile complète sans
  aucun mock au-delà des fixtures de test :
    HTTP (TestClient) → cas d'usage → dépôt SQL réel + argon2 + JWT réel.
  Scénarios : inscription→login (téléphone et e-mail), vérification des claims
  du JWT d'accès (sub=user_id, role, type=access, absence de PII), rotation du
  refresh token, accumulation du rate-limiter jusqu'au 429 + Retry-After, et
  reset du compteur d'échecs après une connexion réussie.

• TestRateLimitAccumulationE2E (sans base de données) — N requêtes HTTP
  consécutives accumulent l'état d'un InMemoryLoginRateLimiter réel capturé
  en closure. Seul le dépôt utilisateur est un fake vide (utilisateur toujours
  introuvable → record_failure à chaque requête). Vérifie le déclenchement du
  429 au seuil, la présence de Retry-After, la valeur positive de Retry-After,
  et que le message 429 ne divulgue pas l'identifiant ciblé.

Prérequis (TestLoginFullStackE2E) :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_login_e2e.py -v

Second groupe, sans base :
    pytest tests/test_login_e2e.py::TestRateLimitAccumulationE2E -v

Nettoyage : les données de test sont supprimées avant et après chaque test
(plage de téléphones réservée : +225071999xxxx).
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Generator

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from coiflink_api.adapters.inbound.auth import get_authenticate_user
from coiflink_api.adapters.outbound.persistence.session import get_engine
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.application.authentication import AuthenticateUser
from coiflink_api.main import app

from .conftest import FakeAuthUserRepository, FakeHasher, FakeTokenService

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — ne doit jamais être utilisé en production.
_TEST_JWT_SECRET = "test-only-e2e-jwt-secret-not-for-production-use"

# Plage de numéros réservée aux tests e2e (formes normalisées +225071999xxxx).
_E2E_PHONE_PREFIX = "+225071999"
_PHONE_A_LOCAL = "0719990001"  # → +2250719990001 après normalisation E.164
_PHONE_B_LOCAL = "0719990002"  # réservé aux scénarios de connexion par e-mail
_E2E_EMAIL = "e2e-login@example.com"
_PASSWORD = "correct-horse-battery"

# Seuil d'anti-bruteforce intentionnellement bas : réduit le nombre de requêtes
# nécessaires pour déclencher le 429 dans les scénarios e2e.
_E2E_MAX_ATTEMPTS = 3


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient avec pile réelle (PostgreSQL + argon2 + JWT).

    - Injecte un JwtTokenService de test (secret local) sur app.state.
    - Substitue un InMemoryLoginRateLimiter frais (seuil = _E2E_MAX_ATTEMPTS).
    - Supprime les lignes de test avant et après chaque test (plage +225071999).
    - Skip si DATABASE_URL absent.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e full-stack.")

    orig_token_service = getattr(app.state, "token_service", None)
    orig_rate_limiter = getattr(app.state, "login_rate_limiter", None)

    app.state.token_service = JwtTokenService(
        _TEST_JWT_SECRET,
        access_ttl=datetime.timedelta(minutes=15),
        refresh_ttl=datetime.timedelta(days=30),
    )
    app.state.login_rate_limiter = InMemoryLoginRateLimiter(
        max_attempts=_E2E_MAX_ATTEMPTS,
        window=datetime.timedelta(minutes=5),
        lockout=datetime.timedelta(minutes=15),
    )

    def _wipe() -> None:
        engine = get_engine()
        with engine.connect() as conn:
            # salon_members → users (FK RESTRICT) : supprimer avant users.
            conn.execute(
                text(
                    "DELETE FROM salon_members WHERE user_id IN "
                    "(SELECT id FROM users WHERE phone LIKE :prefix)"
                ),
                {"prefix": f"{_E2E_PHONE_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM users WHERE phone LIKE :prefix"),
                {"prefix": f"{_E2E_PHONE_PREFIX}%"},
            )
            conn.commit()

    _wipe()
    try:
        yield TestClient(app)
    finally:
        _wipe()
        app.state.token_service = orig_token_service
        app.state.login_rate_limiter = orig_rate_limiter


@pytest.fixture()
def _rl_client() -> Generator[TestClient, None, None]:
    """TestClient pour accumulation du rate-limiter via HTTP (sans base).

    Remplace get_authenticate_user par une implémentation dont le dépôt est
    un fake vide (utilisateur toujours introuvable → record_failure à chaque
    tentative) mais dont le rate-limiter est un InMemoryLoginRateLimiter réel
    capturé en closure — l'état s'accumule d'une requête à l'autre.
    """
    rate_limiter = InMemoryLoginRateLimiter(
        max_attempts=_E2E_MAX_ATTEMPTS,
        window=datetime.timedelta(minutes=5),
        lockout=datetime.timedelta(minutes=15),
    )
    dummy_hash = FakeHasher().hash("dummy")

    def _uc() -> AuthenticateUser:
        return AuthenticateUser(
            FakeAuthUserRepository(),  # dépôt vide → utilisateur introuvable
            FakeHasher(),
            FakeTokenService(),
            rate_limiter,  # instance partagée en closure
            dummy_hash=dummy_hash,
        )

    app.dependency_overrides[get_authenticate_user] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_authenticate_user, None)


# ─── Helper ───────────────────────────────────────────────────────────────────


def _register(
    client: TestClient,
    *,
    phone: str = _PHONE_A_LOCAL,
    email: str | None = None,
) -> None:
    """Inscrit un compte de test via l'API réelle et vérifie le 201."""
    payload: dict = {
        "full_name": "Test E2E Login",
        "phone": phone,
        "password": _PASSWORD,
    }
    if email is not None:
        payload["email"] = email
    resp = client.post("/auth/register", json=payload)
    assert resp.status_code == 201, f"Inscription échouée : {resp.text}"


# ─── Groupe 1 : pile complète (PostgreSQL requis) ─────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestLoginFullStackE2E:
    """Inscription → connexion → refresh avec argon2 + JWT réels (PostgreSQL)."""

    # ── Connexion par téléphone ──────────────────────────────────────────────

    def test_login_by_phone_returns_200(self, _e2e_client: TestClient) -> None:
        _register(_e2e_client)
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        assert r.status_code == 200

    def test_login_response_contains_access_token(self, _e2e_client: TestClient) -> None:
        _register(_e2e_client)
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        assert "access_token" in r.json()

    def test_login_response_contains_refresh_token(self, _e2e_client: TestClient) -> None:
        _register(_e2e_client)
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        assert "refresh_token" in r.json()

    def test_login_response_token_type_is_bearer(self, _e2e_client: TestClient) -> None:
        _register(_e2e_client)
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        assert r.json()["token_type"] == "bearer"

    def test_login_response_expires_in_is_positive_int(self, _e2e_client: TestClient) -> None:
        _register(_e2e_client)
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        expires_in = r.json()["expires_in"]
        assert isinstance(expires_in, int)
        assert expires_in > 0

    # ── Claims du JWT d'accès ────────────────────────────────────────────────

    def test_access_token_sub_matches_registered_user_id(
        self, _e2e_client: TestClient
    ) -> None:
        """Le claim `sub` du JWT d'accès correspond à l'UUID de l'utilisateur inscrit."""
        resp_reg = _e2e_client.post(
            "/auth/register",
            json={"full_name": "E2E Claims", "phone": _PHONE_A_LOCAL, "password": _PASSWORD},
        )
        assert resp_reg.status_code == 201
        expected_id = resp_reg.json()["id"]

        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        claims = JwtTokenService(_TEST_JWT_SECRET).decode(r.json()["access_token"])
        assert claims.sub == expected_id

    def test_access_token_role_is_client(self, _e2e_client: TestClient) -> None:
        _register(_e2e_client)
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        claims = JwtTokenService(_TEST_JWT_SECRET).decode(r.json()["access_token"])
        assert claims.role == "CLIENT"

    def test_access_token_type_claim_is_access(self, _e2e_client: TestClient) -> None:
        _register(_e2e_client)
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        claims = JwtTokenService(_TEST_JWT_SECRET).decode(r.json()["access_token"])
        assert claims.type == "access"

    def test_refresh_token_type_claim_is_refresh(self, _e2e_client: TestClient) -> None:
        _register(_e2e_client)
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        claims = JwtTokenService(_TEST_JWT_SECRET).decode(r.json()["refresh_token"])
        assert claims.type == "refresh"

    def test_access_token_contains_no_pii(self, _e2e_client: TestClient) -> None:
        """Aucun claim du JWT d'accès ne transporte de PII (ADR-0013)."""
        _register(_e2e_client)
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        raw = pyjwt.decode(
            r.json()["access_token"], _TEST_JWT_SECRET, algorithms=["HS256"]
        )
        assert set(raw.keys()).issubset({"sub", "role", "type", "iat", "exp", "jti"})

    # ── Connexion par e-mail ─────────────────────────────────────────────────

    def test_login_by_email_returns_200(self, _e2e_client: TestClient) -> None:
        _register(_e2e_client, phone=_PHONE_B_LOCAL, email=_E2E_EMAIL)
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _E2E_EMAIL, "password": _PASSWORD}
        )
        assert r.status_code == 200

    def test_login_by_email_sub_matches_registered_user_id(
        self, _e2e_client: TestClient
    ) -> None:
        resp_reg = _e2e_client.post(
            "/auth/register",
            json={
                "full_name": "E2E Email Login",
                "phone": _PHONE_B_LOCAL,
                "password": _PASSWORD,
                "email": _E2E_EMAIL,
            },
        )
        assert resp_reg.status_code == 201
        expected_id = resp_reg.json()["id"]

        r = _e2e_client.post(
            "/auth/login", json={"identifier": _E2E_EMAIL, "password": _PASSWORD}
        )
        claims = JwtTokenService(_TEST_JWT_SECRET).decode(r.json()["access_token"])
        assert claims.sub == expected_id

    # ── Rotation du refresh token ────────────────────────────────────────────

    def test_refresh_returns_200(self, _e2e_client: TestClient) -> None:
        _register(_e2e_client)
        login_r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        r = _e2e_client.post(
            "/auth/refresh", json={"refresh_token": login_r.json()["refresh_token"]}
        )
        assert r.status_code == 200

    def test_refresh_returns_new_valid_access_token(self, _e2e_client: TestClient) -> None:
        """Le nouvel access token émis par /auth/refresh est distinct et valide."""
        _register(_e2e_client)
        login_r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        original_access = login_r.json()["access_token"]

        r = _e2e_client.post(
            "/auth/refresh", json={"refresh_token": login_r.json()["refresh_token"]}
        )
        new_access = r.json()["access_token"]

        assert new_access != original_access
        claims = JwtTokenService(_TEST_JWT_SECRET).decode(new_access)
        assert claims.type == "access"

    def test_refresh_rotation_new_refresh_token_is_distinct(
        self, _e2e_client: TestClient
    ) -> None:
        """Le refresh token est rotaté : le nouveau est distinct de l'original."""
        _register(_e2e_client)
        login_r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        original_refresh = login_r.json()["refresh_token"]

        r = _e2e_client.post(
            "/auth/refresh", json={"refresh_token": original_refresh}
        )
        assert r.json()["refresh_token"] != original_refresh

    def test_access_token_used_as_refresh_returns_401(self, _e2e_client: TestClient) -> None:
        """Un jeton d'accès est refusé par /auth/refresh (type invalide)."""
        _register(_e2e_client)
        login_r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        r = _e2e_client.post(
            "/auth/refresh", json={"refresh_token": login_r.json()["access_token"]}
        )
        assert r.status_code == 401

    # ── Anti-bruteforce (accumulation réelle via HTTP) ───────────────────────

    def test_wrong_password_accumulates_to_429(self, _e2e_client: TestClient) -> None:
        """_E2E_MAX_ATTEMPTS échecs consécutifs sur un compte réel → 429."""
        _register(_e2e_client)
        for _ in range(_E2E_MAX_ATTEMPTS):
            r = _e2e_client.post(
                "/auth/login",
                json={"identifier": _PHONE_A_LOCAL, "password": "mauvais-mot-de-passe"},
            )
            assert r.status_code == 401

        r = _e2e_client.post(
            "/auth/login",
            json={"identifier": _PHONE_A_LOCAL, "password": "mauvais-mot-de-passe"},
        )
        assert r.status_code == 429

    def test_429_includes_retry_after_header(self, _e2e_client: TestClient) -> None:
        _register(_e2e_client)
        for _ in range(_E2E_MAX_ATTEMPTS):
            _e2e_client.post(
                "/auth/login",
                json={"identifier": _PHONE_A_LOCAL, "password": "wrong"},
            )
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": "wrong"}
        )
        assert "Retry-After" in r.headers

    def test_correct_password_while_locked_still_returns_429(
        self, _e2e_client: TestClient
    ) -> None:
        """Le bon mot de passe est refusé pendant le verrou (check AVANT lookup)."""
        _register(_e2e_client)
        for _ in range(_E2E_MAX_ATTEMPTS):
            _e2e_client.post(
                "/auth/login",
                json={"identifier": _PHONE_A_LOCAL, "password": "wrong"},
            )
        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        assert r.status_code == 429

    def test_success_resets_failure_counter(self, _e2e_client: TestClient) -> None:
        """Une connexion réussie réinitialise le compteur d'échecs.

        Scénario : (_E2E_MAX_ATTEMPTS − 1) échecs → succès → (_E2E_MAX_ATTEMPTS − 1)
        nouveaux échecs → tous 401 (compteur réinitialisé, pas de déclenchement
        prématuré du verrou). Sans reset, la combinaison des deux séries
        déclencherait le verrou à la première tentative de la seconde phase.
        """
        _register(_e2e_client)

        for _ in range(_E2E_MAX_ATTEMPTS - 1):
            r = _e2e_client.post(
                "/auth/login",
                json={"identifier": _PHONE_A_LOCAL, "password": "wrong"},
            )
            assert r.status_code == 401

        r = _e2e_client.post(
            "/auth/login", json={"identifier": _PHONE_A_LOCAL, "password": _PASSWORD}
        )
        assert r.status_code == 200

        for _ in range(_E2E_MAX_ATTEMPTS - 1):
            r = _e2e_client.post(
                "/auth/login",
                json={"identifier": _PHONE_A_LOCAL, "password": "wrong"},
            )
            assert r.status_code == 401


# ─── Groupe 2 : accumulation du rate-limiter via HTTP (sans base) ─────────────


class TestRateLimitAccumulationE2E:
    """N requêtes HTTP accumulent l'état du rate-limiter réel (dépôt fake vide)."""

    def test_sequential_failures_trigger_429_at_threshold(
        self, _rl_client: TestClient
    ) -> None:
        """_E2E_MAX_ATTEMPTS échecs → la requête suivante est bloquée (429)."""
        payload = {"identifier": "0700000000", "password": "wrong"}
        for _ in range(_E2E_MAX_ATTEMPTS):
            r = _rl_client.post("/auth/login", json=payload)
            assert r.status_code == 401

        r = _rl_client.post("/auth/login", json=payload)
        assert r.status_code == 429

    def test_429_includes_retry_after_header(self, _rl_client: TestClient) -> None:
        payload = {"identifier": "0700000000", "password": "wrong"}
        for _ in range(_E2E_MAX_ATTEMPTS):
            _rl_client.post("/auth/login", json=payload)
        r = _rl_client.post("/auth/login", json=payload)
        assert "Retry-After" in r.headers

    def test_retry_after_is_positive_integer(self, _rl_client: TestClient) -> None:
        payload = {"identifier": "0700000000", "password": "wrong"}
        for _ in range(_E2E_MAX_ATTEMPTS):
            _rl_client.post("/auth/login", json=payload)
        r = _rl_client.post("/auth/login", json=payload)
        retry_after = int(r.headers["Retry-After"])
        assert retry_after > 0

    def test_exactly_at_threshold_failure_returns_401_not_429(
        self, _rl_client: TestClient
    ) -> None:
        """Le _E2E_MAX_ATTEMPTS-ième échec passe check() (verrou non encore actif)
        puis pose le verrou via record_failure → réponse 401, pas 429.
        Le 429 n'intervient qu'à la tentative suivante.
        """
        payload = {"identifier": "0700000000", "password": "wrong"}
        for _ in range(_E2E_MAX_ATTEMPTS - 1):
            r = _rl_client.post("/auth/login", json=payload)
            assert r.status_code == 401

        r = _rl_client.post("/auth/login", json=payload)
        assert r.status_code == 401

    def test_429_message_does_not_reveal_identifier(self, _rl_client: TestClient) -> None:
        """Le message 429 est générique et ne divulgue pas l'identifiant ciblé."""
        payload = {"identifier": "0700000000", "password": "wrong"}
        for _ in range(_E2E_MAX_ATTEMPTS):
            _rl_client.post("/auth/login", json=payload)
        r = _rl_client.post("/auth/login", json=payload)
        assert "0700000000" not in r.text
        assert "+225" not in r.text
