"""Adapter entrant (driving) : router HTTP d'authentification (ADR-0003/0008).

Expose l'**inscription client** `POST /auth/register` (US-1.1, issue #8) et
l'**inscription gérant** `POST /auth/register/manager` (issue #9, compte
propriétaire de salon). Les deux routes traduisent la requête HTTP en commande
applicative, assemblent le cas d'usage `RegisterUser` via l'injection de
dépendances FastAPI (**le rôle est fixé côté serveur**), puis retraduisent les
erreurs de domaine en codes HTTP :
- `PhoneAlreadyInUse` / `EmailAlreadyInUse` → **409 Conflict** ;
- `InvalidPhone` / `InvalidPassword` / `InvalidName` / `InvalidEmail` →
  **422 Unprocessable Entity**.

Invariant de sécurité : **aucun** champ `role` n'est déclaré dans la requête
(`RegisterRequest`) ; le rôle est attribué par le câblage de la route, jamais
lu depuis le corps — pas d'élévation de privilège possible via l'inscription.

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

from coiflink_api.adapters.outbound.notifications.otp_sender_stub import StubOtpSender
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.adapters.outbound.persistence.user_repository import (
    SqlUserRepository,
)
from coiflink_api.adapters.outbound.security.argon2_hasher import Argon2Hasher
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.adapters.outbound.security.otp_in_memory import InMemoryOtpRepository
from coiflink_api.application.authentication import (
    AuthenticateUser,
    LoginCommand,
    RefreshTokens,
)
from coiflink_api.application.password_reset import (
    ConfirmPasswordReset,
    PasswordResetConfirmCommand,
    PasswordResetRequestCommand,
    RequestPasswordReset,
)
from coiflink_api.application.ports.login_rate_limiter import LoginRateLimiter
from coiflink_api.application.ports.otp_repository import OtpRepository
from coiflink_api.application.ports.otp_sender import OtpSender
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.application.ports.token_service import TokenService
from coiflink_api.application.registration import RegisterCommand, RegisterUser
from coiflink_api.config import AuthConfig
from coiflink_api.domain.enums import Role
from coiflink_api.domain.errors import (
    EmailAlreadyInUse,
    ExpiredToken,
    InvalidCredentials,
    InvalidEmail,
    InvalidName,
    InvalidOtp,
    InvalidPassword,
    InvalidPhone,
    InvalidToken,
    OtpExpired,
    PhoneAlreadyInUse,
    TooManyLoginAttempts,
)
from coiflink_api.domain.password import MAX_LENGTH, MIN_LENGTH

router = APIRouter(prefix="/auth", tags=["auth"])

# Message générique unique pour tout échec d'authentification (anti-énumération).
_INVALID_CREDENTIALS_DETAIL = "Identifiants invalides."

# Réinitialisation du mot de passe (#11) — messages **génériques** (anti-énumération).
# La demande répond toujours le même 202, compte existant ou non ; la confirmation
# renvoie un unique 400 pour tout échec d'OTP et identifiant sans défi.
_PASSWORD_RESET_REQUEST_DETAIL = (
    "Si un compte correspond à cet identifiant, un code de réinitialisation a été envoyé."
)
_PASSWORD_RESET_CONFIRM_DETAIL = "Mot de passe réinitialisé."
_PASSWORD_RESET_INVALID_OTP_DETAIL = "Code de réinitialisation invalide ou expiré."
_PASSWORD_RESET_RATE_LIMITED_DETAIL = (
    "Trop de demandes de réinitialisation. Réessayez plus tard."
)


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


def _build_register_user(
    request: Request,
    session: Session,
    hasher: PasswordHasher,
    role: str,
) -> RegisterUser:
    """Assemble un cas d'usage `RegisterUser` pour le `role` **fixé côté serveur**.

    Lit la configuration OTP et les adapters singletons déposés sur `app.state`
    par le composition root ; retombe sur des défauts sûrs (OTP désactivé) si
    l'état n'est pas configuré. Le rôle est passé explicitement par la route
    (jamais lu depuis la requête) — garde-fou anti-élévation de privilège.
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
    """Assemble le cas d'usage d'inscription **client** (`role=CLIENT`)."""

    return _build_register_user(request, session, hasher, Role.CLIENT.value)


