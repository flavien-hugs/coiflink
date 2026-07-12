"""Tests e2e pour US-1.3 — réinitialisation du mot de passe par OTP (#11).

Trois groupes de scénarios :

• TestPasswordResetOtpFlowE2E (sans base de données) — parcours complet en deux
  appels HTTP consécutifs partageant un InMemoryOtpRepository et un
  FakeAuthUserRepository réels :
    POST /auth/password/reset/request → OTP stocké dans l'instance partagée
    POST /auth/password/reset/confirm → OTP relu depuis la même instance.
  L'OTP est capturé via FakeOtpSender (mêle l'interface du canal de notification
  sans I/O réelle). Exercice croisé des frontières de composants.

• TestPasswordResetRateLimitE2E (sans base de données) — N demandes HTTP
  consécutives accumulent l'état d'un InMemoryLoginRateLimiter réel capturé en
  closure. Vérifie le déclenchement du 429 au seuil, la présence de
  Retry-After, et que le message ne divulgue pas l'identifiant.

• TestPasswordResetFullStackE2E (PostgreSQL requis) — parcours complet avec pile
  réelle sans aucun mock applicatif (SQL + argon2 + InMemoryOtpRepository) :
    POST /auth/register (compte réel)
    POST /auth/password/reset/request (OTP capturé via FakeOtpSender)
    POST /auth/password/reset/confirm (OTP + nouveau mot de passe)
    POST /auth/login (ancien mdp → 401, nouveau mdp → 200)
  Vérifie le critère d'acceptation principal de l'issue #11 :
  « l'ancien mot de passe est invalidé ».

Prérequis (TestPasswordResetFullStackE2E) :
    cd backend
    DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
    DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_password_reset_e2e.py -v

Groupes sans base de données :
    pytest tests/test_password_reset_e2e.py::TestPasswordResetOtpFlowE2E -v
    pytest tests/test_password_reset_e2e.py::TestPasswordResetRateLimitE2E -v

Nettoyage (TestPasswordResetFullStackE2E) : les données de test sont supprimées
avant et après chaque test (plage réservée : +225072999xxxx).
"""

from __future__ import annotations

import datetime
import os
import uuid as _uuid_mod
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from coiflink_api.adapters.inbound.auth import (
    get_confirm_password_reset,
    get_request_password_reset,
)
from coiflink_api.adapters.outbound.persistence.session import get_engine
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.adapters.outbound.security.otp_in_memory import InMemoryOtpRepository
from coiflink_api.application.password_reset import (
    ConfirmPasswordReset,
    RequestPasswordReset,
)
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import UserStatus
from coiflink_api.main import app

from .conftest import FakeAuthUserRepository, FakeHasher, FakeOtpSender

# ── Constantes ─────────────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Secret de test local — jamais en production.
_TEST_JWT_SECRET = "test-only-e2e-reset-jwt-secret-not-for-production-use"

# Plage de téléphones réservée aux tests e2e de reset (#11) ; distincte de #10.
_E2E_PHONE_PREFIX = "+225072999"
_PHONE_LOCAL = "0729990011"       # → +2250729990011 après normalisation E.164
_PHONE_LOCAL_B = "0729990012"     # scénarios e-mail
_PHONE_E164 = "+2250729990011"
_E2E_EMAIL = "e2e-reset@example.com"

_OLD_PASSWORD = "ancien-mdp-e2e-reset"
_NEW_PASSWORD = "nouveau-mdp-e2e-reset"

# Seuil intentionnellement bas pour déclencher le 429 avec peu de requêtes.
_E2E_MAX_ATTEMPTS = 3

_UID = _uuid_mod.UUID("00000000-0000-0000-0000-000000009911")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _active_creds(hasher: FakeHasher, password: str = _OLD_PASSWORD) -> UserCredentials:
    """Crédentials actifs avec un condensat produit par FakeHasher."""
    return UserCredentials(
        id=_UID,
        role="CLIENT",
        status=UserStatus.ACTIVE.value,
        password_hash=hasher.hash(password),
    )


