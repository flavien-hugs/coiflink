"""Faux adaptateurs partagés entre les suites de tests (inscription #8, connexion #10, #13).

Chaque fake implémente le protocole du port correspondant sans I/O réelle.
Aucune valeur secrète réelle ni PII n'est utilisée dans ces fixtures.
"""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import uuid
from typing import Union

import pytest

from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import NotificationChannel
from coiflink_api.domain.errors import EmployeeAlreadyInSalon, PhoneAlreadyInUse, TooManyLoginAttempts
from coiflink_api.domain.membership import SalonMembershipToCreate
from coiflink_api.domain.salon import Salon as SalonEntity
from coiflink_api.domain.salon import SalonPhoto as SalonPhotoEntity
from coiflink_api.domain.otp import OtpChallenge
from coiflink_api.domain.tokens import TokenClaims, TokenPair
from coiflink_api.domain.user import User, UserToCreate

_CREATED_AT = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
# Horodatage postérieur à `_CREATED_AT` : les fakes de mutation le posent sur
# `updated_at` pour qu'un test puisse vérifier sa régénération (miroir `onupdate`).
_UPDATED_AT = datetime.datetime(2026, 1, 2, 0, 0, 0, tzinfo=datetime.timezone.utc)
_FIXED_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Paire de jetons synthétiques réutilisable dans les tests de connexion.
FAKE_TOKEN_PAIR = TokenPair(
    access_token="fake-access-token",
    refresh_token="fake-refresh-token",
    expires_in=900,
)

# Claims de refresh synthétiques (sub correspond à _FIXED_UUID).
FAKE_REFRESH_CLAIMS = TokenClaims(
    sub=str(_FIXED_UUID),
    role="CLIENT",
    type="refresh",
    jti="fake-jti-0001",
    iat=1735725600,
    exp=1735725600 + 2592000,
)

# Claims d'**accès** synthétiques (autorisation #12) — même `sub`, `type=access`.
FAKE_ACCESS_CLAIMS = TokenClaims(
    sub=str(_FIXED_UUID),
    role="CLIENT",
    type="access",
    jti="fake-jti-0002",
    iat=1735725600,
    exp=1735725600 + 900,
)

# Secret **factice** réservé aux tests : jamais un secret réel, jamais en production.
TEST_JWT_SECRET = "test-only-jwt-secret-not-for-production-use"