def get_register_manager(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> RegisterUser:
    """Assemble le cas d'usage d'inscription **gérant** (`role=MANAGER`, #9).

    Le rôle `MANAGER` est attribué **côté serveur** ; aucun champ `role` n'est
    lu depuis la requête (anti-élévation de privilège).
    """

    return _build_register_user(request, session, hasher, Role.MANAGER.value)


def _run_registration(usecase: RegisterUser, payload: RegisterRequest) -> UserResponse:
    """Exécute l'inscription et traduit les erreurs de domaine en HTTP.

    Factorisé entre les routes client et gérant : même parcours applicatif, seul
    le rôle (fixé au câblage, dans `usecase`) diffère. La réponse ne transporte
    **jamais** de secret.
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

    return _run_registration(usecase, payload)


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

    Le rôle est attribué **côté serveur** : un éventuel champ `role` dans le
    corps est ignoré (`RegisterRequest` ne le déclare pas). Refuse un doublon de
    téléphone (`409`) et n'émet aucun JWT (la connexion est l'issue #10).
    """

    return _run_registration(usecase, payload)


# --------------------------------------------------------------------------- #
# Connexion / rafraîchissement (US-1.2, issue #10 — JWT + anti-bruteforce).
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    """Corps de `POST /auth/login`. `password` n'est jamais renvoyé ni journalisé."""

    # Identifiant unique = téléphone **ou** e-mail (auto-détecté côté domaine).
    identifier: str = Field(min_length=1, max_length=320, examples=["0700000000"])
    # `min_length=1` (et non la politique d'inscription) : un mot de passe trop
    # court doit produire le **même** 401 générique qu'un mot de passe faux, pas un
    # 422 qui divulguerait la politique / distinguerait les cas (anti-énumération).
    password: str = Field(min_length=1, max_length=MAX_LENGTH, examples=["motdepasse-solide"])


class RefreshRequest(BaseModel):
    """Corps de `POST /auth/refresh`."""

    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    """Paire de jetons émise. **Aucun** secret serveur : la clé de signature n'apparaît jamais."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


def get_token_service(request: Request) -> TokenService:
    """Fournit le `TokenService` déposé sur `app.state` par le composition root.

    Absent (p. ex. `JWT_SECRET` non configuré → non assemblé au démarrage), on
    échoue proprement en `503` sans divulguer de valeur de secret et **sans**
    affecter `/health` ni l'inscription (assemblage déporté aux routes d'auth).
    """

    service = getattr(request.app.state, "token_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service d'authentification indisponible (JWT_SECRET non configuré).",
        )
    return service


def get_login_rate_limiter(request: Request) -> LoginRateLimiter:
    """Fournit le limiteur anti-bruteforce singleton (état en mémoire partagé)."""

    limiter = getattr(request.app.state, "login_rate_limiter", None)
    if limiter is None:
        # Repli sûr (tests/état non configuré) : défauts d'`AuthConfig`.
        config: AuthConfig = getattr(request.app.state, "auth_config", None) or AuthConfig()
        limiter = InMemoryLoginRateLimiter(
            max_attempts=config.login_max_attempts,
            window=config.login_window,
            lockout=config.login_lockout,
        )
        request.app.state.login_rate_limiter = limiter
    return limiter


def get_authenticate_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    token_service: Annotated[TokenService, Depends(get_token_service)],
    rate_limiter: Annotated[LoginRateLimiter, Depends(get_login_rate_limiter)],
) -> AuthenticateUser:
    """Assemble le cas d'usage de **connexion** (aucune règle métier ici)."""

    return AuthenticateUser(
        SqlUserRepository(session),
        hasher,
        token_service,
        rate_limiter,
        dummy_hash=getattr(request.app.state, "login_dummy_hash", None),
    )


def get_refresh_tokens(
    session: Annotated[Session, Depends(get_session)],
    token_service: Annotated[TokenService, Depends(get_token_service)],
) -> RefreshTokens:
    """Assemble le cas d'usage de **rafraîchissement** de jeton."""

    return RefreshTokens(SqlUserRepository(session), token_service)