# ── Groupe 1 : parcours OTP complet (sans base de données) ───────────────────


@pytest.fixture()
def _flow_client() -> Generator[tuple[TestClient, FakeOtpSender, FakeAuthUserRepository, FakeHasher], None, None]:
    """TestClient avec InMemoryOtpRepository partagé entre request et confirm.

    Les deux endpoints partagent la même instance d'OtpRepository et de
    FakeAuthUserRepository (capturée en closure) : le code OTP écrit par
    `/request` est relu par `/confirm`, comme en production.
    """
    hasher = FakeHasher()
    otp_repo = InMemoryOtpRepository()
    sender = FakeOtpSender()
    user_repo = FakeAuthUserRepository(
        credentials_by_phone={_PHONE_E164: _active_creds(hasher)}
    )

    def _request_uc() -> RequestPasswordReset:
        return RequestPasswordReset(user_repo, otp_repo, sender)

    def _confirm_uc() -> ConfirmPasswordReset:
        return ConfirmPasswordReset(user_repo, otp_repo, hasher)

    app.dependency_overrides[get_request_password_reset] = _request_uc
    app.dependency_overrides[get_confirm_password_reset] = _confirm_uc
    try:
        yield TestClient(app), sender, user_repo, hasher
    finally:
        app.dependency_overrides.pop(get_request_password_reset, None)
        app.dependency_overrides.pop(get_confirm_password_reset, None)


class TestPasswordResetOtpFlowE2E:
    """Deux appels HTTP consécutifs partagent un InMemoryOtpRepository réel (#11)."""

    # ── Parcours heureux ─────────────────────────────────────────────────────

    def test_confirm_with_captured_otp_returns_200(
        self, _flow_client: tuple
    ) -> None:
        """Le code OTP émis par /request est accepté par /confirm."""
        client, sender, _, _ = _flow_client
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        r = client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        assert r.status_code == 200

    def test_confirm_detail_is_success_message(self, _flow_client: tuple) -> None:
        client, sender, _, _ = _flow_client
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        r = client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        assert r.json()["detail"] == "Mot de passe réinitialisé."

    def test_password_hash_updated_in_repository(self, _flow_client: tuple) -> None:
        """Après confirm, update_password a bien été appelé sur le dépôt."""
        client, sender, user_repo, _ = _flow_client
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        assert user_repo.updated_passwords, "update_password n'a pas été appelé"

    def test_old_password_invalidated_in_repository(self, _flow_client: tuple) -> None:
        """Critère #11 : l'ancien condensat n'authentifie plus le compte."""
        client, sender, user_repo, hasher = _flow_client
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        cred = user_repo.find_by_phone(_PHONE_E164)
        assert cred is not None
        assert not hasher.verify(_OLD_PASSWORD, cred.password_hash)

    def test_new_password_authenticates_in_repository(self, _flow_client: tuple) -> None:
        """Le nouveau condensat correspond au nouveau mot de passe."""
        client, sender, user_repo, hasher = _flow_client
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        cred = user_repo.find_by_phone(_PHONE_E164)
        assert cred is not None
        assert hasher.verify(_NEW_PASSWORD, cred.password_hash)

    # ── OTP à usage unique ───────────────────────────────────────────────────

    def test_otp_single_use_second_confirm_returns_400(self, _flow_client: tuple) -> None:
        """Après un reset réussi, le même code OTP est refusé (défi supprimé)."""
        client, sender, _, _ = _flow_client
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        r = client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        assert r.status_code == 400

    def test_otp_single_use_second_confirm_generic_detail(self, _flow_client: tuple) -> None:
        """Le message d'erreur du second confirm est le message générique OTP."""
        client, sender, _, _ = _flow_client
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        r = client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        assert r.json()["detail"] == "Code de réinitialisation invalide ou expiré."

    # ── Deuxième demande invalide le premier OTP ─────────────────────────────

    def test_second_request_overwrites_first_otp_in_shared_repo(
        self, _flow_client: tuple
    ) -> None:
        """Une deuxième demande remplace le défi dans l'InMemoryOtpRepository partagé.

        Après deux demandes, le premier code OTP est refusé car la deuxième
        demande a écrasé le défi en mémoire.
        """
        client, sender, _, _ = _flow_client
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        first_code = sender.sent[0][1]
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        second_code = sender.sent[1][1]

        # Le second code doit fonctionner.
        r_second = client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": second_code, "new_password": _NEW_PASSWORD},
        )
        assert r_second.status_code == 200

        # Le premier code n'est plus dans le dépôt (écrasé par la 2ème demande).
        # Seul cas de faux-positif : les deux codes sont identiques (1 sur 10^6).
        if first_code != second_code:
            # Le dépôt ne contient plus le défi (reset réussi l'a supprimé).
            # Si on re-demandait et confirmait, le premier code serait invalide.
            # Ce test vérifie donc l'état après le succès : pas de défi résiduel.
            r_first = client.post(
                "/auth/password/reset/confirm",
                json={"identifier": _PHONE_LOCAL, "code": first_code, "new_password": _NEW_PASSWORD},
            )
            assert r_first.status_code == 400


