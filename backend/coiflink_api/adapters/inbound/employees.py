"""Adapter entrant (driving) : router HTTP de gestion des employés (US-1.4, #13).

Expose la **création d'un compte coiffeur** par un gérant :
`POST /salons/{salon_id}/employees`. La route traduit la requête HTTP en commande
applicative, assemble le cas d'usage `CreateEmployee` via l'injection de
dépendances FastAPI (**le rôle `HAIRDRESSER` est fixé côté serveur**), puis
retraduit les erreurs de domaine en codes HTTP :
- `PhoneAlreadyInUse` / `EmailAlreadyInUse` / `EmployeeAlreadyInSalon` →
  **409 Conflict** ;
- `InvalidPhone` / `InvalidPassword` / `InvalidName` / `InvalidEmail` →
  **422 Unprocessable Entity**.

Sécurité (RBAC #12, ADR-0015) : la route est **protégée** par la permission
`EMPLOYEE_MANAGE` (matrice §4.1 — seul le `MANAGER` la possède) **et** par la
portée salon (`require_salon_scope`) — un gérant ne crée un employé que sur
**son** salon ; un accès hors périmètre renvoie le `403` générique (aucun oracle
d'existence). Le chemin **n'est pas** ajouté à `PUBLIC_ROUTE_PATHS`.

Invariant anti-élévation de privilège : **aucun** champ `role` n'est déclaré dans
la requête (`CreateEmployeeRequest`) ; le rôle est attribué par le câblage, jamais
lu du corps. La réponse (`UserResponse`) n'expose **jamais** `password` ni
`password_hash` (PRD §11.1). Le mot de passe initial reçu n'est ni journalisé ni
renvoyé.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.auth import UserResponse, get_password_hasher
from coiflink_api.adapters.inbound.security import require_permission, require_salon_scope
from coiflink_api.adapters.outbound.persistence.salon_member_repository import (
    SqlSalonMemberRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.adapters.outbound.persistence.user_repository import SqlUserRepository
from coiflink_api.application.employees import CreateEmployee, CreateEmployeeCommand
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.enums import Role
from coiflink_api.domain.errors import (
    EmailAlreadyInUse,
    EmployeeAlreadyInSalon,
    InvalidEmail,
    InvalidName,
    InvalidPassword,
    InvalidPhone,
    PhoneAlreadyInUse,
)
from coiflink_api.domain.password import MAX_LENGTH, MIN_LENGTH
from coiflink_api.domain.permissions import Permission

router = APIRouter(prefix="/salons", tags=["employees"])


class CreateEmployeeRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/employees`.

    **Aucun** champ `role` : le rôle `HAIRDRESSER` est imposé côté serveur
    (anti-élévation de privilège). `password` est le mot de passe **initial** défini
    par le gérant, communiqué hors bande — le coiffeur pourra le changer via le
    reset OTP (#11). Il n'est jamais renvoyé.
    """

    full_name: str = Field(min_length=1, max_length=255, examples=["Awa Koné"])
    phone: str = Field(min_length=1, max_length=32, examples=["0700000000"])
    password: str = Field(
        min_length=MIN_LENGTH,
        max_length=MAX_LENGTH,
        examples=["motdepasse-solide"],
    )
    email: EmailStr | None = Field(default=None, examples=["awa@example.com"])


def get_create_employee(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> CreateEmployee:
    """Assemble le cas d'usage de création d'employé (`role=HAIRDRESSER` fixé).

    Le rôle `HAIRDRESSER` est attribué **côté serveur** ; aucun champ `role` n'est
    lu depuis la requête (anti-élévation de privilège, cohérent avec #8/#9).
    """

    return CreateEmployee(
        SqlUserRepository(session),
        hasher,
        SqlSalonMemberRepository(session),
        role=Role.HAIRDRESSER.value,
    )


@router.post(
    "/{salon_id}/employees",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un compte coiffeur rattaché à un salon (gérant)",
    responses={
        401: {"description": "Jeton absent, invalide, expiré, ou refresh présenté en accès"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        409: {"description": "Téléphone/e-mail déjà pris, ou employé déjà membre du salon"},
        422: {"description": "Nom, téléphone, mot de passe ou e-mail invalides"},
        503: {"description": "JWT_SECRET non configuré"},
    },
)
def create_employee(
    salon_id: uuid.UUID,
    payload: CreateEmployeeRequest,
    usecase: Annotated[CreateEmployee, Depends(get_create_employee)],
    # Gardes RBAC (#12) : permission §4.1 **et** portée salon §11.2. `salon_id` est
    # lu du chemin par `require_salon_scope`. Les deux dépendances résolvent le même
    # `Principal` (via `get_current_principal`) — pas de double lecture de compte.
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        object, Depends(require_permission(Permission.EMPLOYEE_MANAGE))
    ],
) -> UserResponse:
    """Crée un coiffeur (`role=HAIRDRESSER`, `status=ACTIVE`) rattaché à `salon_id`.

    Le coiffeur pourra ensuite se connecter via `POST /auth/login` (#10) avec un
    **périmètre restreint** : sa portée provient de son appartenance au salon
    (`salon_members`). Refuse un doublon de téléphone/e-mail ou une appartenance
    déjà existante (`409`). Ne renvoie **aucun** secret.
    """

    command = CreateEmployeeCommand(
        salon_id=salon_id,
        full_name=payload.full_name,
        phone=payload.phone,
        password=payload.password,
        email=payload.email,
    )
    try:
        user = usecase.execute(command)
    except (PhoneAlreadyInUse, EmailAlreadyInUse, EmployeeAlreadyInSalon) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (InvalidPhone, InvalidPassword, InvalidName, InvalidEmail) as exc:
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


__all__ = ["router", "CreateEmployeeRequest"]
