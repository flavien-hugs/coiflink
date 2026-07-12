"""Cas d'usage : **création d'un compte employé (coiffeur)** par un gérant (US-1.4, #13).

Orchestre la création d'un compte `HAIRDRESSER` **rattaché à un salon** : le
gérant fournit le nom, le téléphone et un mot de passe initial ; le compte est
créé puis inscrit comme **membre** du salon (`salon_members`), ce qui devient la
source d'autorité de sa **portée** (PRD §11.2, ADR-0016).

Comme `RegisterUser` (#8/#9), ce cas d'usage ne dépend que de **ports** (aucune
dépendance FastAPI/SQLAlchemy) et le **rôle cible est fixé au câblage**, jamais
lu depuis la commande ni la requête HTTP : un gérant ne peut créer ni `MANAGER`,
ni `ADMIN`, ni `CLIENT` (garde-fou anti-élévation de privilège, PRD §11.1).

Séquence : valider le nom + le mot de passe → **normaliser le téléphone** →
**pré-vérifier le doublon** → **hacher** → **créer** l'utilisateur (`role`
injecté, `status=ACTIVE`) → **rattacher** au salon (`add_member`) → retourner
l'entité **sans** secret.

Atomicité : les deux écritures (utilisateur + appartenance) passent par la
**même `Session`** et sont committées ensemble par `get_session`. Si
`add_member` lève, la requête est rollbackée → **pas de compte orphelin** sans
salon. Le mot de passe en clair n'est ni journalisé ni conservé au-delà du
hachage.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.application.ports.salon_member_repository import SalonMemberRepository
from coiflink_api.application.ports.user_repository import UserRepository
from coiflink_api.domain.enums import Role, UserStatus, values
from coiflink_api.domain.errors import PhoneAlreadyInUse
from coiflink_api.domain.membership import SalonMembershipToCreate
from coiflink_api.domain.password import validate_password
from coiflink_api.domain.phone import normalize_phone
from coiflink_api.domain.user import User, UserToCreate, validate_name

# Rôles autorisés pour un employé, dérivés du domaine (source de vérité `Role`).
# Garde-fou au câblage : un rôle inconnu échoue à la construction du cas d'usage.
_ROLE_VALUES: frozenset[str] = frozenset(values(Role))


@dataclass(frozen=True)
class CreateEmployeeCommand:
    """Données d'entrée du cas d'usage (mot de passe en clair, éphémère).

    `salon_id` est la **cible** validée en amont par la garde de portée
    (`require_salon_scope`) : le gérant ne peut créer un employé que sur **son**
    salon. Aucun champ `role` : il est fixé côté serveur.
    """

    salon_id: uuid.UUID
    full_name: str
    phone: str
    password: str
    email: str | None = None


class CreateEmployee:
    """Crée un compte employé et le rattache à un salon (rôle fixé au câblage)."""

    def __init__(
        self,
        repository: UserRepository,
        hasher: PasswordHasher,
        members: SalonMemberRepository,
        *,
        role: str = Role.HAIRDRESSER.value,
    ) -> None:
        if role not in _ROLE_VALUES:
            raise ValueError(f"Rôle d'employé inconnu : {role!r}")
        self._role = role
        self._repository = repository
        self._hasher = hasher
        self._members = members

    def execute(self, command: CreateEmployeeCommand) -> User:
        """Crée l'employé (rôle injecté) et l'ajoute au salon ; retourne l'entité."""

        name = validate_name(command.full_name)
        validate_password(command.password)
        phone = normalize_phone(command.phone)
        email = command.email or None

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

        return user


__all__ = ["CreateEmployee", "CreateEmployeeCommand"]