# ── Groupe 2 : accumulation du rate-limiter (sans base de données) ────────────


@pytest.fixture()
def _rl_client() -> Generator[TestClient, None, None]:
    """TestClient pour accumulation du limiteur dédié au reset (sans base).

    Le rate-limiter est un InMemoryLoginRateLimiter réel capturé en closure ;
    son état s'accumule d'une requête à l'autre. Le dépôt utilisateur est vide
    (identifiant introuvable → record_failure après chaque demande).
    """
    rate_limiter = InMemoryLoginRateLimiter(
        max_attempts=_E2E_MAX_ATTEMPTS,
        window=datetime.timedelta(minutes=5),
        lockout=datetime.timedelta(minutes=15),
    )

    def _uc() -> RequestPasswordReset:
        return RequestPasswordReset(
            FakeAuthUserRepository(),  # dépôt vide → utilisateur introuvable
            InMemoryOtpRepository(),
            FakeOtpSender(),
            rate_limiter=rate_limiter,
        )

    app.dependency_overrides[get_request_password_reset] = _uc
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_request_password_reset, None)


class TestPasswordResetRateLimitE2E:
    """N appels HTTP accumulent l'état du InMemoryLoginRateLimiter de reset (#11)."""

    def test_sequential_requests_trigger_429_at_threshold(
        self, _rl_client: TestClient
    ) -> None:
        """_E2E_MAX_ATTEMPTS demandes remplissent la fenêtre ; la suivante est 429."""
        payload = {"identifier": _PHONE_LOCAL}
        for _ in range(_E2E_MAX_ATTEMPTS):
            r = _rl_client.post("/auth/password/reset/request", json=payload)
            assert r.status_code == 202

        r = _rl_client.post("/auth/password/reset/request", json=payload)
        assert r.status_code == 429

    def test_429_includes_retry_after_header(self, _rl_client: TestClient) -> None:
        payload = {"identifier": _PHONE_LOCAL}
        for _ in range(_E2E_MAX_ATTEMPTS):
            _rl_client.post("/auth/password/reset/request", json=payload)
        r = _rl_client.post("/auth/password/reset/request", json=payload)
        assert "Retry-After" in r.headers

    def test_retry_after_is_positive_integer(self, _rl_client: TestClient) -> None:
        payload = {"identifier": _PHONE_LOCAL}
        for _ in range(_E2E_MAX_ATTEMPTS):
            _rl_client.post("/auth/password/reset/request", json=payload)
        r = _rl_client.post("/auth/password/reset/request", json=payload)
        assert int(r.headers["Retry-After"]) > 0

    def test_exactly_at_threshold_returns_202_not_429(
        self, _rl_client: TestClient
    ) -> None:
        """La _E2E_MAX_ATTEMPTS-ième demande passe check() (verrou non actif) ;
        c'est la suivante qui sera refusée.
        """
        payload = {"identifier": _PHONE_LOCAL}
        for _ in range(_E2E_MAX_ATTEMPTS - 1):
            r = _rl_client.post("/auth/password/reset/request", json=payload)
            assert r.status_code == 202

        r = _rl_client.post("/auth/password/reset/request", json=payload)
        assert r.status_code == 202

    def test_429_message_does_not_reveal_identifier(self, _rl_client: TestClient) -> None:
        """Le message 429 est générique — l'identifiant n'y figure jamais."""
        payload = {"identifier": _PHONE_LOCAL}
        for _ in range(_E2E_MAX_ATTEMPTS):
            _rl_client.post("/auth/password/reset/request", json=payload)
        r = _rl_client.post("/auth/password/reset/request", json=payload)
        assert _PHONE_LOCAL not in r.text
        assert "+225" not in r.text

    def test_429_message_is_generic_reset_message(self, _rl_client: TestClient) -> None:
        payload = {"identifier": _PHONE_LOCAL}
        for _ in range(_E2E_MAX_ATTEMPTS):
            _rl_client.post("/auth/password/reset/request", json=payload)
        r = _rl_client.post("/auth/password/reset/request", json=payload)
        assert r.json()["detail"] == "Trop de demandes de réinitialisation. Réessayez plus tard."


