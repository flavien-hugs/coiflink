"""Adapter sortant : émission / décodage de JWT via **PyJWT** (ADR-0013).

Implémente le port `TokenService`. Signe en **HS256** (symétrique) avec le
`JWT_SECRET` (secret lu de l'environnement, ADR-0011) ; pose les claims minimaux
`sub`, `role`, `type`, `iat`, `exp`, `jti` — **aucune PII**. Le jeton d'accès est
court, le refresh long ; les deux se distinguent par le claim `type`.

Sécurité :
- `decode` **impose** l'algorithme attendu (`algorithms=[algorithm]`) et exige
  `exp` : cela rejette `alg=none` et la confusion d'algorithme ;
- les exceptions PyJWT sont mappées vers `ExpiredToken`/`InvalidToken` **sans**
  fuite du détail de la lib ;
- le secret n'est **jamais** journalisé ni renvoyé ; un secret absent fait
  échouer la **construction** de l'adapter (fail-fast clair, sans casser `/health`
  puisque l'adapter n'est assemblé que pour les routes d'auth).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Callable

import jwt

from coiflink_api.domain.errors import ExpiredToken, InvalidToken
from coiflink_api.domain.tokens import ACCESS, REFRESH, TokenClaims, TokenPair


def _utc_now() -> datetime.datetime:
    """Horloge par défaut : instant courant en UTC (aware)."""

    return datetime.datetime.now(datetime.timezone.utc)


class JwtTokenService:
    """Service de jetons JWT (PyJWT, HS256) — implémente le port `TokenService`."""

    def __init__(
        self,
        secret: str,
        *,
        algorithm: str = "HS256",
        access_ttl: datetime.timedelta = datetime.timedelta(minutes=15),
        refresh_ttl: datetime.timedelta = datetime.timedelta(days=30),
        clock: Callable[[], datetime.datetime] | None = None,
        jti_factory: Callable[[], str] | None = None,
    ) -> None:
        if not secret:
            # Fail-fast explicite : impossible d'émettre un jeton sûr sans secret.
            # Le message ne divulgue jamais de valeur, seulement l'état de config.
            raise ValueError(
                "JWT_SECRET est requis pour l'émission de jetons (voir backend/.env.example)."
            )
        self._secret = secret
        self._algorithm = algorithm
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        self._clock = clock if clock is not None else _utc_now
        self._jti_factory = jti_factory if jti_factory is not None else (lambda: uuid.uuid4().hex)

    def issue_pair(self, user_id: uuid.UUID | str, role: str) -> TokenPair:
        """Émet une paire d'accès (court) + refresh (long) pour ce compte."""

        now = self._clock()
        sub = str(user_id)
        access = self._encode(sub, role, ACCESS, now, self._access_ttl)
        refresh = self._encode(sub, role, REFRESH, now, self._refresh_ttl)
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=int(self._access_ttl.total_seconds()),
        )

    def decode(self, token: str) -> TokenClaims:
        """Décode et vérifie signature + `exp` + algorithme attendu."""

        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise ExpiredToken("Jeton expiré.") from exc
        except jwt.InvalidTokenError as exc:
            # Couvre signature invalide, alg inattendu, altération, claims manquants.
            raise InvalidToken("Jeton invalide.") from exc

        return TokenClaims(
            sub=str(payload.get("sub", "")),
            role=str(payload.get("role", "")),
            type=str(payload.get("type", "")),
            jti=str(payload.get("jti", "")),
            iat=int(payload.get("iat", 0)),
            exp=int(payload.get("exp", 0)),
        )

    def verify_refresh(self, token: str) -> TokenClaims:
        """Décode un jeton et exige `type == "refresh"`."""

        claims = self.decode(token)
        if claims.type != REFRESH:
            raise InvalidToken("Type de jeton invalide (refresh attendu).")
        return claims

    def _encode(
        self,
        sub: str,
        role: str,
        token_type: str,
        now: datetime.datetime,
        ttl: datetime.timedelta,
    ) -> str:
        payload = {
            "sub": sub,
            "role": role,
            "type": token_type,
            "iat": int(now.timestamp()),
            "exp": int((now + ttl).timestamp()),
            "jti": self._jti_factory(),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)


__all__ = ["JwtTokenService"]
