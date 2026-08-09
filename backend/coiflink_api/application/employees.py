"""Cas d'usage : **gestion des coiffeuses** par un gérant (US-1.4, #13 ; #150).

Orchestre la création, la lecture, la modification de profil et l'activation/
désactivation d'un compte `HAIRDRESSER` **rattaché à un salon** — la source
d'autorité de sa **portée** (PRD §11.2, ADR-0016) et, depuis #150, de sa
**disponibilité aux affectations** (`salon_members.status`).

Comme `RegisterUser` (#8/#9), `CreateEmployee` ne dépend que de **ports**
(aucune dépendance FastAPI/SQLAlchemy) et le **rôle cible est fixé au
câblage**, jamais lu depuis la commande ni la requête HTTP : un gérant ne peut
créer ni `MANAGER`, ni `ADMIN`, ni `CLIENT` (garde-fou anti-élévation de
privilège, PRD §11.1).

**Création** — séquence : valider le nom + le mot de passe → **normaliser le
téléphone** → **pré-vérifier le doublon** → **hacher** → **créer**
l'utilisateur (`role` injecté, `status=ACTIVE`) → **rattacher** au salon
(`add_member`, avec champs pro) → **journaliser** `EMPLOYEE_CREATED` → retourner
l'entité **sans** secret. Atomicité : les trois écritures (utilisateur +
appartenance + audit) passent par la **même `Session`**, committées ensemble
par `get_session`. Le mot de passe en clair n'est ni journalisé ni conservé
au-delà du hachage.

**Modification de profil** — met à jour **identité** (`users`) **et** champs
pro (`salon_members`) dans la **même** unité de travail ; journalise
`EMPLOYEE_UPDATED` avec un diff **neutre** (noms de champs uniquement, patron
`CUSTOMER_UPDATED` #144).

**Activation/désactivation** — pilote `salon_members.status`
(`ACTIVE`/`INACTIVE`), **jamais** `users.status` (compte global, hors
périmètre) : désactiver une coiffeuse la retire de l'éligibilité aux
**nouvelles** affectations de ce salon (`_require_salon_hairdresser`), sans
bloquer sa connexion.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from coiflink_api.application.ports.audit_log import AuditLog
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.application.ports.salon_member_repository import SalonMemberRepository
from coiflink_api.application.ports.user_repository import UserRepository
from coiflink_api.domain.audit import ENTITY_TYPE_SALON_MEMBER, AuditAction, AuditEntry
from coiflink_api.domain.employee import Employee, normalize_specialties
from coiflink_api.domain.enums import Role, UserStatus, values
from coiflink_api.domain.errors import EmployeeNotFound, PhoneAlreadyInUse
from coiflink_api.domain.membership import SalonMembershipToCreate
from coiflink_api.domain.password import validate_password
from coiflink_api.domain.phone import normalize_phone
from coiflink_api.domain.user import UserToCreate, validate_name

# Rôles autorisés pour un employé, dérivés du domaine (source de vérité `Role`).
# Garde-fou au câblage : un rôle inconnu échoue à la construction du cas d'usage.
_ROLE_VALUES: frozenset[str] = frozenset(values(Role))

# Champs comparés pour le diff **neutre** de la modification (ordre stable),
# miroir de `_APPOINTMENT_DIFF_FIELDS`/`CUSTOMER_UPDATED` (#144).
_EMPLOYEE_DIFF_FIELDS: tuple[str, ...] = (
    "full_name",
    "phone",
    "email",
    "specialties",
    "hired_at",
)


@dataclass(frozen=True)
class CreateEmployeeCommand:
    """Données d'entrée du cas d'usage (mot de passe en clair, éphémère).

    `salon_id` est la **cible** validée en amont par la garde de portée
    (`require_salon_scope`) : le gérant ne peut créer un employé que sur **son**
    salon. Aucun champ `role` : il est fixé côté serveur.
    """

    salon_id: uuid.UUID
    actor_id: uuid.UUID
    full_name: str
    phone: str
    password: str
    email: str | None = None
    specialties: str | None = None
    hired_at: datetime.date | None = None


class CreateEmployee:
    """Crée un compte employé et le rattache à un salon (rôle fixé au câblage)."""

    def __init__(
        self,
        repository: UserRepository,
        hasher: PasswordHasher,
        members: SalonMemberRepository,
        audit_log: AuditLog,
        *,
        role: str = Role.HAIRDRESSER.value,
    ) -> None:
        if role not in _ROLE_VALUES:
            raise ValueError(f"Rôle d'employé inconnu : {role!r}")
        self._role = role
        self._repository = repository
        self._hasher = hasher
        self._members = members
        self._audit_log = audit_log

    def execute(self, command: CreateEmployeeCommand) -> Employee:
        """Crée l'employé (rôle injecté) et l'ajoute au salon ; retourne l'entité."""

        name = validate_name(command.full_name)
        validate_password(command.password)
        phone = normalize_phone(command.phone)
        email = command.email or None
        specialties = normalize_specialties(command.specialties)

        # Pré-vérification applicative du doublon (message clair → 409).
        if self._repository.phone_exists(phone):
            raise PhoneAlreadyInUse(
                "Ce numéro de téléphone est déjà associé à un compte."
            )

        password_hash = self._hasher.hash(command.password)

        to_create = UserToCreate(
            full_name=name,
            phone=phone,
            password_hash=password_hash,
            email=email,
            role=self._role,
            status=UserStatus.ACTIVE.value,
        )
        # `create` peut lever PhoneAlreadyInUse/EmailAlreadyInUse (fallback course
        # concurrente via les contraintes base) : on laisse remonter tel quel.
        user = self._repository.create(to_create)

        # Rattachement au salon : source d'autorité de la portée (§11.2). Une
        # violation d'unicité `(salon_id, user_id)` remonte en
        # `EmployeeAlreadyInSalon`. Même Session ⇒ rollback atomique si échec.
        self._members.add_member(
            SalonMembershipToCreate(
                salon_id=command.salon_id,
                user_id=user.id,
                role=self._role,
                status=UserStatus.ACTIVE.value,
            )
        )
        # Champs pro facultatifs (#150) : posés dans un second temps (même
        # Session) plutôt que d'étendre `SalonMembershipToCreate` — évite de
        # dupliquer la validation dans l'entité d'écriture d'`add_member`.
        if specialties is not None or command.hired_at is not None:
            self._members.update_professional_fields(
                command.salon_id,
                user.id,
                specialties=specialties,
                hired_at=command.hired_at,
            )

        # Audit §11.4 dans la **même** unité de travail que la création
        # (patron #20) : entrée neutre, aucune valeur (nom/téléphone/e-mail).
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.EMPLOYEE_CREATED.value,
                actor_user_id=command.actor_id,
                salon_id=command.salon_id,
                entity_type=ENTITY_TYPE_SALON_MEMBER,
                entity_id=user.id,
                metadata={},
            )
        )

        return Employee(
            id=user.id,
            full_name=user.full_name,
            phone=user.phone,
            email=user.email,
            role=self._role,
            status=UserStatus.ACTIVE.value,
            specialties=specialties,
            hired_at=command.hired_at,
            created_at=user.created_at,
        )


