"""Suite de sécurité **JWT / refresh** consolidée (#51, §11.1, ADR-0013).

Regroupe en une lecture unique les propriétés cryptographiques et de session que
`test_jwt_token_service.py` couvre au niveau **service** (rejet `alg=none`,
signature altérée, expiration, mauvais `type`…), et les **rejoue au niveau HTTP**
contre une route protégée réelle (`GET /auth/me`) — ce que la suite service ne
fait pas. On **ne recopie pas** les assertions déjà couvertes à l'identique : on
ajoute les cas manquants (confusion d'algorithme, claims obligatoires manquants)
et le **volet HTTP** (anti-énumération : message identique quel que soit le motif).

DB-free : au niveau HTTP, un jeton invalide/expiré/de mauvais type est rejeté par
la garde globale `require_authenticated` **avant** toute relecture en base
(`get_current_principal`). Cette suite tourne donc dans le gate ADW sans PostgreSQL.
Le volet e2e (révocation immédiate d'un compte suspendu, rotation du refresh à
`/auth/refresh`) vit dans `test_security_isolation_e2e.py` (pile réelle).
"""

from __future__ import annotations

import base64
import datetime
import json
import uuid
from collections.abc import Generator

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.domain.errors import ExpiredToken, InvalidToken
from coiflink_api.domain.tokens import ACCESS
from coiflink_api.main import app as main_app

# Secret **local** de test — jamais un secret réel, jamais en production (§11).
_SECRET = "test-only-security-jwt-suite-secret-not-for-production"
_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
# Horloge figée dans le passé : tout jeton émis avec elle est expiré « maintenant ».
_PAST = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)


def _svc(**kwargs: object) -> JwtTokenService:
    return JwtTokenService(_SECRET, **kwargs)  # type: ignore[arg-type]


