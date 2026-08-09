"""Adapter entrant (driving) : router HTTP de gestion des employés (US-1.4, #13 ; #150).

Expose la **gestion des coiffeuses** par un gérant :
- `POST /salons/{salon_id}/employees` — créer un compte coiffeur ;
- `GET /salons/{salon_id}/employees` — lister les coiffeuses du salon ;
- `GET /salons/{salon_id}/employees/{employee_id}` — charger une coiffeuse ;
- `PUT /salons/{salon_id}/employees/{employee_id}` — modifier son profil ;
- `DELETE /salons/{salon_id}/employees/{employee_id}` — désactiver (retire
  l'éligibilité aux **nouvelles** affectations, `salon_members.status`) ;
- `POST /salons/{salon_id}/employees/{employee_id}/reactivate` — réactiver.

Chaque route traduit la requête HTTP en commande applicative, assemble le cas
d'usage via l'injection de dépendances FastAPI (**le rôle `HAIRDRESSER` est
fixé côté serveur**), puis retraduit les erreurs de domaine en codes HTTP :
- `PhoneAlreadyInUse` / `EmailAlreadyInUse` / `EmployeeAlreadyInSalon` →
  **409 Conflict** ;
- `InvalidPhone` / `InvalidPassword` / `InvalidName` / `InvalidEmail` /
  `InvalidEmployeeSpecialties` → **422 Unprocessable Entity** ;
- `EmployeeNotFound` → **404 Not Found** (après portée, aucun oracle §11.2).

Sécurité (RBAC #12, ADR-0015) : toutes les routes sont **protégées** par la
permission `EMPLOYEE_MANAGE` (matrice §4.1 — seul le `MANAGER` la possède)
**et** par la portée salon (`require_salon_scope`) — un gérant ne gère
d'employés que sur **son** salon ; un accès hors périmètre renvoie le `403`
générique (aucun oracle d'existence). Aucun chemin n'est ajouté à
`PUBLIC_ROUTE_PATHS`.

Invariant anti-élévation de privilège : **aucun** champ `role`/`status` n'est
déclaré dans les requêtes ; le rôle est attribué par le câblage, le statut
d'appartenance est piloté par les **actions dédiées** (`DELETE`/`.../
reactivate`), jamais par la modification de profil. Les réponses (`
EmployeeResponse`) n'exposent **jamais** `password` ni `password_hash`.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.auth import get_password_hasher
from coiflink_api.adapters.inbound.security import require_permission, require_salon_scope
from coiflink_api.adapters.outbound.persistence.audit_log_repository import SqlAuditLog
from coiflink_api.adapters.outbound.persistence.salon_member_repository import (
    SqlSalonMemberRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.adapters.outbound.persistence.user_repository import SqlUserRepository
from coiflink_api.application.employees import (
    CreateEmployee,
    CreateEmployeeCommand,
    DeactivateEmployee,
    GetSalonEmployee,
    ListSalonEmployees,
    ReactivateEmployee,
    UpdateEmployeeProfile,
    UpdateEmployeeProfileCommand,
)
from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.employee import Employee
from coiflink_api.domain.enums import Role
from coiflink_api.domain.errors import (
    EmailAlreadyInUse,
    EmployeeAlreadyInSalon,
    EmployeeNotFound,
    InvalidEmail,
    InvalidEmployeeSpecialties,
    InvalidName,
    InvalidPassword,
    InvalidPhone,
    PhoneAlreadyInUse,
)
from coiflink_api.domain.password import MAX_LENGTH, MIN_LENGTH
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

router = APIRouter(prefix="/salons", tags=["employees"])


# --------------------------------------------------------------------------- #
# Schémas Pydantic.
# --------------------------------------------------------------------------- #
class CreateEmployeeRequest(BaseModel):
    """Corps de `POST /salons/{salon_id}/employees`.

    **Aucun** champ `role` : le rôle `HAIRDRESSER` est imposé côté serveur
    (anti-élévation de privilège). `password` est le mot de passe **initial**
    défini par le gérant, communiqué hors bande — le coiffeur pourra le
    changer via le reset OTP (#11). Il n'est jamais renvoyé. `specialties`/
    `hired_at` (facultatifs, #150) sont les champs professionnels.
    """

    full_name: str = Field(min_length=1, max_length=255, examples=["Awa Koné"])
    phone: str = Field(min_length=1, max_length=32, examples=["0700000000"])
    password: str = Field(
        min_length=MIN_LENGTH,
        max_length=MAX_LENGTH,
        examples=["motdepasse-solide"],
    )
    email: EmailStr | None = Field(default=None, examples=["awa@example.com"])
    specialties: str | None = Field(
        default=None, examples=["Tresses, colorations, lissages"]
    )
    hired_at: datetime.date | None = Field(default=None, examples=["2026-01-15"])


class UpdateEmployeeRequest(BaseModel):
    """Corps de `PUT /salons/{salon_id}/employees/{employee_id}` (#150).

    Sémantique **replace** (comme la modification RDV #23/fiche client #144) :
    remplace intégralement identité + champs pro. **Aucun** `role`/`status` :
    la disponibilité se pilote via `DELETE`/`.../reactivate`, jamais ici.
    """

    full_name: str = Field(min_length=1, max_length=255, examples=["Awa Koné"])
    phone: str = Field(min_length=1, max_length=32, examples=["0700000000"])
    email: EmailStr | None = Field(default=None, examples=["awa@example.com"])
    specialties: str | None = Field(
        default=None, examples=["Tresses, colorations, lissages"]
    )
    hired_at: datetime.date | None = Field(default=None, examples=["2026-01-15"])


class EmployeeResponse(BaseModel):
    """Représentation publique d'une coiffeuse — **sans** aucun secret.

    `status` reflète `salon_members.status` (disponibilité aux affectations),
    **pas** `users.status` (compte global).
    """

    id: uuid.UUID
    full_name: str
    phone: str
    email: str | None
    role: str
    status: str
    specialties: str | None
    hired_at: datetime.date | None
    created_at: datetime.datetime


def _employee_response(employee: Employee) -> EmployeeResponse:
    return EmployeeResponse(
        id=employee.id,
        full_name=employee.full_name,
        phone=employee.phone,
        email=employee.email,
        role=employee.role,
        status=employee.status,
        specialties=employee.specialties,
        hired_at=employee.hired_at,
        created_at=employee.created_at,
    )


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_audit_log(
    session: Annotated[Session, Depends(get_session)],
) -> AuditLog:
    """Journal d'audit §11.4 adossé à la **même** session (atomicité, patron #20)."""

    return SqlAuditLog(session)


def get_salon_member_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SqlSalonMemberRepository:
    """Dépôt d'appartenances employé↔salon adossé à la session de la requête."""

    return SqlSalonMemberRepository(session)


def get_create_employee(
    session: Annotated[Session, Depends(get_session)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> CreateEmployee:
    """Assemble le cas d'usage de création d'employé (`role=HAIRDRESSER` fixé).

    Le rôle `HAIRDRESSER` est attribué **côté serveur** ; aucun champ `role` n'est
    lu depuis la requête (anti-élévation de privilège, cohérent avec #8/#9).
    """

    return CreateEmployee(
        SqlUserRepository(session),
        hasher,
        SqlSalonMemberRepository(session),
        audit_log,
        role=Role.HAIRDRESSER.value,
    )


def get_list_salon_employees(
    members: Annotated[SqlSalonMemberRepository, Depends(get_salon_member_repository)],
) -> ListSalonEmployees:
    return ListSalonEmployees(members)


def get_salon_employee(
    members: Annotated[SqlSalonMemberRepository, Depends(get_salon_member_repository)],
) -> GetSalonEmployee:
    return GetSalonEmployee(members)


def get_update_employee_profile(
    session: Annotated[Session, Depends(get_session)],
    members: Annotated[SqlSalonMemberRepository, Depends(get_salon_member_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> UpdateEmployeeProfile:
    return UpdateEmployeeProfile(SqlUserRepository(session), members, audit_log)


def get_deactivate_employee(
    members: Annotated[SqlSalonMemberRepository, Depends(get_salon_member_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> DeactivateEmployee:
    return DeactivateEmployee(members, audit_log)


def get_reactivate_employee(
    members: Annotated[SqlSalonMemberRepository, Depends(get_salon_member_repository)],
    audit_log: Annotated[AuditLog, Depends(get_audit_log)],
) -> ReactivateEmployee:
    return ReactivateEmployee(members, audit_log)


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.post(
    "/{salon_id}/employees",
    response_model=EmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un compte coiffeur rattaché à un salon (gérant)",
    responses={
        401: {"description": "Jeton absent, invalide, expiré, ou refresh présenté en accès"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        409: {"description": "Téléphone/e-mail déjà pris, ou employé déjà membre du salon"},
        422: {"description": "Nom, téléphone, mot de passe, e-mail ou spécialités invalides"},
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
    principal: Annotated[
        Principal, Depends(require_permission(Permission.EMPLOYEE_MANAGE))
    ],
) -> EmployeeResponse:
    """Crée un coiffeur (`role=HAIRDRESSER`, `status=ACTIVE`) rattaché à `salon_id`.

    Le coiffeur pourra ensuite se connecter via `POST /auth/login` (#10) avec un
    **périmètre restreint** : sa portée provient de son appartenance au salon
    (`salon_members`). Refuse un doublon de téléphone/e-mail ou une appartenance
    déjà existante (`409`). Ne renvoie **aucun** secret.
    """

    command = CreateEmployeeCommand(
        salon_id=salon_id,
        actor_id=principal.id,
        full_name=payload.full_name,
        phone=payload.phone,
        password=payload.password,
        email=payload.email,
        specialties=payload.specialties,
        hired_at=payload.hired_at,
    )
    try:
        employee = usecase.execute(command)
    except (PhoneAlreadyInUse, EmailAlreadyInUse, EmployeeAlreadyInSalon) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (
        InvalidPhone,
        InvalidPassword,
        InvalidName,
        InvalidEmail,
        InvalidEmployeeSpecialties,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return _employee_response(employee)


@router.get(
    "/{salon_id}/employees",
    response_model=list[EmployeeResponse],
    summary="Lister les coiffeuses du salon (gérant)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
    },
)
def list_employees(
    salon_id: uuid.UUID,
    usecase: Annotated[ListSalonEmployees, Depends(get_list_salon_employees)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.EMPLOYEE_MANAGE))
    ],
) -> list[EmployeeResponse]:
    """Liste les coiffeuses **du salon**, triées par nom d'affichage."""

    employees = usecase.execute(salon_id)
    return [_employee_response(employee) for employee in employees]


@router.get(
    "/{salon_id}/employees/{employee_id}",
    response_model=EmployeeResponse,
    summary="Charger une coiffeuse du salon (gérant)",
    responses={
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        404: {"description": "Coiffeuse inexistante ou hors salon (après portée)"},
    },
)
def get_employee(
    salon_id: uuid.UUID,
    employee_id: uuid.UUID,
    usecase: Annotated[GetSalonEmployee, Depends(get_salon_employee)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    _principal: Annotated[
        Principal, Depends(require_permission(Permission.EMPLOYEE_MANAGE))
    ],
) -> EmployeeResponse:
    """Charge une coiffeuse **du salon** ; `404` si inexistante ou hors salon."""

    try:
        employee = usecase.execute(salon_id, employee_id)
    except EmployeeNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _employee_response(employee)


@router.put(
    "/{salon_id}/employees/{employee_id}",
    response_model=EmployeeResponse,
    summary="Modifier le profil d'une coiffeuse du salon (gérant, §11.4)",
    responses={
        200: {"description": "Profil mis à jour"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        404: {"description": "Coiffeuse inexistante ou hors salon (après portée)"},
        409: {"description": "Téléphone/e-mail déjà pris par un autre compte"},
        422: {"description": "Nom, téléphone, e-mail ou spécialités invalides"},
    },
)
def update_employee(
    salon_id: uuid.UUID,
    employee_id: uuid.UUID,
    payload: UpdateEmployeeRequest,
    usecase: Annotated[UpdateEmployeeProfile, Depends(get_update_employee_profile)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.EMPLOYEE_MANAGE))
    ],
) -> EmployeeResponse:
    """Remplace identité + champs pro de la coiffeuse ; journalise `EMPLOYEE_UPDATED`.

    `full_name`/`phone` sont revalidés et normalisés côté serveur. Un doublon
    de téléphone/e-mail **sur un autre compte** est un `409` (unicité globale
    `users`, distincte de l'appartenance salon).
    """

    command = UpdateEmployeeProfileCommand(
        full_name=payload.full_name,
        phone=payload.phone,
        email=payload.email,
        specialties=payload.specialties,
        hired_at=payload.hired_at,
    )
    try:
        employee = usecase.execute(salon_id, employee_id, principal.id, command)
    except EmployeeNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except (PhoneAlreadyInUse, EmailAlreadyInUse) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (InvalidPhone, InvalidName, InvalidEmail, InvalidEmployeeSpecialties) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _employee_response(employee)


@router.delete(
    "/{salon_id}/employees/{employee_id}",
    response_model=EmployeeResponse,
    summary="Désactiver une coiffeuse (retire l'éligibilité aux affectations, §11.4)",
    responses={
        200: {"description": "Coiffeuse désactivée (salon_members.status = INACTIVE)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        404: {"description": "Coiffeuse inexistante ou hors salon (après portée)"},
    },
)
def deactivate_employee(
    salon_id: uuid.UUID,
    employee_id: uuid.UUID,
    usecase: Annotated[DeactivateEmployee, Depends(get_deactivate_employee)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.EMPLOYEE_MANAGE))
    ],
) -> EmployeeResponse:
    """Désactive la coiffeuse (`salon_members.status = INACTIVE`) — idempotent.

    Ne bloque **pas** sa connexion (`users.status` inchangé) : retire
    seulement son éligibilité aux **nouvelles** affectations de ce salon
    (`_require_salon_hairdresser`). Appeler deux fois est **sans effet de
    bord** (même statut cible).
    """

    try:
        employee = usecase.execute(salon_id, employee_id, principal.id)
    except EmployeeNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _employee_response(employee)


@router.post(
    "/{salon_id}/employees/{employee_id}/reactivate",
    response_model=EmployeeResponse,
    summary="Réactiver une coiffeuse (§11.4)",
    responses={
        200: {"description": "Coiffeuse réactivée (salon_members.status = ACTIVE)"},
        401: {"description": "Jeton absent, invalide ou expiré"},
        403: {"description": "Rôle insuffisant ou salon hors périmètre (message générique)"},
        404: {"description": "Coiffeuse inexistante ou hors salon (après portée)"},
    },
)
def reactivate_employee(
    salon_id: uuid.UUID,
    employee_id: uuid.UUID,
    usecase: Annotated[ReactivateEmployee, Depends(get_reactivate_employee)],
    _scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.EMPLOYEE_MANAGE))
    ],
) -> EmployeeResponse:
    """Réactive la coiffeuse (`salon_members.status = ACTIVE`) — idempotent."""

    try:
        employee = usecase.execute(salon_id, employee_id, principal.id)
    except EmployeeNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _employee_response(employee)


__all__ = [
    "router",
    "CreateEmployeeRequest",
    "UpdateEmployeeRequest",
    "EmployeeResponse",
]
