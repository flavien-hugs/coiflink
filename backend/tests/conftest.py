"""Faux adaptateurs partagés entre les suites de tests (inscription #8, connexion #10).

Chaque fake implémente le protocole du port correspondant sans I/O réelle.
Aucune valeur secrète réelle ni PII n'est utilisée dans ces fixtures.
"""

from __future__ import annotations

import dataclasses
import datetime
import uuid
from typing import Union

import pytest

from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import NotificationChannel
from coiflink_api.domain.errors import PhoneAlreadyInUse, TooManyLoginAttempts
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
    ) -> None:
        self._pair = pair or FAKE_TOKEN_PAIR
        self._verify_refresh_result: Union[TokenClaims, Exception] = (
            verify_refresh_result if verify_refresh_result is not None else FAKE_REFRESH_CLAIMS
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