def _client_ip(request: Request) -> str | None:
    """IP du pair direct (`request.client.host`).

    Note (ADR-0013) : derrière le proxy Railway, l'IP réelle transiterait par
    `X-Forwarded-For` ; son exploitation *de confiance* est différée pour éviter
    un en-tête spoofable dans la clé d'anti-bruteforce.
    """

    return request.client.host if request.client else None


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Connexion (téléphone ou e-mail + mot de passe) — émet un JWT + refresh",
)
def login(
    payload: LoginRequest,
    request: Request,
    usecase: Annotated[AuthenticateUser, Depends(get_authenticate_user)],
) -> TokenResponse:
    """Authentifie et émet une paire de jetons ; `401` générique / `429` si bruteforce."""

    command = LoginCommand(
        identifier=payload.identifier,
        password=payload.password,
        client_ip=_client_ip(request),
    )
    try:
        pair = usecase.execute(command)
    except TooManyLoginAttempts as exc:
        headers = (
            {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives de connexion. Réessayez plus tard.",
            headers=headers,
        ) from exc
    except InvalidCredentials as exc:
        # Message générique constant (jamais str(exc)) : aucune énumération de comptes.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS_DETAIL
        ) from exc

    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rafraîchit le jeton d'accès à partir d'un refresh token valide",
)
def refresh(
    payload: RefreshRequest,
    usecase: Annotated[RefreshTokens, Depends(get_refresh_tokens)],
) -> TokenResponse:
    """Échange un refresh valide contre une **nouvelle** paire (rotation) ; `401` sinon."""

    try:
        pair = usecase.execute(payload.refresh_token)
    except (InvalidToken, ExpiredToken) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton de rafraîchissement invalide.",
        ) from exc

    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
    )


# --------------------------------------------------------------------------- #
# Réinitialisation du mot de passe par OTP (US-1.3, issue #11).
# Parcours en deux étapes : demande d'un code (SMS **ou** e-mail), puis
# confirmation (code + nouveau mot de passe qui invalide l'ancien). Réponses
# **génériques** (anti-énumération) ; indépendant de `JWT_SECRET` (pas de 503).
# --------------------------------------------------------------------------- #
class PasswordResetRequestSchema(BaseModel):
    """Corps de `POST /auth/password/reset/request`."""

    # Identifiant = téléphone **ou** e-mail (auto-détecté côté domaine).
    identifier: str = Field(min_length=1, max_length=320, examples=["0700000000"])


class PasswordResetConfirmSchema(BaseModel):
    """Corps de `POST /auth/password/reset/confirm`. Aucun champ n'est renvoyé."""

    identifier: str = Field(min_length=1, max_length=320, examples=["0700000000"])
    # `min_length=1` (jamais la longueur exacte de l'OTP) pour ne pas divulguer la
    # politique du code (anti-énumération).
    code: str = Field(min_length=1, max_length=32, examples=["123456"])
    new_password: str = Field(
        min_length=MIN_LENGTH,
        max_length=MAX_LENGTH,
        examples=["nouveau-motdepasse-solide"],
    )


class MessageResponse(BaseModel):
    """Réponse générique porteuse d'un seul message — **aucun** secret ni PII."""

    detail: str


def _get_password_reset_otp_repository(request: Request) -> OtpRepository:
    """Dépôt OTP **dédié au reset** (singleton `app.state`), distinct de l'inscription.

    La demande et la confirmation partagent la même instance : un code émis à la
    demande est retrouvé à la confirmation. Repli sûr si l'état n'est pas câblé.
    """

    repo = getattr(request.app.state, "password_reset_otp_repository", None)
    if repo is None:
        repo = InMemoryOtpRepository()
        request.app.state.password_reset_otp_repository = repo
    return repo


def _get_password_reset_sender(request: Request) -> OtpSender:
    """Expéditeur OTP de reset (stub multi-canal). Repli sûr si non câblé."""

    sender = getattr(request.app.state, "password_reset_otp_sender", None)
    if sender is None:
        sender = StubOtpSender()
        request.app.state.password_reset_otp_sender = sender
    return sender


