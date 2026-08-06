"""Protection **brute-force** de `POST /auth/login` de bout en bout (#51, §11.1).

L'unitaire existe déjà (`test_login_rate_limiter.py`, `test_login_api.py`) ; cette
suite prouve le verrou **sur la pile HTTP réelle** contre `/auth/login`, avec un
`InMemoryLoginRateLimiter` de test aux seuils déterministes injecté sur `app.state`
(patron `test_rbac_e2e.py`) :

- N échecs sur le **même** identifiant → au dépassement, `429` + `Retry-After` ;
- **anti-énumération** : `401` **générique et identique** (`"Identifiants
  invalides."`) pour compte inconnu et mot de passe faux — jamais un `422` qui
  divulguerait la politique de mot de passe ;
- un **succès réinitialise** le compteur ;
- clé **par identifiant** : verrouiller A ne verrouille pas B (défense contre le
  verrouillage trivial d'un tiers). *(La dimension IP de la clé reste unitaire —
  `TestClient` présente une IP de pair constante, cf. `test_login_rate_limiter.py`.)*
- reset OTP : `/auth/password/reset/request` répond **toujours** `202` (générique).

Prérequis :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_security_bruteforce_e2e.py -v

Nettoyage : plage de téléphones réservée `+225089992xxxx`.
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from coiflink_api.adapters.outbound.persistence.session import get_engine
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.main import app as main_app

# ─── Constantes ───────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_TEST_JWT_SECRET = "test-only-security-bruteforce-e2e-jwt-secret-not-for-production"

_E2E_PHONE_PREFIX = "+225089992"
_PHONE_A = "0899920001"
_PHONE_B = "0899920002"
_PASSWORD = "security-bruteforce-e2e-strong-password-2024"
_WRONG_PASSWORD = "wrong-password-attempt-0000"

# Seuils déterministes du limiteur de test (cf. valeurs de `test_rbac_e2e.py`).
_MAX_ATTEMPTS = 5

_INVALID_CREDENTIALS_DETAIL = "Identifiants invalides."


# ─── Nettoyage ────────────────────────────────────────────────────────────────


def _wipe_test_data() -> None:
    """Cette suite ne crée que des comptes : supprime les users de la plage réservée."""

    engine = get_engine()
    with engine.connect() as conn:
        params = {"prefix": f"{_E2E_PHONE_PREFIX}%"}
        # Défensif (aucun salon créé ici, mais l'ordre reste FK-safe si cela évolue).
        conn.execute(
            text(
                "DELETE FROM salon_members WHERE user_id IN "
                "(SELECT id FROM users WHERE phone LIKE :prefix)"
            ),
            params,
        )
        conn.execute(text("DELETE FROM users WHERE phone LIKE :prefix"), params)
        conn.commit()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _e2e_client() -> Generator[TestClient, None, None]:
    """TestClient pile complète, avec un limiteur de connexion **déterministe** dédié.

    Un limiteur neuf par test (fenêtre 300 s, verrou 900 s, seuil 5) garantit
    l'isolation : l'état d'un test ne verrouille jamais le suivant.
    """

    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e de brute-force.")

    orig_token_service = getattr(main_app.state, "token_service", None)
    orig_rate_limiter = getattr(main_app.state, "login_rate_limiter", None)

    main_app.state.token_service = JwtTokenService(
        _TEST_JWT_SECRET,
        access_ttl=datetime.timedelta(minutes=15),
        refresh_ttl=datetime.timedelta(days=30),
    )
    main_app.state.login_rate_limiter = InMemoryLoginRateLimiter(
        max_attempts=_MAX_ATTEMPTS,
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


def _register_manager(client: TestClient, *, phone: str) -> None:
    resp = client.post(
        "/auth/register/manager",
        json={"full_name": "Gérant Brute-Force", "phone": phone, "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Inscription échouée ({phone}) : {resp.text}"


def _login(client: TestClient, *, identifier: str, password: str) -> object:
    return client.post("/auth/login", json={"identifier": identifier, "password": password})


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestLoginBruteForceE2E:
    """Verrou anti-bruteforce de `POST /auth/login` sur la pile réelle."""

    def test_lockout_after_threshold_returns_429_with_retry_after(
        self, _e2e_client: TestClient
    ) -> None:
        """`_MAX_ATTEMPTS` échecs → l'attaque suivante est verrouillée (`429` + `Retry-After`)."""

        client = _e2e_client
        _register_manager(client, phone=_PHONE_A)

        # Les `_MAX_ATTEMPTS` premiers échecs restent des 401 (le seuil verrouille au dernier).
        for _ in range(_MAX_ATTEMPTS):
            resp = _login(client, identifier=_PHONE_A, password=_WRONG_PASSWORD)
            assert resp.status_code == 401, f"Attendu 401 avant seuil, reçu {resp.status_code}"

        locked = _login(client, identifier=_PHONE_A, password=_WRONG_PASSWORD)
        assert locked.status_code == 429
        assert "Retry-After" in locked.headers
        assert int(locked.headers["Retry-After"]) > 0

        # Le verrou tient même avec le **bon** mot de passe (l'attaquant ne s'en sort pas).
        even_correct = _login(client, identifier=_PHONE_A, password=_PASSWORD)
        assert even_correct.status_code == 429

    def test_anti_enumeration_identical_401_for_unknown_and_wrong_password(
        self, _e2e_client: TestClient
    ) -> None:
        """Compte inconnu et mot de passe faux → **même** `401` générique (jamais `422`)."""

        client = _e2e_client
        _register_manager(client, phone=_PHONE_A)

        unknown = _login(client, identifier=_PHONE_B, password=_PASSWORD)  # jamais inscrit
        wrong_pw = _login(client, identifier=_PHONE_A, password=_WRONG_PASSWORD)

        assert unknown.status_code == 401
        assert wrong_pw.status_code == 401
        assert unknown.json()["detail"] == wrong_pw.json()["detail"] == _INVALID_CREDENTIALS_DETAIL

    def test_short_password_is_401_not_422(self, _e2e_client: TestClient) -> None:
        """Un mot de passe trop court produit le **même** `401` générique, pas un `422`.

        Le schéma de connexion impose `min_length=1` (jamais la politique
        d'inscription) : distinguer « trop court » de « faux » divulguerait la
        politique de mot de passe (anti-énumération).
        """

        client = _e2e_client
        _register_manager(client, phone=_PHONE_A)
        resp = _login(client, identifier=_PHONE_A, password="x")
        assert resp.status_code == 401
        assert resp.json()["detail"] == _INVALID_CREDENTIALS_DETAIL

    def test_successful_login_resets_the_counter(self, _e2e_client: TestClient) -> None:
        """Un succès **avant** le seuil remet le compteur à zéro (pas de verrou latent)."""

        client = _e2e_client
        _register_manager(client, phone=_PHONE_A)

        # 4 échecs (sous le seuil), puis un succès qui réinitialise.
        for _ in range(_MAX_ATTEMPTS - 1):
            assert _login(client, identifier=_PHONE_A, password=_WRONG_PASSWORD).status_code == 401
        assert _login(client, identifier=_PHONE_A, password=_PASSWORD).status_code == 200

        # 4 nouveaux échecs ne verrouillent pas (le compteur est reparti de zéro).
        for _ in range(_MAX_ATTEMPTS - 1):
            resp = _login(client, identifier=_PHONE_A, password=_WRONG_PASSWORD)
            assert resp.status_code == 401, f"Le succès n'a pas réinitialisé le compteur : {resp.status_code}"

    def test_lock_is_scoped_per_identifier(self, _e2e_client: TestClient) -> None:
        """Verrouiller l'identifiant A ne verrouille **pas** l'identifiant B (clé par identifiant)."""

        client = _e2e_client
        _register_manager(client, phone=_PHONE_A)
        _register_manager(client, phone=_PHONE_B)

        # Verrouille A.
        for _ in range(_MAX_ATTEMPTS):
            _login(client, identifier=_PHONE_A, password=_WRONG_PASSWORD)
        assert _login(client, identifier=_PHONE_A, password=_WRONG_PASSWORD).status_code == 429

        # B reste joignable : un tiers ne peut pas verrouiller le compte de B via A.
        assert _login(client, identifier=_PHONE_B, password=_PASSWORD).status_code == 200

    def test_password_reset_request_is_always_202(self, _e2e_client: TestClient) -> None:
        """`/auth/password/reset/request` répond **toujours** `202` (anti-énumération)."""

        client = _e2e_client
        _register_manager(client, phone=_PHONE_A)

        known = client.post("/auth/password/reset/request", json={"identifier": _PHONE_A})
        unknown = client.post("/auth/password/reset/request", json={"identifier": _PHONE_B})
        assert known.status_code == 202
        assert unknown.status_code == 202
        assert known.json()["detail"] == unknown.json()["detail"]
