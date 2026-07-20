"""Faux adaptateurs partagés entre les suites de tests (inscription #8, connexion #10, #13).

Chaque fake implémente le protocole du port correspondant sans I/O réelle.
Aucune valeur secrète réelle ni PII n'est utilisée dans ces fixtures.
"""

from __future__ import annotations

import dataclasses
import datetime
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

    def list_for_salon(self, salon_id: uuid.UUID, *, include_inactive: bool = True):  # type: ignore[no-untyped-def]
        return tuple(
            s
            for s in self._services.values()
            if s.salon_id == salon_id  # type: ignore[union-attr]
            and (include_inactive or s.is_active)  # type: ignore[union-attr]
        )

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


@pytest.fixture()
def fake_service_repository() -> "FakeServiceRepository":
    return FakeServiceRepository()


@pytest.fixture()
def fake_audit_log() -> "FakeAuditLog":
    return FakeAuditLog()


@pytest.fixture()
def fake_salon_catalog_repository() -> "FakeSalonCatalogRepository":
    return FakeSalonCatalogRepository()