def _get_password_reset_rate_limiter(request: Request) -> LoginRateLimiter:
    """Limiteur anti-flood **dédié au reset** (singleton `app.state`).

    Distinct du limiteur de connexion : rate-limiter la demande de reset ne doit
    pas verrouiller la connexion (et inversement). Repli sûr avec les seuils de
    reset d'`AuthConfig` si l'état n'est pas configuré.
    """

    limiter = getattr(request.app.state, "password_reset_rate_limiter", None)
    if limiter is None:
        config: AuthConfig = (
            getattr(request.app.state, "auth_config", None) or AuthConfig()
        )
        limiter = InMemoryLoginRateLimiter(
            max_attempts=config.password_reset_max_attempts,
            window=config.password_reset_window,
            lockout=config.password_reset_lockout,
        )
        request.app.state.password_reset_rate_limiter = limiter
    return limiter


def get_request_password_reset(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> RequestPasswordReset:
    """Assemble le cas d'usage de **demande** de reset (aucune règle métier ici).

    L'OTP de reset est **toujours actif** (jamais gouverné par `OTP_ENABLED`) et
    la route **ne dépend pas** de `token_service` (pas de `503`).
    """

    config: AuthConfig = getattr(request.app.state, "auth_config", None) or AuthConfig()
    return RequestPasswordReset(
        SqlUserRepository(session),
        _get_password_reset_otp_repository(request),
        _get_password_reset_sender(request),
        rate_limiter=_get_password_reset_rate_limiter(request),
        otp_length=config.otp_length,
        otp_ttl=config.password_reset_otp_ttl,
        otp_max_attempts=config.password_reset_otp_max_attempts,
    )


def get_confirm_password_reset(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> ConfirmPasswordReset:
    """Assemble le cas d'usage de **confirmation** de reset (dépôt OTP dédié partagé)."""

    return ConfirmPasswordReset(
        SqlUserRepository(session),
        _get_password_reset_otp_repository(request),
        hasher,
    )


@router.post(
    "/password/reset/request",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Demande un code de réinitialisation du mot de passe (SMS ou e-mail)",
)
def request_password_reset(
    payload: PasswordResetRequestSchema,
    request: Request,
    usecase: Annotated[RequestPasswordReset, Depends(get_request_password_reset)],
) -> MessageResponse:
    """Émet un OTP de reset ; **toujours** `202` générique (anti-énumération).

    `429` + `Retry-After` si la demande est rate-limitée. Ne divulgue jamais si un
    compte existe pour l'identifiant fourni ; ne renvoie **jamais** le code OTP.
    """

    command = PasswordResetRequestCommand(
        identifier=payload.identifier,
        client_ip=_client_ip(request),
    )
    try:
        usecase.execute(command)
    except TooManyLoginAttempts as exc:
        headers = (
            {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_PASSWORD_RESET_RATE_LIMITED_DETAIL,
            headers=headers,
        ) from exc

    return MessageResponse(detail=_PASSWORD_RESET_REQUEST_DETAIL)


@router.post(
    "/password/reset/confirm",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirme la réinitialisation (code + nouveau mot de passe)",
)
def confirm_password_reset(
    payload: PasswordResetConfirmSchema,
    usecase: Annotated[ConfirmPasswordReset, Depends(get_confirm_password_reset)],
) -> MessageResponse:
    """Vérifie l'OTP puis remplace le mot de passe ; `400` générique / `422` politique.

    `400` **unique** pour tout échec d'OTP (invalide, expiré, trop d'essais, déjà
    consommé) **et** identifiant sans défi (cause exacte jamais divulguée). `422`
    si le nouveau mot de passe viole la politique. Après succès, l'ancien mot de
    passe ne s'authentifie plus via `POST /auth/login`.
    """

    command = PasswordResetConfirmCommand(
        identifier=payload.identifier,
        code=payload.code,
        new_password=payload.new_password,
    )
    try:
        usecase.execute(command)
    except InvalidPassword as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except (InvalidOtp, OtpExpired) as exc:
        # Message générique constant (jamais str(exc)) : cause exacte non divulguée.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_PASSWORD_RESET_INVALID_OTP_DETAIL,
        ) from exc

    return MessageResponse(detail=_PASSWORD_RESET_CONFIRM_DETAIL)


__all__ = [
    "router",
    "RegisterRequest",
    "UserResponse",
    "LoginRequest",
    "RefreshRequest",
    "TokenResponse",
    "PasswordResetRequestSchema",
    "PasswordResetConfirmSchema",
    "MessageResponse",
]
