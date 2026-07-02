"""Adapter entrant (driving) : router HTTP d'authentification (ADR-0003/0008).

Expose l'**inscription client** `POST /auth/register` (US-1.1, issue #8). Traduit
la requête HTTP en commande applicative, assemble le cas d'usage `RegisterClient`
via l'injection de dépendances FastAPI, puis retraduit les erreurs de domaine en
codes HTTP :
- `PhoneAlreadyInUse` / `EmailAlreadyInUse` → **409 Conflict** ;
- `InvalidPhone` / `InvalidPassword` / `InvalidName` / `InvalidEmail` →
  **422 Unprocessable Entity**.

Les schémas Pydantic servent la documentation OpenAPI auto-générée (ADR-0003).
La réponse n'expose **jamais** `password` ni `password_hash` (PRD §11.1). Le
mot de passe reçu n'est ni journalisé ni renvoyé.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.adapters.outbound.persistence.user_repository import (
    SqlUserRepository,
)
from coiflink_api.adapters.outbound.security.argon2_hasher import Argon2Hasher
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.application.registration import RegisterClient, RegisterCommand
from coiflink_api.config import AuthConfig
from coiflink_api.domain.errors import (
    EmailAlreadyInUse,
    InvalidEmail,
    InvalidName,
    InvalidPassword,
    InvalidPhone,
    PhoneAlreadyInUse,
)
from coiflink_api.domain.password import MAX_LENGTH, MIN_LENGTH

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    """Corps de `POST /auth/register`. `password` n'est jamais renvoyé."""

    full_name: str = Field(min_length=1, max_length=255, examples=["Awa Koné"])
    phone: str = Field(min_length=1, max_length=32, examples=["0700000000"])
    password: str = Field(
        min_length=MIN_LENGTH,
        max_length=MAX_LENGTH,
        examples=["motdepasse-solide"],
    )
    email: EmailStr | None = Field(default=None, examples=["awa@example.com"])


class UserResponse(BaseModel):
    """Représentation publique d'un utilisateur — **sans** aucun secret."""

    id: uuid.UUID
    full_name: str
    phone: str
    email: str | None
    role: str
    status: str
    created_at: datetime.datetime


def get_password_hasher() -> PasswordHasher:
    """Fournit l'adapter de hachage (argon2). Surchargable en test."""

    return Argon2Hasher()


def get_register_client(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> RegisterClient:
    """Assemble le cas d'usage `RegisterClient` avec ses adapters (DI).

    Lit la configuration OTP et les adapters singletons déposés sur `app.state`
    par le composition root ; retombe sur des défauts sûrs (OTP désactivé) si
    l'état n'est pas configuré.
    """

    config: AuthConfig = getattr(request.app.state, "auth_config", None) or AuthConfig()
    return RegisterClient(
        SqlUserRepository(session),
        hasher,
        otp_enabled=config.otp_enabled,
        otp_sender=getattr(request.app.state, "otp_sender", None),
        otp_repository=getattr(request.app.state, "otp_repository", None),
        otp_length=config.otp_length,
        otp_ttl=config.otp_ttl,
        otp_max_attempts=config.otp_max_attempts,
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Inscription d'un client (nom, téléphone, mot de passe)",
)
def register_client(
    payload: RegisterRequest,
    usecase: Annotated[RegisterClient, Depends(get_register_client)],
) -> UserResponse:
    """Crée un compte client (`role=CLIENT`) ; refuse un doublon de téléphone."""

    command = RegisterCommand(
        full_name=payload.full_name,
        phone=payload.phone,
        password=payload.password,
        email=payload.email,
    )
    try:
        user = usecase.execute(command)
    except (PhoneAlreadyInUse, EmailAlreadyInUse) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (
        InvalidPhone,
        InvalidPassword,
        InvalidName,
        InvalidEmail,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return UserResponse(
        id=user.id,
        full_name=user.full_name,
        phone=user.phone,
        email=user.email,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
    )


__all__ = ["router", "RegisterRequest", "UserResponse"]
