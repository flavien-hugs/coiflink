"""Adapter entrant (driving) : router HTTP d'authentification (ADR-0003/0008).

Expose l'**inscription client** `POST /auth/register` (US-1.1, issue #8). Traduit
la requête HTTP en commande applicative, assemble le cas d'usage `InscrireClient`
via l'injection de dépendances FastAPI, puis retraduit les erreurs de domaine en
codes HTTP :
- `TelephoneDejaUtilise` / `EmailDejaUtilise` → **409 Conflict** ;
- `TelephoneInvalide` / `MotDePasseInvalide` / `NomInvalide` / `EmailInvalide` →
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

from coiflink_api.adapters.sortant.persistance.depot_utilisateur import (
    DepotUtilisateurSql,
)
from coiflink_api.adapters.sortant.persistance.session import get_session
from coiflink_api.adapters.sortant.securite.hacheur import HacheurArgon2
from coiflink_api.application.inscription import CommandeInscription, InscrireClient
from coiflink_api.application.ports.hacheur_mot_de_passe import HacheurMotDePasse
from coiflink_api.config import AuthConfig
from coiflink_api.domaine.erreurs import (
    EmailDejaUtilise,
    EmailInvalide,
    MotDePasseInvalide,
    NomInvalide,
    TelephoneDejaUtilise,
    TelephoneInvalide,
)
from coiflink_api.domaine.mot_de_passe import LONGUEUR_MAX, LONGUEUR_MIN

router = APIRouter(prefix="/auth", tags=["auth"])


class InscriptionRequete(BaseModel):
    """Corps de `POST /auth/register`. `password` n'est jamais renvoyé."""

    full_name: str = Field(min_length=1, max_length=255, examples=["Awa Koné"])
    phone: str = Field(min_length=1, max_length=32, examples=["0700000000"])
    password: str = Field(
        min_length=LONGUEUR_MIN,
        max_length=LONGUEUR_MAX,
        examples=["motdepasse-solide"],
    )
    email: EmailStr | None = Field(default=None, examples=["awa@example.com"])


class UtilisateurReponse(BaseModel):
    """Représentation publique d'un utilisateur — **sans** aucun secret."""

    id: uuid.UUID
    full_name: str
    phone: str
    email: str | None
    role: str
    status: str
    created_at: datetime.datetime


def get_hacheur() -> HacheurMotDePasse:
    """Fournit l'adapter de hachage (argon2). Surchargable en test."""

    return HacheurArgon2()


def get_inscrire_client(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    hacheur: Annotated[HacheurMotDePasse, Depends(get_hacheur)],
) -> InscrireClient:
    """Assemble le cas d'usage `InscrireClient` avec ses adapters (DI).

    Lit la configuration OTP et les adapters singletons déposés sur `app.state`
    par le composition root ; retombe sur des défauts sûrs (OTP désactivé) si
    l'état n'est pas configuré.
    """

    config: AuthConfig = getattr(request.app.state, "auth_config", None) or AuthConfig()
    return InscrireClient(
        DepotUtilisateurSql(session),
        hacheur,
        otp_active=config.otp_active,
        expediteur_otp=getattr(request.app.state, "expediteur_otp", None),
        depot_otp=getattr(request.app.state, "depot_otp", None),
        longueur_otp=config.otp_longueur,
        ttl_otp=config.otp_ttl,
        max_essais_otp=config.otp_max_essais,
    )


@router.post(
    "/register",
    response_model=UtilisateurReponse,
    status_code=status.HTTP_201_CREATED,
    summary="Inscription d'un client (nom, téléphone, mot de passe)",
)
def inscrire_client(
    requete: InscriptionRequete,
    usecase: Annotated[InscrireClient, Depends(get_inscrire_client)],
) -> UtilisateurReponse:
    """Crée un compte client (`role=CLIENT`) ; refuse un doublon de téléphone."""

    commande = CommandeInscription(
        full_name=requete.full_name,
        telephone=requete.phone,
        mot_de_passe=requete.password,
        email=requete.email,
    )
    try:
        utilisateur = usecase.executer(commande)
    except (TelephoneDejaUtilise, EmailDejaUtilise) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (
        TelephoneInvalide,
        MotDePasseInvalide,
        NomInvalide,
        EmailInvalide,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return UtilisateurReponse(
        id=utilisateur.id,
        full_name=utilisateur.full_name,
        phone=utilisateur.telephone,
        email=utilisateur.email,
        role=utilisateur.role,
        status=utilisateur.status,
        created_at=utilisateur.created_at,
    )


__all__ = ["router", "InscriptionRequete", "UtilisateurReponse"]