@dataclass(frozen=True)
class UpdateEmployeeProfileCommand:
    """Champs saisissables d'une modification de profil coiffeuse (#150).

    Sémantique **replace** (comme la modification RDV #23) : remplace
    intégralement identité + champs pro. Ne porte **jamais** `salon_id`
    (chemin) ni `status` (action dédiée activer/désactiver).
    """

    full_name: str
    phone: str
    email: str | None
    specialties: str | None
    hired_at: datetime.date | None


def _changed_employee_fields(current: Employee, updated: Employee) -> list[str]:
    """Noms des champs dont la valeur change (diff neutre, §11.4, #144)."""

    return [
        field
        for field in _EMPLOYEE_DIFF_FIELDS
        if getattr(current, field) != getattr(updated, field)
    ]


class UpdateEmployeeProfile:
    """Modifie identité + champs pro d'une coiffeuse **du salon** et journalise (#150).

    Séquence (patron portée→écriture→audit) : charger la coiffeuse **du salon**
    (`EmployeeNotFound` si inexistante/hors salon — indiscernables, §11.2) →
    normaliser (nom, téléphone, spécialités) → écrire l'identité (`users`, peut
    lever `PhoneAlreadyInUse`/`EmailAlreadyInUse` — unicité **globale**) →
    écrire les champs pro (`salon_members`) → audit `EMPLOYEE_UPDATED` **neutre**
    dans la **même** unité de travail.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        members: SalonMemberRepository,
        audit_log: AuditLog,
    ) -> None:
        self._users = user_repository
        self._members = members
        self._audit_log = audit_log

    def execute(
        self,
        salon_id: uuid.UUID,
        employee_id: uuid.UUID,
        actor_id: uuid.UUID,
        command: UpdateEmployeeProfileCommand,
    ) -> Employee:
        current = self._members.find_by_id(salon_id, employee_id)
        if current is None:
            # Coiffeuse inexistante **ou** hors salon : indiscernables (§11.2).
            raise EmployeeNotFound("Coiffeuse introuvable.")

        name = validate_name(command.full_name)
        phone = normalize_phone(command.phone)
        email = command.email or None
        specialties = normalize_specialties(command.specialties)

        # Identité (`users`) : unicité **globale** — peut lever
        # `PhoneAlreadyInUse`/`EmailAlreadyInUse` si un **autre** compte porte
        # déjà ce téléphone/e-mail.
        self._users.update_identity(
            employee_id, full_name=name, phone=phone, email=email
        )
        # Champs pro (`salon_members`) : `find_by_id` a déjà confirmé
        # l'appartenance — `update_professional_fields` ne peut plus renvoyer
        # `None` dans le flux normal (même Session, aucune écriture entre
        # temps qui retirerait la ligne).
        updated = self._members.update_professional_fields(
            salon_id, employee_id, specialties=specialties, hired_at=command.hired_at
        )
        assert updated is not None  # garanti par `find_by_id` ci-dessus

        target = Employee(
            id=updated.id,
            full_name=name,
            phone=phone,
            email=email,
            role=updated.role,
            status=updated.status,
            specialties=specialties,
            hired_at=command.hired_at,
            created_at=updated.created_at,
        )
        changed = _changed_employee_fields(current, target)
        self._audit_log.record(
            AuditEntry(
                action=AuditAction.EMPLOYEE_UPDATED.value,
                actor_user_id=actor_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_SALON_MEMBER,
                entity_id=employee_id,
                metadata={"changed": changed},
            )
        )
        return target


class ListSalonEmployees:
    """Liste les coiffeuses **du salon** (lecture planning gérant, #150).

    Lecture pure (aucune écriture, aucun audit — cohérent avec
    `ListSalonAppointments` #26) : la portée salon est assurée par la garde
    HTTP `require_salon_scope`, ré-affirmée en SQL par le dépôt.
    """

    def __init__(self, members: SalonMemberRepository) -> None:
        self._members = members

    def execute(self, salon_id: uuid.UUID) -> tuple[Employee, ...]:
        return self._members.list_for_salon(salon_id)


class GetSalonEmployee:
    """Charge une coiffeuse **du salon** ; lève `EmployeeNotFound` sinon (#150)."""

    def __init__(self, members: SalonMemberRepository) -> None:
        self._members = members

    def execute(self, salon_id: uuid.UUID, employee_id: uuid.UUID) -> Employee:
        employee = self._members.find_by_id(salon_id, employee_id)
        if employee is None:
            raise EmployeeNotFound("Coiffeuse introuvable.")
        return employee


class _SetEmployeeAvailability:
    """Base commune activer/désactiver — pilote `salon_members.status` (#150).

    Factorise la séquence portée→écriture→audit ; les sous-classes ne fixent
    que le statut cible et l'action d'audit.
    """

    _target_status: str
    _audit_action: str

    def __init__(self, members: SalonMemberRepository, audit_log: AuditLog) -> None:
        self._members = members
        self._audit_log = audit_log

    def execute(
        self, salon_id: uuid.UUID, employee_id: uuid.UUID, actor_id: uuid.UUID
    ) -> Employee:
        updated = self._members.set_status(salon_id, employee_id, self._target_status)
        if updated is None:
            # Coiffeuse inexistante **ou** hors salon : indiscernables (§11.2).
            raise EmployeeNotFound("Coiffeuse introuvable.")
        self._audit_log.record(
            AuditEntry(
                action=self._audit_action,
                actor_user_id=actor_id,
                salon_id=salon_id,
                entity_type=ENTITY_TYPE_SALON_MEMBER,
                entity_id=employee_id,
                metadata={},
            )
        )
        return updated


class DeactivateEmployee(_SetEmployeeAvailability):
    """Désactive une coiffeuse (`salon_members.status = INACTIVE`, #150).

    Retire la coiffeuse de l'éligibilité aux **nouvelles** affectations de ce
    salon (`_require_salon_hairdresser`) — ne bloque **pas** sa connexion
    (`users.status` inchangé) ni ses RDV déjà assignés.
    """

    _target_status = UserStatus.INACTIVE.value
    _audit_action = AuditAction.EMPLOYEE_DEACTIVATED.value


class ReactivateEmployee(_SetEmployeeAvailability):
    """Réactive une coiffeuse (`salon_members.status = ACTIVE`, #150)."""

    _target_status = UserStatus.ACTIVE.value
    _audit_action = AuditAction.EMPLOYEE_REACTIVATED.value


__all__ = [
    "CreateEmployee",
    "CreateEmployeeCommand",
    "UpdateEmployeeProfile",
    "UpdateEmployeeProfileCommand",
    "ListSalonEmployees",
    "GetSalonEmployee",
    "DeactivateEmployee",
    "ReactivateEmployee",
]
