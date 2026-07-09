"""Composition root de l'API backend CoifLink (architecture hexagonale, ADR-0008).

Ce module n'est pas une couche métier : il **assemble** l'application. Il lit la
configuration depuis l'environnement (jamais de secret en dur, cf. PRD §11,
ADR-0005/0006), instancie FastAPI et monte les adapters entrants (routers).

Répartition hexagonale :
- `domain/`       — entités et règles métier (zéro dépendance framework/I/O) ;
- `application/`  — cas d'usage + `ports` (interfaces) ;
- `adapters/`     — `inbound/` (HTTP FastAPI...) et `outbound/` (Postgres, Redis...).
"""

from __future__ import annotations

import os
import secrets

from fastapi import FastAPI

from coiflink_api.adapters.inbound.auth import router as auth_router
from coiflink_api.adapters.inbound.health import router as health_router
from coiflink_api.adapters.outbound.notifications.otp_sender_stub import (
    StubOtpSender,
)
from coiflink_api.adapters.outbound.security.argon2_hasher import Argon2Hasher
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.adapters.outbound.security.otp_in_memory import (
    InMemoryOtpRepository,
)
from coiflink_api.config import load_auth_config

# Configuration lue depuis l'environnement (jamais de secret en dur).
APP_NAME = os.environ.get("APP_NAME", "CoifLink API")
APP_ENV = os.environ.get("APP_ENV", "development")

app = FastAPI(title=APP_NAME)

# Assemblage de l'authentification : la config et les adapters singletons sont
# déposés sur `app.state` et relus par l'adapter entrant `auth` lors de
# l'injection de dépendances. Aucune règle métier ici — uniquement du câblage.
_auth_config = load_auth_config()
app.state.auth_config = _auth_config

# Inscription/OTP (#8/#9) : envoi stub + dépôt OTP en mémoire.
app.state.otp_sender = StubOtpSender()
app.state.otp_repository = InMemoryOtpRepository()

# Connexion/JWT (#10) :
# - le limiteur anti-bruteforce est un **singleton** (état en mémoire partagé) ;
# - le condensat *dummy* est **pré-calculé une fois** (atténuation d'oracle
#   temporel quand aucun compte ne correspond, cf. `AuthenticateUser`) ;
# - le `TokenService` n'est assemblé que si `JWT_SECRET` est présent. Absent, on
#   laisse `None` : les routes `/auth/login` et `/auth/refresh` répondent `503`
#   (fail-fast clair) sans casser `GET /health` ni l'inscription (ADR-0011/0013).
app.state.login_rate_limiter = InMemoryLoginRateLimiter(
    max_attempts=_auth_config.login_max_attempts,
    window=_auth_config.login_window,
    lockout=_auth_config.login_lockout,
)
app.state.login_dummy_hash = Argon2Hasher().hash(secrets.token_urlsafe(32))
if _auth_config.jwt_secret:
    app.state.token_service = JwtTokenService(
        _auth_config.jwt_secret,
        algorithm=_auth_config.jwt_algorithm,
        access_ttl=_auth_config.access_ttl,
        refresh_ttl=_auth_config.refresh_ttl,
    )
else:
    app.state.token_service = None

app.include_router(health_router)
app.include_router(auth_router)