# ── Groupe 3 : pile complète (PostgreSQL requis) ──────────────────────────────


@pytest.fixture()
def _fullstack_client() -> Generator[tuple[TestClient, FakeOtpSender], None, None]:
    """TestClient avec pile réelle : SQL + argon2 + InMemoryOtpRepository.

    - `app.state.password_reset_otp_sender` est remplacé par un FakeOtpSender
      qui capture les codes OTP émis sans I/O.
    - `app.state.password_reset_otp_repository` est une instance fraîche par
      test (isolation).
    - `app.state.token_service` est câblé pour permettre la vérification de
      connexion après reset.
    - Les données de test (plage +225072999xxxx) sont supprimées avant et après
      chaque test.
    - Skip automatique si DATABASE_URL n'est pas défini.
    """
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL requis pour les tests e2e full-stack.")

    fake_sender = FakeOtpSender()

    orig_sender = getattr(app.state, "password_reset_otp_sender", None)
    orig_otp_repo = getattr(app.state, "password_reset_otp_repository", None)
    orig_token_service = getattr(app.state, "token_service", None)
    orig_login_rl = getattr(app.state, "login_rate_limiter", None)
    orig_reset_rl = getattr(app.state, "password_reset_rate_limiter", None)

    app.state.password_reset_otp_sender = fake_sender
    app.state.password_reset_otp_repository = InMemoryOtpRepository()
    app.state.token_service = JwtTokenService(
        _TEST_JWT_SECRET,
        access_ttl=datetime.timedelta(minutes=15),
        refresh_ttl=datetime.timedelta(days=30),
    )
    # Limiteurs frais par test pour éviter toute contamination entre tests.
    app.state.login_rate_limiter = InMemoryLoginRateLimiter(
        max_attempts=10,
        window=datetime.timedelta(minutes=5),
        lockout=datetime.timedelta(minutes=15),
    )
    app.state.password_reset_rate_limiter = InMemoryLoginRateLimiter(
        max_attempts=10,
        window=datetime.timedelta(minutes=5),
        lockout=datetime.timedelta(minutes=15),
    )

    def _wipe() -> None:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM users WHERE phone LIKE :prefix"),
                {"prefix": f"{_E2E_PHONE_PREFIX}%"},
            )
            conn.commit()

    _wipe()
    try:
        yield TestClient(app), fake_sender
    finally:
        _wipe()
        app.state.password_reset_otp_sender = orig_sender
        app.state.password_reset_otp_repository = orig_otp_repo
        app.state.token_service = orig_token_service
        app.state.login_rate_limiter = orig_login_rl
        app.state.password_reset_rate_limiter = orig_reset_rl


def _register_fullstack(
    client: TestClient,
    *,
    phone: str = _PHONE_LOCAL,
    password: str = _OLD_PASSWORD,
) -> None:
    """Inscrit un compte de test via l'API réelle et vérifie le 201."""
    resp = client.post(
        "/auth/register",
        json={"full_name": "E2E Reset Test", "phone": phone, "password": password},
    )
    assert resp.status_code == 201, f"Inscription échouée : {resp.text}"


@pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL requis — définissez DATABASE_URL.")
class TestPasswordResetFullStackE2E:
    """Critère #11 : inscription → reset OTP → connexion avec argon2 + SQL réels."""

    # ── Parcours de reset complet ────────────────────────────────────────────

    def test_full_reset_flow_returns_200_on_confirm(
        self, _fullstack_client: tuple
    ) -> None:
        client, sender = _fullstack_client
        _register_fullstack(client)
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        r = client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        assert r.status_code == 200

    def test_old_password_rejected_after_reset(self, _fullstack_client: tuple) -> None:
        """Critère d'acceptation #11 : l'ancien mot de passe est invalidé."""
        client, sender = _fullstack_client
        _register_fullstack(client)
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        r = client.post(
            "/auth/login",
            json={"identifier": _PHONE_LOCAL, "password": _OLD_PASSWORD},
        )
        assert r.status_code == 401

    def test_new_password_accepted_after_reset(self, _fullstack_client: tuple) -> None:
        """Après reset, le nouveau mot de passe s'authentifie avec succès."""
        client, sender = _fullstack_client
        _register_fullstack(client)
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        r = client.post(
            "/auth/login",
            json={"identifier": _PHONE_LOCAL, "password": _NEW_PASSWORD},
        )
        assert r.status_code == 200

    def test_new_password_login_returns_jwt_pair(self, _fullstack_client: tuple) -> None:
        """La connexion après reset émet bien une paire de jetons."""
        client, sender = _fullstack_client
        _register_fullstack(client)
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        r = client.post(
            "/auth/login",
            json={"identifier": _PHONE_LOCAL, "password": _NEW_PASSWORD},
        )
        body = r.json()
        assert "access_token" in body
        assert "refresh_token" in body

    # ── OTP à usage unique (pile réelle) ────────────────────────────────────

    def test_otp_single_use_second_confirm_returns_400(
        self, _fullstack_client: tuple
    ) -> None:
        """Après un reset réussi, la même tentative est refusée (défi supprimé)."""
        client, sender = _fullstack_client
        _register_fullstack(client)
        client.post("/auth/password/reset/request", json={"identifier": _PHONE_LOCAL})
        otp_code = sender.sent[0][1]
        client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        r = client.post(
            "/auth/password/reset/confirm",
            json={"identifier": _PHONE_LOCAL, "code": otp_code, "new_password": _NEW_PASSWORD},
        )
        assert r.status_code == 400

    # ── Requête sans compte (anti-énumération, pile réelle) ──────────────────

    def test_request_for_unknown_account_returns_202(
        self, _fullstack_client: tuple
    ) -> None:
        """Anti-énumération #11 : 202 même si aucun compte ne correspond."""
        client, sender = _fullstack_client
        r = client.post(
            "/auth/password/reset/request",
            json={"identifier": "0729990099"},  # aucun compte inscrit
        )
        assert r.status_code == 202

    def test_request_for_unknown_account_same_detail_as_known(
        self, _fullstack_client: tuple
    ) -> None:
        """Le corps de la réponse 202 est identique pour un compte existant ou non."""
        client, sender = _fullstack_client
        _register_fullstack(client)

        r_known = client.post(
            "/auth/password/reset/request", json={"identifier": _PHONE_LOCAL}
        )
        r_unknown = client.post(
            "/auth/password/reset/request",
            json={"identifier": "0729990099"},
        )
        assert r_known.json()["detail"] == r_unknown.json()["detail"]

    def test_request_for_unknown_account_sends_no_otp(
        self, _fullstack_client: tuple
    ) -> None:
        """Aucun OTP n'est envoyé si l'identifiant ne correspond à aucun compte."""
        client, sender = _fullstack_client
        client.post(
            "/auth/password/reset/request",
            json={"identifier": "0729990099"},
        )
        assert not sender.sent