def _b64url(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()


def _forge_alg_none() -> str:
    """Forge un jeton `alg=none` **non signé** (attaque de confusion d'algorithme)."""

    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    header = _b64url({"alg": "none", "typ": "JWT"})
    body = _b64url(
        {
            "sub": str(_UUID),
            "role": "ADMIN",
            "type": ACCESS,
            "iat": now,
            "exp": now + 900,
            "jti": "forged",
        }
    )
    return f"{header}.{body}."


def _tamper_signature(token: str) -> str:
    """Rend la signature HMAC invalide en modifiant l'avant-dernier caractère.

    Cible l'avant-dernier caractère base64url (6 bits significatifs) plutôt que le
    dernier — dont les 2 bits de poids faible d'une signature 32 octets non paddée
    sont toujours nuls, ce qui rendrait l'altération parfois sans effet (flaky).
    Miroir du helper de `test_rbac_e2e.py`.
    """

    header_payload, signature = token.rsplit(".", 1)
    bad = "A" if signature[-2] != "A" else "B"
    return f"{header_payload}.{signature[:-2] + bad + signature[-1]}"


# --------------------------------------------------------------------------- #
# Niveau service — propriétés cryptographiques (compléments à test_jwt_token_service).
# --------------------------------------------------------------------------- #
class TestJwtServiceProperties:
    def test_alg_none_is_rejected(self) -> None:
        """`alg=none` (jeton non signé) → `InvalidToken` (l'algorithme est imposé)."""

        with pytest.raises(InvalidToken):
            _svc().decode(_forge_alg_none())

    def test_algorithm_confusion_is_rejected(self) -> None:
        """Un jeton signé en **HS384** est refusé par un décodeur **HS256** (confusion).

        `decode` impose `algorithms=["HS256"]` : un jeton dont l'en-tête annonce un
        autre algorithme — même signé avec le bon secret — n'est jamais accepté.
        """

        hs384 = JwtTokenService(_SECRET, algorithm="HS384").issue_pair(_UUID, "CLIENT")
        with pytest.raises(InvalidToken):
            _svc().decode(hs384.access_token)  # décodeur HS256

    def test_tampered_signature_is_rejected(self) -> None:
        token = _svc().issue_pair(_UUID, "CLIENT").access_token
        with pytest.raises(InvalidToken):
            _svc().decode(_tamper_signature(token))

    @pytest.mark.parametrize("missing", ["exp", "iat", "sub"])
    def test_missing_required_claim_is_rejected(self, missing: str) -> None:
        """Un claim obligatoire (`exp`/`iat`/`sub`) absent → `InvalidToken`.

        `decode` exige explicitement ces claims (`options={"require": [...]}`), ce
        qui rejette un jeton amputé (forgé) même par ailleurs bien signé.
        """

        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        claims: dict = {
            "sub": str(_UUID),
            "role": "CLIENT",
            "type": ACCESS,
            "iat": now,
            "exp": now + 900,
            "jti": "x",
        }
        claims.pop(missing)
        token = pyjwt.encode(claims, _SECRET, algorithm="HS256")
        with pytest.raises(InvalidToken):
            _svc().decode(token)

    def test_expired_access_is_rejected(self) -> None:
        token = _svc(
            access_ttl=datetime.timedelta(seconds=1), clock=lambda: _PAST
        ).issue_pair(_UUID, "CLIENT").access_token
        with pytest.raises(ExpiredToken):
            _svc().decode(token)

    def test_refresh_presented_as_access_is_rejected(self) -> None:
        """Un refresh (TTL long) présenté comme jeton d'accès → `InvalidToken`."""

        refresh = _svc().issue_pair(_UUID, "CLIENT").refresh_token
        with pytest.raises(InvalidToken):
            _svc().verify_access(refresh)


# --------------------------------------------------------------------------- #
# Niveau HTTP — GET /auth/me rejette tout jeton douteux **avant** la base.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def _http() -> Generator[tuple[TestClient, JwtTokenService], None, None]:
    """Dépose un vrai `JwtTokenService` (secret local) sur `app.state` ; nettoie ensuite.

    Les 401 testés surviennent dans la garde globale (signature/`exp`/`type`), donc
    **sans** relecture en base : la suite reste DB-free.
    """

    orig = getattr(main_app.state, "token_service", None)
    service = JwtTokenService(_SECRET)
    main_app.state.token_service = service
    try:
        with TestClient(main_app, raise_server_exceptions=False) as client:
            yield client, service
    finally:
        main_app.state.token_service = orig


def _get_me(client: TestClient, token: str | None) -> object:
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.get("/auth/me", headers=headers)


class TestJwtOverHttp:
    def test_alg_none_returns_401(
        self, _http: tuple[TestClient, JwtTokenService]
    ) -> None:
        client, _ = _http
        resp = _get_me(client, _forge_alg_none())
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate") == "Bearer"

    def test_tampered_token_returns_401(
        self, _http: tuple[TestClient, JwtTokenService]
    ) -> None:
        client, service = _http
        access = service.issue_pair(_UUID, "MANAGER").access_token
        resp = _get_me(client, _tamper_signature(access))
        assert resp.status_code == 401

    def test_expired_access_returns_401(
        self, _http: tuple[TestClient, JwtTokenService]
    ) -> None:
        expired = JwtTokenService(
            _SECRET, access_ttl=datetime.timedelta(seconds=1), clock=lambda: _PAST
        ).issue_pair(_UUID, "MANAGER").access_token
        client, _ = _http
        resp = _get_me(client, expired)
        assert resp.status_code == 401

    def test_refresh_as_access_message_identical_to_missing_token(
        self, _http: tuple[TestClient, JwtTokenService]
    ) -> None:
        """Anti-énumération : refresh-en-accès et absence de jeton → **même** `401`.

        Le motif exact (mauvais `type` vs jeton absent) n'est jamais divulgué : les
        deux réponses portent le même `detail` générique.
        """

        client, service = _http
        refresh = service.issue_pair(_UUID, "MANAGER").refresh_token
        r_refresh = _get_me(client, refresh)
        r_none = _get_me(client, None)
        assert r_refresh.status_code == 401
        assert r_none.status_code == 401
        assert r_refresh.json()["detail"] == r_none.json()["detail"]

    def test_no_token_service_returns_503(self) -> None:
        """`JWT_SECRET` absent (service non assemblé) → `503` sur route protégée."""

        orig = getattr(main_app.state, "token_service", None)
        main_app.state.token_service = None
        try:
            with TestClient(main_app, raise_server_exceptions=False) as client:
                resp = _get_me(client, "any-token")
        finally:
            main_app.state.token_service = orig
        assert resp.status_code == 503
