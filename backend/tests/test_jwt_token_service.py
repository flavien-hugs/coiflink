"""Tests unitaires pour `JwtTokenService` (adapter sortant, issue #10, US-1.2).

Vérifie :
- fail-fast sur secret vide ;
- `issue_pair` : deux jetons distincts, claims corrects, `expires_in` cohérent,
  `token_type == "bearer"`, accès vs refresh par `type`, aucune PII, JTI uniques ;
- `decode` : accepte un jeton valide, rejette signature invalide, mauvais secret,
  jeton expiré, `alg=none`, entrée vide/illisible ;
- `verify_refresh` : accepte le refresh, rejette un jeton d'accès (mauvais `type`),
  rejette un refresh expiré.
"""

from __future__ import annotations

import base64
import datetime
import json
import uuid

import jwt as pyjwt
import pytest

from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.domain.errors import ExpiredToken, InvalidToken
from coiflink_api.domain.tokens import ACCESS, REFRESH

_SECRET = "test-only-secret-do-not-use-in-prod-x1y2z3"
_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
# Instant dans le passé lointain : tout jeton créé avec cette horloge est expiré maintenant.
_PAST = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)


def _svc(
    *,
    secret: str = _SECRET,
    access_ttl: datetime.timedelta = datetime.timedelta(minutes=15),
    refresh_ttl: datetime.timedelta = datetime.timedelta(days=30),
    clock=None,
) -> JwtTokenService:
    """Construit un `JwtTokenService` ; sans `clock`, utilise l'horloge réelle."""
    kw: dict = {"access_ttl": access_ttl, "refresh_ttl": refresh_ttl}
    if clock is not None:
        kw["clock"] = clock
    return JwtTokenService(secret, **kw)


