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

from fastapi import FastAPI

from coiflink_api.adapters.inbound.auth import router as auth_router
from coiflink_api.adapters.inbound.health import router as health_router
from coiflink_api.adapters.outbound.notifications.otp_sender_stub import (
    StubOtpSender,
)
from coiflink_api.adapters.outbound.security.otp_in_memory import (
    InMemoryOtpRepository,
)
from coiflink_api.config import load_auth_config

# Configuration lue depuis l'environnement (jamais de secret en dur).
APP_NAME = os.environ.get("APP_NAME", "CoifLink API")
APP_ENV = os.environ.get("APP_ENV", "development")

app = FastAPI(title=APP_NAME)

# Assemblage de l'authentification (issue #8) : la config OTP et les adapters
# singletons (envoi stub, dépôt OTP en mémoire) sont déposés sur `app.state` et
# relus par l'adapter entrant `auth` lors de l'injection de dépendances. Aucune
# règle métier ici — uniquement du câblage (comme pour `health_router`).
app.state.auth_config = load_auth_config()
app.state.otp_sender = StubOtpSender()
app.state.otp_repository = InMemoryOtpRepository()

app.include_router(health_router)
app.include_router(auth_router)