def make_access_token(
    user_id: Union[uuid.UUID, str],
    role: str,
    *,
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Fabrique un **vrai** JWT d'accès signé avec le secret de test (#12).

    Utile aux tests de gardes : ils exercent le décodage réel (`JwtTokenService`)
    sans dépendre d'une connexion ni d'une base.
    """

    return JwtTokenService(secret).issue_pair(user_id, role).access_token


def make_refresh_token(
    user_id: Union[uuid.UUID, str],
    role: str,
    *,
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Fabrique un vrai **refresh** token — refusé sur une route protégée (#12)."""

    return JwtTokenService(secret).issue_pair(user_id, role).refresh_token


class FakeHasher:
    """Hacheur déterministe (préfixe « hash: »). Ne produit jamais le clair tel quel."""

    def hash(self, plain: str) -> str:
        return f"hash:{plain}"

    def verify(self, plain: str, hashed: str) -> bool:
        return hashed == f"hash:{plain}"


class FakeUserRepository:
    """Dépôt en mémoire pour les tests unitaires et API."""

    def __init__(self, existing_phones: set[str] | None = None) -> None:
        self._phones: set[str] = set(existing_phones or [])
        self.created: list[UserToCreate] = []
        # Historique des appels à update_password (#11) : (user_id str, hash).
        self.updated_passwords: list[tuple[str, str]] = []

    def phone_exists(self, phone: str) -> bool:
        return phone in self._phones

    def create(self, user: UserToCreate) -> User:
        self.created.append(user)
        self._phones.add(user.phone)
        return User(
            id=_FIXED_UUID,
            full_name=user.full_name,
            phone=user.phone,
            email=user.email,
            role=user.role,
            status=user.status,
            created_at=_CREATED_AT,
        )

    def update_password(
        self, user_id: Union[uuid.UUID, str], new_password_hash: str
    ) -> None:
        """Enregistre le remplacement du condensat (réinitialisation, #11)."""

        self.updated_passwords.append((str(user_id), new_password_hash))


class FakeUserRepositoryRaisingDuplicate:
    """Dépôt dont `create` lève PhoneAlreadyInUse (simulation d'IntegrityError concurrente)."""

    def phone_exists(self, phone: str) -> bool:  # noqa: ARG002
        return False

    def create(self, user: UserToCreate) -> User:  # noqa: ARG002
        raise PhoneAlreadyInUse("Contrainte base violée (race condition simulée).")


class FakeAuthUserRepository(FakeUserRepository):
    """FakeUserRepository étendu avec les méthodes d'authentification (connexion #10).

    Prend en paramètre des tables optionnelles `credentials_by_phone`,
    `credentials_by_email`, `credentials_by_id` (clé = str) pour contrôler
    finement les résultats de recherche dans les tests.
    """

    def __init__(
        self,
        existing_phones: set[str] | None = None,
        credentials_by_phone: dict[str, UserCredentials] | None = None,
        credentials_by_email: dict[str, UserCredentials] | None = None,
        credentials_by_id: dict[str, UserCredentials] | None = None,
    ) -> None:
        super().__init__(existing_phones=existing_phones)
        self._by_phone: dict[str, UserCredentials] = credentials_by_phone or {}
        self._by_email: dict[str, UserCredentials] = credentials_by_email or {}
        self._by_id: dict[str, UserCredentials] = credentials_by_id or {}

    def find_by_phone(self, phone: str) -> UserCredentials | None:
        return self._by_phone.get(phone)

    def find_by_email(self, email: str) -> UserCredentials | None:
        return self._by_email.get(email)

    def find_by_id(self, user_id: Union[uuid.UUID, str]) -> UserCredentials | None:
        return self._by_id.get(str(user_id))

    def find_user_by_id(self, user_id: Union[uuid.UUID, str]) -> User | None:
        """Entité **publique** (sans condensat) du compte — `GET /auth/me` (#12).

        Dérivée des `UserCredentials` connus : le `password_hash` n'est jamais
        recopié dans l'entité retournée. `None` si l'id est inconnu.
        """

        cred = self._by_id.get(str(user_id))
        if cred is None:
            return None
        return User(
            id=cred.id,
            full_name="Utilisateur Test",
            phone="+2250700000000",
            email=None,
            role=cred.role,
            status=cred.status,
            created_at=_CREATED_AT,
        )

    def update_password(
        self, user_id: Union[uuid.UUID, str], new_password_hash: str
    ) -> None:
        """Enregistre l'appel **et** met à jour le condensat des credentials stockés.

        Remplace `password_hash` dans les tables de recherche pour le compte
        correspondant (frozen dataclass ⇒ `dataclasses.replace`) : un `find_by_*`
        ultérieur reflète le nouveau condensat (l'ancien ne s'authentifie plus).
        """

        super().update_password(user_id, new_password_hash)
        uid = str(user_id)
        for table in (self._by_phone, self._by_email, self._by_id):
            for lookup_key, cred in list(table.items()):
                if str(cred.id) == uid:
                    table[lookup_key] = dataclasses.replace(
                        cred, password_hash=new_password_hash
                    )


class FakeTokenService:
    """Service de jetons factice à résultat configurable (tests connexion #10).

    `verify_refresh_result` peut être une `TokenClaims` (succès) ou une exception
    à lever. Utilise `FAKE_REFRESH_CLAIMS` par défaut.
    """

    def __init__(
        self,
        *,
        pair: TokenPair | None = None,
        verify_refresh_result: Union[TokenClaims, Exception, None] = None,
        verify_access_result: Union[TokenClaims, Exception, None] = None,
    ) -> None:
        self._pair = pair or FAKE_TOKEN_PAIR
        self._verify_refresh_result: Union[TokenClaims, Exception] = (
            verify_refresh_result if verify_refresh_result is not None else FAKE_REFRESH_CLAIMS
        )
        self._verify_access_result: Union[TokenClaims, Exception] = (
            verify_access_result if verify_access_result is not None else FAKE_ACCESS_CLAIMS
        )
        self.issued: list[tuple[Union[uuid.UUID, str], str]] = []

    def issue_pair(self, user_id: Union[uuid.UUID, str], role: str) -> TokenPair:
        self.issued.append((user_id, role))
        return self._pair

    def decode(self, token: str) -> TokenClaims:  # noqa: ARG002
        raise NotImplementedError("FakeTokenService.decode non implémenté")

    def verify_refresh(self, token: str) -> TokenClaims:  # noqa: ARG002
        if isinstance(self._verify_refresh_result, Exception):
            raise self._verify_refresh_result
        return self._verify_refresh_result

    def verify_access(self, token: str) -> TokenClaims:  # noqa: ARG002
        """Vérifie un jeton d'**accès** (autorisation #12) ; refuse tout autre type.

        `verify_access_result` (constructeur) permet de simuler un succès
        (`TokenClaims`) ou un refus (exception à lever, p. ex. `InvalidToken` pour
        un refresh présenté comme jeton d'accès).
        """

        if isinstance(self._verify_access_result, Exception):
            raise self._verify_access_result
        return self._verify_access_result


class FakeLoginRateLimiter:
    """Limiteur anti-bruteforce factice à comportement configurable (tests #10).

    Enregistre les appels à `check`, `record_failure` et `reset` pour assertions.
    Peut être configuré pour lever `TooManyLoginAttempts` à `check`.
    """

    def __init__(
        self,
        *,
        locked: bool = False,
        retry_after: int | None = None,
    ) -> None:
        self._locked = locked
        self._retry_after = retry_after
        self.checks: list[str] = []
        self.failures: list[str] = []
        self.resets: list[str] = []

    def check(self, key: str) -> None:
        self.checks.append(key)
        if self._locked:
            raise TooManyLoginAttempts(
                "Trop de tentatives.", retry_after=self._retry_after
            )

    def record_failure(self, key: str) -> None:
        self.failures.append(key)

    def reset(self, key: str) -> None:
        self.resets.append(key)


class FakeSalonScopeRepository:
    """Portée salon en mémoire (isolation §11.2, #12).

    `scopes` associe un `principal_id` à ses salons. `calls` enregistre les appels
    pour vérifier qu'un `ADMIN` **ne sollicite pas** le port (portée plateforme
    court-circuitée par `AccessPolicy`).
    """

    def __init__(
        self, scopes: dict[uuid.UUID, frozenset[uuid.UUID]] | None = None
    ) -> None:
        self.scopes: dict[uuid.UUID, frozenset[uuid.UUID]] = scopes or {}
        self.calls: list[tuple[uuid.UUID, str]] = []

    def salon_ids_for(self, principal_id: uuid.UUID, role: str) -> frozenset[uuid.UUID]:
        self.calls.append((principal_id, role))
        return self.scopes.get(principal_id, frozenset())


class FakeOtpSender:
    """Expéditeur OTP en mémoire (multi-canal) ; ne journalise rien.

    `sent` conserve des couples `(recipient, code)` (compat #8) ; `sent_channels`
    enregistre en plus le canal — `(recipient, code, channel)` — pour vérifier le
    routage SMS/e-mail de la réinitialisation (#11).
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.sent_channels: list[tuple[str, str, str]] = []

    def send(
        self,
        recipient: str,
        code: str,
        channel: str = NotificationChannel.SMS.value,
    ) -> None:
        self.sent.append((recipient, code))
        self.sent_channels.append((recipient, code, channel))


class FakeOtpRepository:
    """Dépôt OTP en mémoire (clé de destinataire : téléphone E.164 ou e-mail)."""

    def __init__(self) -> None:
        self.challenges: dict[str, OtpChallenge] = {}

    def save(self, key: str, challenge: OtpChallenge) -> None:
        self.challenges[key] = challenge

    def get(self, key: str) -> OtpChallenge | None:
        return self.challenges.get(key)

    def delete(self, key: str) -> None:
        self.challenges.pop(key, None)


# ── Fixtures pytest partagées ──────────────────────────────────────────────


@pytest.fixture()
def fake_hasher() -> FakeHasher:
    return FakeHasher()


@pytest.fixture()
def fake_user_repository() -> FakeUserRepository:
    return FakeUserRepository()


@pytest.fixture()
def fake_otp_sender() -> FakeOtpSender:
    return FakeOtpSender()


@pytest.fixture()
def fake_otp_repository() -> FakeOtpRepository:
    return FakeOtpRepository()


@pytest.fixture()
def fake_auth_user_repository() -> FakeAuthUserRepository:
    return FakeAuthUserRepository()


@pytest.fixture()
def fake_token_service() -> FakeTokenService:
    return FakeTokenService()


@pytest.fixture()
def fake_rate_limiter() -> FakeLoginRateLimiter:
    return FakeLoginRateLimiter()


@pytest.fixture()
def fake_salon_scope_repository() -> FakeSalonScopeRepository:
    return FakeSalonScopeRepository()


class FakeSalonMemberRepository:
    """Dépôt d'appartenances employé↔salon en mémoire (#13).

    `raise_duplicate=True` simule une violation d'unicité `(salon_id, user_id)`.
    `added` enregistre chaque appel pour vérifier les données transmises.
    """

    def __init__(self, *, raise_duplicate: bool = False) -> None:
        self._raise_duplicate = raise_duplicate
        self.added: list[SalonMembershipToCreate] = []

    def add_member(self, membership: SalonMembershipToCreate) -> None:
        if self._raise_duplicate:
            raise EmployeeAlreadyInSalon("Cet employé est déjà rattaché à ce salon.")
        self.added.append(membership)


@pytest.fixture()
def fake_salon_member_repository() -> FakeSalonMemberRepository:
    return FakeSalonMemberRepository()


class FakeSalonRepository:
    """Dépôt de salons en mémoire (création + lecture + médias, #15).

    Implémente le port `SalonRepository` sans I/O réelle. `created` conserve les
    intentions d'écriture pour vérifier que l'`owner_id` provient bien du
    principal. Les photos sont stockées par salon (ordre d'insertion = position).
    """

    def __init__(self) -> None:
        self.created: list = []
        self._salons: dict[uuid.UUID, "SalonEntity"] = {}
        self._photos: dict[uuid.UUID, list["SalonPhotoEntity"]] = {}

    def create(self, salon):  # type: ignore[no-untyped-def]
        from coiflink_api.domain.enums import SalonStatus
        from coiflink_api.domain.salon import Salon as SalonEntity

        self.created.append(salon)
        entity = SalonEntity(
            id=uuid.uuid4(),
            owner_id=salon.owner_id,
            name=salon.name,
            description=salon.description,
            phone=salon.phone,
            address=salon.address,
            city=salon.city,
            commune=salon.commune,
            latitude=salon.latitude,
            longitude=salon.longitude,
            logo_object_key=None,
            status=SalonStatus.ACTIVE.value,
            opening_hours=None,
            created_at=_CREATED_AT,
            updated_at=_CREATED_AT,
        )
        self._salons[entity.id] = entity
        self._photos.setdefault(entity.id, [])
        return entity

    def find_by_id(self, salon_id: uuid.UUID):  # type: ignore[no-untyped-def]
        return self._salons.get(salon_id)

    def list_for_owner(self, owner_id: uuid.UUID):  # type: ignore[no-untyped-def]
        return tuple(
            s for s in self._salons.values() if s.owner_id == owner_id
        )

    def update(self, salon_id: uuid.UUID, changes):  # type: ignore[no-untyped-def]
        import dataclasses as _dc

        from coiflink_api.domain.errors import SalonNotFound

        salon = self._salons.get(salon_id)
        if salon is None:
            raise SalonNotFound("Salon introuvable.")
        salon = _dc.replace(
            salon,
            name=changes.name,
            description=changes.description,
            phone=changes.phone,
            address=changes.address,
            city=changes.city,
            commune=changes.commune,
            latitude=changes.latitude,
            longitude=changes.longitude,
        )
        self._salons[salon_id] = salon
        return salon

    def set_logo(self, salon_id: uuid.UUID, object_key):  # type: ignore[no-untyped-def]
        import dataclasses as _dc

        from coiflink_api.domain.errors import SalonNotFound

        salon = self._salons.get(salon_id)
        if salon is None:
            raise SalonNotFound("Salon introuvable.")
        salon = _dc.replace(salon, logo_object_key=object_key)
        self._salons[salon_id] = salon
        return salon

    def set_opening_hours(self, salon_id: uuid.UUID, opening_hours):  # type: ignore[no-untyped-def]
        import dataclasses as _dc

        from coiflink_api.domain.errors import SalonNotFound

        salon = self._salons.get(salon_id)
        if salon is None:
            raise SalonNotFound("Salon introuvable.")
        salon = _dc.replace(salon, opening_hours=opening_hours)
        self._salons[salon_id] = salon
        return salon

    def add_photo(self, salon_id: uuid.UUID, object_key: str):  # type: ignore[no-untyped-def]
        from coiflink_api.domain.salon import SalonPhoto as SalonPhotoEntity

        photos = self._photos.setdefault(salon_id, [])
        photo = SalonPhotoEntity(
            id=uuid.uuid4(),
            salon_id=salon_id,
            object_key=object_key,
            position=len(photos),
            created_at=_CREATED_AT,
        )
        photos.append(photo)
        return photo

    def list_photos(self, salon_id: uuid.UUID):  # type: ignore[no-untyped-def]
        return tuple(self._photos.get(salon_id, []))

    def count_photos(self, salon_id: uuid.UUID) -> int:
        return len(self._photos.get(salon_id, []))

    def delete_photo(self, salon_id: uuid.UUID, photo_id: uuid.UUID):  # type: ignore[no-untyped-def]
        photos = self._photos.get(salon_id, [])
        for index, photo in enumerate(photos):
            if photo.id == photo_id:
                del photos[index]
                return photo.object_key
        return None


class FakeMediaStorage:
    """Stockage objet en mémoire (URLs signées factices) — aucun appel réseau (#15).

    `presign_*` renvoient des URLs déterministes et **non secrètes** ; `deleted`
    et `uploads` enregistrent les appels pour assertions.
    """

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.uploads: list[tuple[str, str]] = []

    def presign_upload(self, object_key: str, content_type: str):  # type: ignore[no-untyped-def]
        from coiflink_api.application.ports.media_storage import PresignedUpload

        self.uploads.append((object_key, content_type))
        return PresignedUpload(
            url=f"https://fake-bucket.local/upload/{object_key}",
            object_key=object_key,
            method="PUT",
            headers={"Content-Type": content_type},
            expires_in=900,
        )

    def presign_download(self, object_key: str) -> str:
        return f"https://fake-bucket.local/download/{object_key}?sig=fake"

    def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


@pytest.fixture()
def fake_salon_repository() -> "FakeSalonRepository":
    return FakeSalonRepository()


@pytest.fixture()
def fake_media_storage() -> "FakeMediaStorage":
    return FakeMediaStorage()


class FakeServiceRepository:
    """Dépôt de prestations en mémoire (US-2.3, #17).

    Implémente le port `ServiceRepository` sans I/O réelle. Isolation §11.2 :
    `find_by_id` et les mutations filtrent sur `(salon_id, service_id)` —
    une prestation d'un autre salon est indiscernable d'une prestation inexistante.
    """

    def __init__(self) -> None:
        self._services: dict[uuid.UUID, object] = {}
        self.created: list = []

    def create(self, service):  # type: ignore[no-untyped-def]
        from coiflink_api.domain.service import Service

        entity = Service(
            id=uuid.uuid4(),
            salon_id=service.salon_id,
            name=service.name,
            description=service.description,
            price=service.price,
            duration_minutes=service.duration_minutes,
            category=service.category,
            is_active=True,
            created_at=_CREATED_AT,
            updated_at=_CREATED_AT,
        )
        self._services[entity.id] = entity
        self.created.append(service)
        return entity

    def find_by_id(self, salon_id: uuid.UUID, service_id: uuid.UUID):  # type: ignore[no-untyped-def]
        service = self._services.get(service_id)
        if service is None or service.salon_id != salon_id:  # type: ignore[union-attr]
            return None
        return service

    def list_for_salon(self, salon_id: uuid.UUID, *, filter, include_inactive: bool = True):  # type: ignore[no-untyped-def]
        return tuple(
            s
            for s in self._services.values()
            if s.salon_id == salon_id  # type: ignore[union-attr]
            and (include_inactive or s.is_active)  # type: ignore[union-attr]
            and self._matches(s, filter)
        )

    @staticmethod
    def _matches(s, filter) -> bool:  # type: ignore[no-untyped-def]
        """Filtrage en mémoire **miroir** des clauses SQL (nom/catégorie/dates, ET)."""

        if filter.created_at_from is not None and s.created_at < filter.created_at_from:  # type: ignore[union-attr]
            return False
        if filter.created_at_to is not None and s.created_at > filter.created_at_to:  # type: ignore[union-attr]
            return False
        if filter.category is not None and s.category != filter.category:  # type: ignore[union-attr]
            return False
        if filter.q is not None and filter.q.lower() not in s.name.lower():  # type: ignore[union-attr]
            return False
        return True

    def update(self, salon_id: uuid.UUID, service_id: uuid.UUID, changes):  # type: ignore[no-untyped-def]
        import dataclasses as _dc

        from coiflink_api.domain.errors import ServiceNotFound

        service = self.find_by_id(salon_id, service_id)
        if service is None:
            raise ServiceNotFound("Prestation introuvable.")
        updated = _dc.replace(
            service,
            name=changes.name,
            price=changes.price,
            duration_minutes=changes.duration_minutes,
            description=changes.description,
            category=changes.category,
            updated_at=_CREATED_AT,
        )
        self._services[service_id] = updated
        return updated

    def set_active(self, salon_id: uuid.UUID, service_id: uuid.UUID, active: bool):  # type: ignore[no-untyped-def]
        import dataclasses as _dc

        from coiflink_api.domain.errors import ServiceNotFound

        service = self.find_by_id(salon_id, service_id)
        if service is None:
            raise ServiceNotFound("Prestation introuvable.")
        updated = _dc.replace(service, is_active=active, updated_at=_CREATED_AT)
        self._services[service_id] = updated
        return updated


class FakeSalonCatalogRepository:
    """Dépôt de catalogue public en mémoire (lecture `ACTIVE`-only, §8.3, #18/#19).

    Filtre en mémoire : sert à isoler la couche applicative de la base de données
    dans les tests unitaires et d'API. Le filtre `status == ACTIVE` est appliqué
    en premier (invariant du port). La recherche par nom est une sous-chaîne
    insensible à la casse (même sémantique que l'ILIKE SQL).

    Fiche client (#19) : `services` associe un `salon_id` à ses prestations
    (actives **et** inactives) et `photos` à ses photos. `list_active_services`
    ne renvoie que les prestations `is_active=True` (filtre côté lecture, jamais en
    post-filtrage applicatif), triées par nom — miroir de l'ILIKE/`ORDER BY` SQL.
    """

    def __init__(
        self,
        salons: list | None = None,
        services: dict | None = None,
        photos: dict | None = None,
    ) -> None:
        self._salons: list = list(salons or [])
        self._services: dict = dict(services or {})
        self._photos: dict = dict(photos or {})

    def _active_matching(self, query) -> list:  # type: ignore[no-untyped-def]
        active = [s for s in self._salons if s.status == "ACTIVE"]
        if query.text:
            t = query.text.lower()
            active = [s for s in active if t in s.name.lower()]
        if query.city:
            c = query.city.lower()
            active = [s for s in active if s.city and s.city.lower() == c]
        if query.commune:
            co = query.commune.lower()
            active = [s for s in active if s.commune and s.commune.lower() == co]
        return active

    def search_active(self, query) -> tuple:  # type: ignore[no-untyped-def]
        matching = sorted(self._active_matching(query), key=lambda s: s.name)
        return tuple(matching[query.offset : query.offset + query.limit])

    def count_active(self, query) -> int:  # type: ignore[no-untyped-def]
        return len(self._active_matching(query))

    def get_active(self, salon_id):  # type: ignore[no-untyped-def]
        for s in self._salons:
            if s.id == salon_id and s.status == "ACTIVE":
                return s
        return None

    def list_active_services(self, salon_id):  # type: ignore[no-untyped-def]
        services = [
            s for s in self._services.get(salon_id, []) if s.is_active
        ]
        return tuple(sorted(services, key=lambda s: s.name))

    def list_photos(self, salon_id):  # type: ignore[no-untyped-def]
        return tuple(self._photos.get(salon_id, []))


class FakeAuditLog:
    """Journal d'audit en mémoire (§11.4, US-2.3, #17).

    Accumule les `AuditEntry` pour vérification dans les tests.
    """

    def __init__(self) -> None:
        self.recorded: list = []

    def record(self, entry) -> None:  # type: ignore[no-untyped-def]
        self.recorded.append(entry)


class FakeAppointmentRepository:
    """Dépôt de rendez-vous en mémoire (US-3.7, #21 / US-3.2, #23).

    Implémente le port `AppointmentRepository` sans I/O réelle. `booked` associe une
    clé `(salon_id, hairdresser_id, date)` à des `SlotRange` déjà réservés (alimente
    le moteur de disponibilité). `raise_conflict=True` simule la **course
    concurrente** : `create`/`update` lèvent `SlotAlreadyBooked`. `raise_not_modifiable=True`
    simule la garde TOCTOU : `update` lève `AppointmentNotModifiable`. `appointments`
    pré-charge des `Appointment` (entités de lecture) pour `get_owned`/`update`/`list_for_client`.
    `booked_slots_calls` enregistre chaque appel pour vérifier l'`exclude_appointment_id` (#23).
    """

    def __init__(
        self,
        booked: dict | None = None,
        *,
        raise_conflict: bool = False,
        raise_not_modifiable: bool = False,
        raise_not_cancellable: bool = False,
        raise_invalid_transition: bool = False,
        appointments: list | None = None,
    ) -> None:
        self._booked: dict = dict(booked or {})
        self._raise_conflict = raise_conflict
        self._raise_not_modifiable = raise_not_modifiable
        self._raise_not_cancellable = raise_not_cancellable
        self._raise_invalid_transition = raise_invalid_transition
        self.created: list = []
        self.updated: list = []
        self.cancelled: list = []
        # #25 — mémorise les transitions `(appointment_id, from, to, reason)` et les
        # (dés)assignations `(appointment_id, hairdresser_id)` pour assertions.
        self.status_changes: list = []
        self.assignments: list = []
        self.booked_slots_calls: list = []
        # Résultats configurables pour `demand_by_service` (US-6.3 #41).
        self.demand_results: tuple = ()
        self.demand_by_service_calls: list[dict] = []
        # Résultats configurables pour `segment_active_clients` (US-6.4 #42).
        self.segment_results: tuple = ()
        self.segment_active_clients_calls: list[dict] = []
        self._appointments: dict = {}
        for appt in (appointments or []):
            self._appointments[appt.id] = appt

    def booked_slots(  # type: ignore[no-untyped-def]
        self,
        salon_id,
        hairdresser_id,
        date,
        *,
        exclude_appointment_id=None,
    ):
        self.booked_slots_calls.append({
            "salon_id": salon_id,
            "hairdresser_id": hairdresser_id,
            "date": date,
            "exclude_appointment_id": exclude_appointment_id,
        })
        return tuple(self._booked.get((salon_id, hairdresser_id, date), ()))

    def create(self, appointment):  # type: ignore[no-untyped-def]
        from coiflink_api.domain.appointment import Appointment
        from coiflink_api.domain.errors import SlotAlreadyBooked

        if self._raise_conflict:
            raise SlotAlreadyBooked(
                "Ce créneau vient d'être réservé pour ce coiffeur."
            )
        self.created.append(appointment)
        entity = Appointment(
            id=uuid.uuid4(),
            salon_id=appointment.salon_id,
            client_id=appointment.client_id,
            hairdresser_id=appointment.hairdresser_id,
            date=appointment.date,
            start_time=appointment.start_time,
            end_time=appointment.end_time,
            status=appointment.status,
            client_note=appointment.client_note,
            created_at=_CREATED_AT,
            services=appointment.services,
        )
        self._appointments[entity.id] = entity
        return entity

    def get_owned(self, appointment_id, client_id):  # type: ignore[no-untyped-def]
        """Retourne le RDV si et seulement si `client_id` correspond (§11.2)."""
        appt = self._appointments.get(appointment_id)
        if appt is None or appt.client_id != client_id:
            return None
        return appt

    def update(self, appointment_id, changes):  # type: ignore[no-untyped-def]
        import dataclasses as _dc
        from coiflink_api.domain.errors import AppointmentNotModifiable, SlotAlreadyBooked

        if self._raise_not_modifiable:
            raise AppointmentNotModifiable("Ce rendez-vous n'est plus modifiable.")
        if self._raise_conflict:
            raise SlotAlreadyBooked(
                "Ce créneau vient d'être réservé pour ce coiffeur."
            )
        appt = self._appointments.get(appointment_id)
        if appt is None:
            raise AppointmentNotModifiable("Ce rendez-vous n'est plus modifiable.")
        self.updated.append((appointment_id, changes))
        updated = _dc.replace(
            appt,
            date=changes.date,
            start_time=changes.start_time,
            end_time=changes.end_time,
            hairdresser_id=changes.hairdresser_id,
            client_note=changes.client_note,
            services=changes.services,
        )
        self._appointments[appointment_id] = updated
        return updated

    def cancel(self, appointment_id, *, reason):  # type: ignore[no-untyped-def]
        """Annule le RDV (transition `CANCELLED`) et mémorise le motif transmis (#24).

        `raise_not_cancellable=True` simule la garde TOCTOU (statut passé terminal
        entre la lecture et l'écriture) : lève `AppointmentNotCancellable`. Un RDV
        déjà terminal (hors `PENDING`/`CONFIRMED`) ou absent est refusé de la même
        façon (miroir de l'UPDATE conditionnel base). `cancelled` enregistre chaque
        `(appointment_id, reason)` reçu pour vérifier que le motif normalisé transite.
        """
        import dataclasses as _dc
        from coiflink_api.domain.appointment import CLIENT_CANCELLABLE_STATUSES
        from coiflink_api.domain.enums import AppointmentStatus
        from coiflink_api.domain.errors import AppointmentNotCancellable

        if self._raise_not_cancellable:
            raise AppointmentNotCancellable(
                "Ce rendez-vous ne peut plus être annulé."
            )
        appt = self._appointments.get(appointment_id)
        if appt is None or appt.status not in CLIENT_CANCELLABLE_STATUSES:
            raise AppointmentNotCancellable(
                "Ce rendez-vous ne peut plus être annulé."
            )
        self.cancelled.append((appointment_id, reason))
        updated = _dc.replace(
            appt,
            status=AppointmentStatus.CANCELLED.value,
        )
        self._appointments[appointment_id] = updated
        return updated

    def get_in_salon(self, appointment_id, salon_id):  # type: ignore[no-untyped-def]
        """Retourne le RDV si et seulement si `salon_id` correspond (§11.2, #25)."""
        appt = self._appointments.get(appointment_id)
        if appt is None or appt.salon_id != salon_id:
            return None
        return appt

    def set_status(  # type: ignore[no-untyped-def]
        self,
        appointment_id,
        salon_id,
        *,
        expected_current,
        target,
        reason=None,
    ):
        """Transition de statut gérant (UPDATE conditionnel salon + statut, #25).

        `raise_invalid_transition=True` simule la garde TOCTOU/hors-portée : lève
        `InvalidAppointmentTransition`. Sinon, refuse (même erreur) un RDV disparu,
        hors salon, ou dont le statut ne correspond pas à `expected_current` — miroir
        du `WHERE id AND salon_id AND status = :expected` du SQL. `status_changes`
        enregistre `(appointment_id, from, to, reason)`.
        """
        import dataclasses as _dc
        from coiflink_api.domain.errors import InvalidAppointmentTransition

        if self._raise_invalid_transition:
            raise InvalidAppointmentTransition(
                "Cette transition de statut n'est pas autorisée."
            )
        appt = self._appointments.get(appointment_id)
        if (
            appt is None
            or appt.salon_id != salon_id
            or appt.status != expected_current
        ):
            raise InvalidAppointmentTransition(
                "Cette transition de statut n'est pas autorisée."
            )
        self.status_changes.append(
            (appointment_id, expected_current, target, reason)
        )
        updated = _dc.replace(appt, status=target)
        self._appointments[appointment_id] = updated
        return updated

    def assign_hairdresser(self, appointment_id, salon_id, *, hairdresser_id):  # type: ignore[no-untyped-def]
        """(Dés)assigne un coiffeur à un RDV actif du salon (#25).

        `raise_conflict=True` simule le conflit d'agenda (exclusion base) : lève
        `SlotAlreadyBooked`. Refuse (via `InvalidAppointmentTransition`) un RDV
        disparu, hors salon ou terminal — miroir du `WHERE ... status IN (actifs)`.
        `assignments` enregistre `(appointment_id, hairdresser_id)`.
        """
        import dataclasses as _dc
        from coiflink_api.domain.appointment import CLIENT_MODIFIABLE_STATUSES
        from coiflink_api.domain.errors import (
            InvalidAppointmentTransition,
            SlotAlreadyBooked,
        )

        if self._raise_conflict:
            raise SlotAlreadyBooked(
                "Ce créneau vient d'être réservé pour ce coiffeur."
            )
        appt = self._appointments.get(appointment_id)
        if (
            appt is None
            or appt.salon_id != salon_id
            or appt.status not in CLIENT_MODIFIABLE_STATUSES
        ):
            raise InvalidAppointmentTransition(
                "Ce rendez-vous n'accepte plus d'assignation de coiffeur."
            )
        self.assignments.append((appointment_id, hairdresser_id))
        updated = _dc.replace(appt, hairdresser_id=hairdresser_id)
        self._appointments[appointment_id] = updated
        return updated

    def list_for_client(  # type: ignore[no-untyped-def]
        self, client_id, statuses=None, *, newest_first=False
    ):
        """Liste les RDV du `client_id`, filtrés par `statuses` si fourni.

        `newest_first` inverse l'ordre (historique #30) ; par défaut, tri
        chronologique croissant `(date, start_time)` — miroir du SQL.
        """
        result = [
            a
            for a in self._appointments.values()
            if a.client_id == client_id
            and (statuses is None or a.status in statuses)
        ]
        result.sort(
            key=lambda a: (a.date, a.start_time), reverse=newest_first
        )
        return tuple(result)

    def list_for_salon(  # type: ignore[no-untyped-def]
        self, salon_id, date_from, date_to, statuses=None
    ):
        """RDV du salon dans `[date_from, date_to]`, filtrés par statut, triés (#26).

        Refiltre `salon_id` (isolation §11.2) et applique la plage **inclusive** + le
        filtre optionnel `statuses` ; tri `(date, start_time)` — miroir du SQL.
        """
        result = [
            a
            for a in self._appointments.values()
            if a.salon_id == salon_id
            and date_from <= a.date <= date_to
            and (statuses is None or a.status in statuses)
        ]
        result.sort(key=lambda a: (a.date, a.start_time))
        return tuple(result)

    def list_for_hairdresser(  # type: ignore[no-untyped-def]
        self, hairdresser_id, date_from, date_to, statuses=None
    ):
        """RDV assignés au coiffeur dans `[date_from, date_to]`, filtrés, triés (#27).

        Refiltre `hairdresser_id` (isolation « son planning » §11.2) : un RDV d'un autre
        coiffeur ou **non assigné** (`hairdresser_id is None`) est exclu par l'égalité.
        Applique la plage **inclusive** + le filtre optionnel `statuses` ; tri
        `(date, start_time)` — miroir du SQL.
        """
        result = [
            a
            for a in self._appointments.values()
            if a.hairdresser_id == hairdresser_id
            and date_from <= a.date <= date_to
            and (statuses is None or a.status in statuses)
        ]
        result.sort(key=lambda a: (a.date, a.start_time))
        return tuple(result)

    def count_by_status_for_day(  # type: ignore[no-untyped-def]
        self, salon_id, day
    ):
        """Décompte des RDV du salon pour `day`, groupés par statut (US-6.1 #39).

        Refiltre `salon_id` et `date` (isolation §11.2) — miroir du `GROUP BY` SQL.
        Retourne `{status: count}` ; un statut sans RDV du jour est absent de la map.
        """
        counts: dict = {}
        for appt in self._appointments.values():
            if appt.salon_id == salon_id and appt.date == day:
                counts[appt.status] = counts.get(appt.status, 0) + 1
        return counts

    def demand_by_service(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from=None, date_to=None
    ):
        """Retourne `demand_results` (préconfiguré) et enregistre l'appel (#41).

        Le fake ne ré-agrège pas depuis `_appointments` : les tests configurent
        `demand_results` directement pour éviter de construire un dataset complet
        d'`Appointment`/`BookedService`. L'isolation SQL réelle est testée en e2e.
        Les arguments sont tracés dans `demand_by_service_calls` pour assertions.
        """
        self.demand_by_service_calls.append(
            {
                "salon_id": salon_id,
                "statuses": statuses,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return self.demand_results

    def segment_active_clients(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from, date_to
    ):
        """Retourne `segment_results` (préconfiguré) et enregistre l'appel (#42).

        Le fake ne ré-agrège pas depuis `_appointments` : les tests configurent
        `segment_results` directement. L'isolation SQL réelle est testée en e2e.
        Les arguments sont tracés dans `segment_active_clients_calls` pour assertions.
        """
        self.segment_active_clients_calls.append(
            {
                "salon_id": salon_id,
                "statuses": statuses,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return self.segment_results


class FakeCustomerRepository:
    """Dépôt de fiches clients en mémoire (US-4.1, #28).

    Implémente le port `CustomerRepository` sans I/O réelle. Isolation §11.2 :
    `find_by_id`, `list_for_salon`, `count_for_salon` et `phone_exists` filtrent
    sur `salon_id` — une fiche d'un autre salon est indiscernable d'une fiche
    inexistante, et le même téléphone reste acceptable dans **un autre** salon.

    `raise_conflict=True` simule la **course concurrente** : `create` lève
    `CustomerAlreadyExists` (le filet base derrière le pré-contrôle applicatif).
    """

    def __init__(self, *, raise_conflict: bool = False) -> None:
        self._customers: dict[uuid.UUID, object] = {}
        # Visites terminées par fiche (US-4.2, #29), déjà triées « plus récent
        # d'abord » comme le contrat du dépôt SQL. Les fakes n'ont **pas** d'`user_id` :
        # le lien fiche ↔ compte est encapsulé — une fiche sans entrée ici renvoie
        # une liste vide (équivalent d'une fiche walk-in ou sans visite réalisée).
        self._visits: dict[uuid.UUID, tuple] = {}
        self.created: list = []
        self.last_visits_call: tuple | None = None
        self.raise_conflict = raise_conflict

    def set_visits(self, customer_id: uuid.UUID, visits: tuple) -> None:
        """Amorce l'historique de visites d'une fiche (helper de test, #29)."""

        self._visits[customer_id] = visits

    def create(self, customer):  # type: ignore[no-untyped-def]
        from coiflink_api.domain.customer import Customer
        from coiflink_api.domain.errors import CustomerAlreadyExists

        if self.raise_conflict:
            raise CustomerAlreadyExists(
                "Une fiche existe déjà pour ce numéro dans ce salon."
            )
        entity = Customer(
            id=uuid.uuid4(),
            salon_id=customer.salon_id,
            full_name=customer.full_name,
            phone=customer.phone,
            gender=customer.gender,
            notes=customer.notes,
            last_visit_at=None,
            total_visits=0,
            created_at=_CREATED_AT,
            updated_at=_CREATED_AT,
        )
        self._customers[entity.id] = entity
        self.created.append(customer)
        return entity

    def find_by_id(self, salon_id: uuid.UUID, customer_id: uuid.UUID):  # type: ignore[no-untyped-def]
        customer = self._customers.get(customer_id)
        if customer is None or customer.salon_id != salon_id:  # type: ignore[union-attr]
            return None
        return customer

    def _for_salon(self, salon_id: uuid.UUID) -> list:
        return [
            c
            for c in self._customers.values()
            if c.salon_id == salon_id  # type: ignore[union-attr]
        ]

    def _matching(self, salon_id: uuid.UUID, filter) -> list:  # type: ignore[no-untyped-def]
        """Filtrage en mémoire **miroir** des clauses SQL : salon + critères ET."""

        result = []
        for c in self._for_salon(salon_id):
            if filter.created_at_from is not None and c.created_at < filter.created_at_from:  # type: ignore[union-attr]
                continue
            if filter.created_at_to is not None and c.created_at > filter.created_at_to:  # type: ignore[union-attr]
                continue
            if filter.gender is not None and c.gender != filter.gender:  # type: ignore[union-attr]
                continue
            if filter.q is not None and filter.q.lower() not in c.full_name.lower():  # type: ignore[union-attr]
                continue
            result.append(c)
        return result

    def list_for_salon(self, salon_id: uuid.UUID, *, filter, limit: int, offset: int):  # type: ignore[no-untyped-def]
        return tuple(self._matching(salon_id, filter)[offset : offset + limit])

    def count_for_salon(self, salon_id: uuid.UUID, *, filter) -> int:  # type: ignore[no-untyped-def]
        return len(self._matching(salon_id, filter))

    def phone_exists(self, salon_id: uuid.UUID, phone: str) -> bool:
        return any(c.phone == phone for c in self._for_salon(salon_id))  # type: ignore[union-attr]

    def update_notes(self, salon_id, customer_id, notes):  # type: ignore[no-untyped-def]
        from dataclasses import replace

        from coiflink_api.domain.errors import CustomerNotFound

        customer = self._customers.get(customer_id)
        if customer is None or customer.salon_id != salon_id:  # type: ignore[union-attr]
            # Fiche hors salon/inexistante : indiscernable (isolation §11.2).
            raise CustomerNotFound("Fiche client introuvable.")
        # Seule `notes` change ; `updated_at` régénéré (miroir du `onupdate` SQL).
        updated = replace(customer, notes=notes, updated_at=_UPDATED_AT)
        self._customers[customer_id] = updated
        return updated

    def list_visits(self, salon_id, customer_id, statuses):  # type: ignore[no-untyped-def]
        # Enregistre l'appel (les tests vérifient que `statuses == HISTORY_STATUSES`).
        self.last_visits_call = (salon_id, customer_id, statuses)
        customer = self._customers.get(customer_id)
        if customer is None or customer.salon_id != salon_id:  # type: ignore[union-attr]
            # Fiche hors salon/inexistante : aucun RDV reliable (isolation §11.2).
            return ()
        visits = self._visits.get(customer_id, ())
        # Le dépôt SQL filtre le statut en base ; le fake reproduit ce filtre.
        return tuple(v for v in visits if v.status in statuses)


@pytest.fixture()
def fake_service_repository() -> "FakeServiceRepository":
    return FakeServiceRepository()


@pytest.fixture()
def fake_customer_repository() -> "FakeCustomerRepository":
    return FakeCustomerRepository()


@pytest.fixture()
def fake_audit_log() -> "FakeAuditLog":
    return FakeAuditLog()


@pytest.fixture()
def fake_salon_catalog_repository() -> "FakeSalonCatalogRepository":
    return FakeSalonCatalogRepository()


@pytest.fixture()
def fake_appointment_repository() -> "FakeAppointmentRepository":
    return FakeAppointmentRepository()


class FakePaymentRepository:
    """Dépôt de paiements en mémoire (US-5.1/5.3, #33/#34).

    Implémente le port `PaymentRepository` sans I/O réelle. Isolation §11.2 :
    `get` et `mark_adjusted` filtrent sur `(salon_id, id)` — un paiement d'un autre
    salon est indiscernable d'un paiement inexistant. **Aucune** méthode `delete`
    n'est exposée : un paiement validé n'est jamais supprimé (§8.2).
    """

    def __init__(
        self,
        payments: list | None = None,
        *,
        client_names: dict | None = None,
        discrepancies: list | None = None,
    ) -> None:
        self._payments: dict[uuid.UUID, object] = {}
        self.created: list = []
        self.mark_adjusted_calls: list[tuple[uuid.UUID, uuid.UUID]] = []
        # Résolution optionnelle `client_id → full_name` (miroir du join SQL #35).
        self._client_names: dict = dict(client_names or {})
        for p in payments or []:
            self._payments[p.id] = p  # type: ignore[union-attr]
        # Écarts de caisse pré-chargés (US-5.4, #36) — miroir du LEFT JOIN SQL.
        self._discrepancies: list = list(discrepancies or [])
        self.list_completed_calls: list = []
        self.count_completed_calls: list = []

    def create(self, payment):  # type: ignore[no-untyped-def]
        from coiflink_api.domain.payment import Payment

        entity = Payment(
            id=uuid.uuid4(),
            salon_id=payment.salon_id,
            amount=payment.amount,
            currency=payment.currency,
            payment_method=payment.payment_method,
            status=payment.status,
            recorded_by=payment.recorded_by,
            appointment_id=payment.appointment_id,
            service_id=payment.service_id,
            client_id=payment.client_id,
            reference=payment.reference,
            created_at=_CREATED_AT,
        )
        self._payments[entity.id] = entity
        self.created.append(payment)
        return entity

    def get(self, salon_id: uuid.UUID, payment_id: uuid.UUID):  # type: ignore[no-untyped-def]
        from coiflink_api.domain.errors import PaymentNotFound

        payment = self._payments.get(payment_id)
        if payment is None or payment.salon_id != salon_id:  # type: ignore[union-attr]
            raise PaymentNotFound("Paiement introuvable.")
        return payment

    def mark_adjusted(self, salon_id: uuid.UUID, payment_id: uuid.UUID):  # type: ignore[no-untyped-def]
        import dataclasses as _dc

        from coiflink_api.domain.enums import PaymentStatus
        from coiflink_api.domain.errors import PaymentNotAdjustable, PaymentNotFound

        payment = self._payments.get(payment_id)
        if payment is None or payment.salon_id != salon_id:  # type: ignore[union-attr]
            raise PaymentNotFound("Paiement introuvable.")
        if payment.status != PaymentStatus.VALIDATED.value:  # type: ignore[union-attr]
            raise PaymentNotAdjustable("Ce paiement ne peut pas être corrigé.")
        self.mark_adjusted_calls.append((salon_id, payment_id))
        updated = _dc.replace(payment, status=PaymentStatus.ADJUSTED.value)
        self._payments[payment_id] = updated
        return updated

    def list_for_salon(self, salon_id, *, filter, limit, offset):  # type: ignore[no-untyped-def]
        from coiflink_api.domain.transaction import Transaction

        matches = self._matching(salon_id, filter)
        # Tri déterministe : created_at DESC, id DESC (miroir du SQL #35).
        matches.sort(key=lambda p: (p.created_at, p.id), reverse=True)
        page = matches[offset : offset + limit]
        return tuple(
            Transaction(payment=p, client_name=self._client_names.get(p.client_id))
            for p in page
        )

    def count_for_salon(self, salon_id, *, filter):  # type: ignore[no-untyped-def]
        return len(self._matching(salon_id, filter))

    def _matching(self, salon_id, filter):  # type: ignore[no-untyped-def]
        """Filtrage en mémoire **miroir** des clauses SQL (§35) : salon + critères ET."""

        result = []
        for p in self._payments.values():
            if p.salon_id != salon_id:  # type: ignore[union-attr]
                continue
            if filter.created_at_from is not None and p.created_at < filter.created_at_from:
                continue
            if filter.created_at_to is not None and p.created_at > filter.created_at_to:
                continue
            if filter.client_id is not None and p.client_id != filter.client_id:
                continue
            if filter.amount_min is not None and p.amount < filter.amount_min:
                continue
            if filter.amount_max is not None and p.amount > filter.amount_max:
                continue
            if filter.payment_method is not None and p.payment_method != filter.payment_method:
                continue
            if filter.q is not None:
                name = self._client_names.get(p.client_id) or ""
                if filter.q.lower() not in name.lower():
                    continue
            result.append(p)
        return result

    def list_completed_without_payment(  # type: ignore[no-untyped-def]
        self, salon_id: uuid.UUID, *, filter, limit: int, offset: int
    ):
        self.list_completed_calls.append((salon_id, filter, limit, offset))
        matches = self._matching_discrepancies(salon_id, filter)
        return tuple(matches[offset: offset + limit])

    def count_completed_without_payment(self, salon_id: uuid.UUID, *, filter) -> int:  # type: ignore[no-untyped-def]
        self.count_completed_calls.append((salon_id, filter))
        return len(self._matching_discrepancies(salon_id, filter))

    def _matching_discrepancies(self, salon_id: uuid.UUID, filter) -> list:  # type: ignore[no-untyped-def]
        """Filtrage en mémoire des écarts : salon_id + plage de dates (§36)."""

        result = []
        for d in self._discrepancies:
            if d.salon_id != salon_id:
                continue
            if filter.date_from is not None and d.appointment_date < filter.date_from:
                continue
            if filter.date_to is not None and d.appointment_date > filter.date_to:
                continue
            result.append(d)
        # Tri déterministe : appointment_date DESC, start_time DESC, appointment_id DESC.
        result.sort(
            key=lambda d: (d.appointment_date, d.start_time, d.appointment_id),
            reverse=True,
        )
        return result


class FakeCashJournalRepository:
    """Dépôt du journal de caisse en mémoire (append-only, US-5.3, #34).

    Implémente le port `CashJournalRepository` sans I/O réelle. **Invariant
    append-only structurel** : ce fake n'expose **aucune** méthode `update`/`delete`
    — l'immuabilité du journal est ainsi vérifiée par le contrat lui-même. Isolation
    §11.2 : `list_for_salon` et `count_for_salon` filtrent sur `salon_id`.
    """

    def __init__(self) -> None:
        self._entries: list = []
        self.appended: list = []

    def append(self, entry):  # type: ignore[no-untyped-def]
        from coiflink_api.domain.cash_journal import CashJournalEntry

        created = CashJournalEntry(
            id=uuid.uuid4(),
            salon_id=entry.salon_id,
            operation_type=entry.operation_type,
            amount=entry.amount,
            currency="XOF",
            performed_by=entry.performed_by,
            performed_by_name=None,
            transaction_id=entry.transaction_id,
            description=entry.description,
            created_at=_CREATED_AT,
        )
        self._entries.append(created)
        self.appended.append(entry)
        return created

    def list_for_salon(self, salon_id: uuid.UUID, *, limit: int, offset: int):  # type: ignore[no-untyped-def]
        entries = [e for e in self._entries if e.salon_id == salon_id]
        entries_desc = list(reversed(entries))
        return tuple(entries_desc[offset : offset + limit])

    def count_for_salon(self, salon_id: uuid.UUID) -> int:
        return sum(1 for e in self._entries if e.salon_id == salon_id)

    def net_revenue_between(
        self,
        salon_id: uuid.UUID,
        *,
        created_at_from: datetime.datetime,
        created_at_to: datetime.datetime,
    ) -> "decimal.Decimal":
        """Somme signée du CA sur l'intervalle (fake : retourne 0.00 par défaut).

        Les tests qui ont besoin de valeurs configurables définissent leur propre
        fake plus spécialisé (`FakeRevenueCashJournalRepository`).
        """
        return decimal.Decimal("0.00")


class FakeReceiptRepository:
    """Dépôt de lecture des reçus en mémoire (US-5.5, #38).

    Implémente le port `ReceiptRepository` sans I/O réelle. **Appartenance §11.2** :
    `list_receipts_for_client`/`count_receipts_for_client`/`get_receipt_for_client`
    filtrent **inconditionnellement** sur `client_id` (via `Receipt.payment_id` →
    paiement du client) — un reçu d'un autre client est indiscernable d'un reçu
    inexistant (non-oracle §11.3). **Aucune** méthode d'écriture n'est exposée : le
    reçu est une projection en lecture.

    `receipts_by_client` associe un `client_id` à un tuple de `Receipt` **déjà**
    ordonné « plus récent d'abord » (miroir du tri SQL) ; un `client_id` absent
    renvoie une liste vide.
    """

    def __init__(
        self, receipts_by_client: dict | None = None
    ) -> None:
        self._by_client: dict = dict(receipts_by_client or {})

    def list_receipts_for_client(self, client_id, *, limit, offset):  # type: ignore[no-untyped-def]
        receipts = self._by_client.get(client_id, ())
        return tuple(receipts[offset : offset + limit])

    def count_receipts_for_client(self, client_id) -> int:  # type: ignore[no-untyped-def]
        return len(self._by_client.get(client_id, ()))

    def get_receipt_for_client(self, client_id, payment_id):  # type: ignore[no-untyped-def]
        for receipt in self._by_client.get(client_id, ()):
            if receipt.payment_id == payment_id:
                return receipt
        return None


@pytest.fixture()
def fake_payment_repository() -> "FakePaymentRepository":
    return FakePaymentRepository()


@pytest.fixture()
def fake_receipt_repository() -> "FakeReceiptRepository":
    return FakeReceiptRepository()


@pytest.fixture()
def fake_cash_journal_repository() -> "FakeCashJournalRepository":
    return FakeCashJournalRepository()