class TestConstructor:
    def test_empty_secret_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="JWT_SECRET"):
            JwtTokenService("")

    def test_none_secret_raises_value_error(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            JwtTokenService(None)  # type: ignore[arg-type]


class TestIssuePair:
    def test_returns_two_distinct_tokens(self) -> None:
        pair = _svc().issue_pair(_UUID, "CLIENT")
        assert pair.access_token
        assert pair.refresh_token
        assert pair.access_token != pair.refresh_token

    def test_expires_in_matches_access_ttl_seconds(self) -> None:
        pair = _svc(access_ttl=datetime.timedelta(minutes=15)).issue_pair(_UUID, "CLIENT")
        assert pair.expires_in == 900

    def test_token_type_is_bearer(self) -> None:
        pair = _svc().issue_pair(_UUID, "CLIENT")
        assert pair.token_type == "bearer"

    def test_access_token_has_type_access(self) -> None:
        pair = _svc().issue_pair(_UUID, "CLIENT")
        claims = _svc().decode(pair.access_token)
        assert claims.type == ACCESS

    def test_refresh_token_has_type_refresh(self) -> None:
        pair = _svc().issue_pair(_UUID, "CLIENT")
        claims = _svc().decode(pair.refresh_token)
        assert claims.type == REFRESH

    def test_claims_sub_is_user_id_string(self) -> None:
        pair = _svc().issue_pair(_UUID, "CLIENT")
        claims = _svc().decode(pair.access_token)
        assert claims.sub == str(_UUID)

    def test_claims_role_is_preserved(self) -> None:
        pair = _svc().issue_pair(_UUID, "MANAGER")
        claims = _svc().decode(pair.access_token)
        assert claims.role == "MANAGER"

    def test_exp_is_after_iat(self) -> None:
        pair = _svc().issue_pair(_UUID, "CLIENT")
        claims = _svc().decode(pair.access_token)
        assert claims.exp > claims.iat

    def test_refresh_exp_greater_than_access_exp(self) -> None:
        pair = _svc(
            access_ttl=datetime.timedelta(minutes=15),
            refresh_ttl=datetime.timedelta(days=30),
        ).issue_pair(_UUID, "CLIENT")
        svc = _svc()
        access_claims = svc.decode(pair.access_token)
        refresh_claims = svc.decode(pair.refresh_token)
        assert refresh_claims.exp > access_claims.exp

    def test_jti_is_non_empty(self) -> None:
        pair = _svc().issue_pair(_UUID, "CLIENT")
        claims = _svc().decode(pair.access_token)
        assert claims.jti

    def test_consecutive_pairs_have_distinct_jtis(self) -> None:
        svc = _svc()
        claims1 = svc.decode(svc.issue_pair(_UUID, "CLIENT").access_token)
        claims2 = svc.decode(svc.issue_pair(_UUID, "CLIENT").access_token)
        assert claims1.jti != claims2.jti

    def test_claims_contain_no_pii(self) -> None:
        """Aucun claim ne doit transporter de PII (tel/email/nom) — ADR-0013."""
        pair = _svc().issue_pair(_UUID, "CLIENT")
        raw = pyjwt.decode(pair.access_token, _SECRET, algorithms=["HS256"])
        assert set(raw.keys()).issubset({"sub", "role", "type", "iat", "exp", "jti"})

    def test_string_user_id_accepted(self) -> None:
        pair = _svc().issue_pair("some-string-id", "CLIENT")
        claims = _svc().decode(pair.access_token)
        assert claims.sub == "some-string-id"


class TestDecode:
    def test_valid_token_returns_correct_claims(self) -> None:
        svc = _svc()
        pair = svc.issue_pair(_UUID, "CLIENT")
        claims = svc.decode(pair.access_token)
        assert claims.sub == str(_UUID)
        assert claims.role == "CLIENT"

    def test_tampered_signature_raises_invalid_token(self) -> None:
        svc = _svc()
        token = svc.issue_pair(_UUID, "CLIENT").access_token
        tampered = token[:-4] + "xxxx"
        with pytest.raises(InvalidToken):
            svc.decode(tampered)

    def test_wrong_secret_raises_invalid_token(self) -> None:
        token = _svc(secret="secret-one-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx").issue_pair(
            _UUID, "CLIENT"
        ).access_token
        with pytest.raises(InvalidToken):
            _svc(secret="secret-two-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx").decode(token)

    def test_expired_token_raises_expired_token(self) -> None:
        # Créé à _PAST avec un TTL d'1 seconde → expiré depuis 2020.
        token = _svc(
            access_ttl=datetime.timedelta(seconds=1), clock=lambda: _PAST
        ).issue_pair(_UUID, "CLIENT").access_token
        with pytest.raises(ExpiredToken):
            _svc().decode(token)

    def test_alg_none_rejected(self) -> None:
        """Un jeton avec `alg=none` doit être rejeté (confusion d'algorithme)."""
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        header_b64 = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        body_b64 = base64.urlsafe_b64encode(
            json.dumps({
                "sub": str(_UUID), "role": "CLIENT", "type": ACCESS,
                "iat": now, "exp": now + 900, "jti": "test-jti",
            }).encode()
        ).rstrip(b"=").decode()
        none_token = f"{header_b64}.{body_b64}."
        with pytest.raises(InvalidToken):
            _svc().decode(none_token)

    def test_empty_string_raises_invalid_token(self) -> None:
        with pytest.raises(InvalidToken):
            _svc().decode("")

    def test_garbage_raises_invalid_token(self) -> None:
        with pytest.raises(InvalidToken):
            _svc().decode("not.a.jwt")

    def test_single_segment_raises_invalid_token(self) -> None:
        with pytest.raises(InvalidToken):
            _svc().decode("onlyone")


class TestVerifyRefresh:
    def test_refresh_token_accepted(self) -> None:
        svc = _svc()
        pair = svc.issue_pair(_UUID, "CLIENT")
        claims = svc.verify_refresh(pair.refresh_token)
        assert claims.type == REFRESH

    def test_access_token_raises_invalid_token(self) -> None:
        svc = _svc()
        pair = svc.issue_pair(_UUID, "CLIENT")
        with pytest.raises(InvalidToken):
            svc.verify_refresh(pair.access_token)

    def test_expired_refresh_raises_expired_token(self) -> None:
        token = _svc(
            refresh_ttl=datetime.timedelta(seconds=1), clock=lambda: _PAST
        ).issue_pair(_UUID, "CLIENT").refresh_token
        with pytest.raises(ExpiredToken):
            _svc().verify_refresh(token)

    def test_tampered_refresh_raises_invalid_token(self) -> None:
        svc = _svc()
        token = svc.issue_pair(_UUID, "CLIENT").refresh_token
        tampered = token[:-4] + "zzzz"
        with pytest.raises(InvalidToken):
            svc.verify_refresh(tampered)
