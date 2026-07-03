"""Adapter entrant (driving) : router HTTP d'authentification (ADR-0003/0008).

Expose l'inscription en libre-service :
- **client** `POST /auth/register` (US-1.1, issue #8) → `role=CLIENT` ;
- **gérant** `POST /auth/register/manager` (issue #9) → `role=MANAGER`, prêt à
  devenir propriétaire d'un salon (#15).

Traduit la requête HTTP en commande applicative, assemble le cas d'usage
`RegisterUser` (avec le rôle **imposé côté serveur** par le chemin choisi) via
l'injection de dépendances FastAPI, puis retraduit les erreurs de domaine en
codes HTTP :
- `PhoneAlreadyInUse` / `EmailAlreadyInUse` → **409 Conflict** ;
- `InvalidPhone` / `InvalidPassword` / `InvalidName` / `InvalidEmail` →
  **422 Unprocessable Entity**.

Anti-élévation de privilège (label `security`) : le rôle n'est **jamais** lu
depuis la requête. `RegisterRequest` ne déclare pas de champ `role` et refuse
tout champ superflu (`extra="forbid"` → `422`), et le cas d'usage n'accepte
qu'un rôle de la liste blanche `SELF_REGISTERABLE_ROLES`.

Les schémas Pydantic servent la documentation OpenAPI auto-générée (ADR-0003).
La réponse n'expose **jamais** `password` ni `password_hash` (PRD §11.1). Le
mot de passe reçu n'est ni journalisé ni renvoyé.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.adapters.outbound.persistence.user_repository import (
    SqlUserRepository,
)
from coiflink_api.adapters.outbound.security.argon2_hasher import Argon2Hasher
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.application.registration import RegisterCommand, RegisterUser
from coiflink_api.config import AuthConfig
from coiflink_api.domain.enums import Role
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
    """Corps d'inscription (client **et** gérant). `password` n'est jamais renvoyé.

    **Aucun champ `role`** : le rôle est imposé côté serveur par le chemin
    d'inscription. `extra="forbid"` fait échouer en `422` tout champ superflu
    (p. ex. un `role` injecté par un appelant malveillant) au lieu de l'ignorer
    silencieusement — défense en profondeur contre l'élévation de privilège.
    """

    model_config = ConfigDict(extra="forbid")

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


def _build_register_user(
    request: Request,
    session: Session,
    hasher: PasswordHasher,
    *,
    role: Role,
) -> RegisterUser:
    """Assemble le cas d'usage `RegisterUser` avec ses adapters, pour un rôle donné.

    Lit la configuration OTP et les adapters singletons déposés sur `app.state`
    par le composition root ; retombe sur des défauts sûrs (OTP désactivé) si
    l'état n'est pas configuré. Le `role` est **imposé ici** (côté serveur), pas
    par la requête.
    """

    config: AuthConfig = getattr(request.app.state, "auth_config", None) or AuthConfig()
    return RegisterUser(
        SqlUserRepository(session),
        hasher,
        role=role,
        otp_enabled=config.otp_enabled,
        otp_sender=getattr(request.app.state, "otp_sender", None),
        otp_repository=getattr(request.app.state, "otp_repository", None),
        otp_length=config.otp_length,
        otp_ttl=config.otp_ttl,
        otp_max_attempts=config.otp_max_attempts,
    )


def get_register_client(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> RegisterUser:
    """Dépendance FastAPI : inscription **client** (`role=CLIENT`)."""

    return _build_register_user(request, session, hasher, role=Role.CLIENT)


def get_register_manager(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> RegisterUser:
    """Dépendance FastAPI : inscription **gérant** (`role=MANAGER`, issue #9)."""

    return _build_register_user(request, session, hasher, role=Role.MANAGER)


def _register(usecase: RegisterUser, payload: RegisterRequest) -> UserResponse:
    """Exécute l'inscription et retraduit les erreurs de domaine en codes HTTP.

    Le mapping est **identique** pour les inscriptions client et gérant : seul le
    rôle porté par le cas d'usage (imposé à l'assemblage) change.
    """

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


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Inscription d'un client (nom, téléphone, mot de passe)",
)
def register_client(
    payload: RegisterRequest,
    usecase: Annotated[RegisterUser, Depends(get_register_client)],
) -> UserResponse:
    """Crée un compte client (`role=CLIENT`) ; refuse un doublon de téléphone."""

    return _register(usecase, payload)


@router.post(
    "/register/manager",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Inscription d'un gérant (compte propriétaire de salon)",
)
def register_manager(
    payload: RegisterRequest,
    usecase: Annotated[RegisterUser, Depends(get_register_manager)],
) -> UserResponse:
    """Crée un compte gérant (`role=MANAGER`), prêt à créer un salon (#15).

    Le rôle est **imposé côté serveur** (aucun champ `role` accepté) ; mêmes
    règles que le client : hachage argon2, normalisation du téléphone, refus de
    doublon. #9 **n'émet aucun JWT** et **ne crée aucun salon**.
    """

    return _register(usecase, payload)


__all__ = ["router", "RegisterRequest", "UserResponse"]
