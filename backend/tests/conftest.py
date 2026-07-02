"""Faux adaptateurs partagés entre les suites de tests (inscription #8).

Chaque fake implémente le protocole du port correspondant sans I/O réelle.
Aucune valeur secrète réelle ni PII n'est utilisée dans ces fixtures.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from coiflink_api.domain.errors import PhoneAlreadyInUse
from coiflink_api.domain.otp import OtpChallenge
from coiflink_api.domain.user import User, UserToCreate

_CREATED_AT = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
_FIXED_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")


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


class FakeUserRepositoryRaisingDuplicate:
    """Dépôt dont `create` lève PhoneAlreadyInUse (simulation d'IntegrityError concurrente)."""

    def phone_exists(self, phone: str) -> bool:  # noqa: ARG002
        return False

    def create(self, user: UserToCreate) -> User:  # noqa: ARG002
        raise PhoneAlreadyInUse("Contrainte base violée (race condition simulée).")


class FakeOtpSender:
    """Expéditeur OTP en mémoire ; ne journalise rien."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, phone: str, code: str) -> None:
        self.sent.append((phone, code))


class FakeOtpRepository:
    """Dépôt OTP en mémoire."""

    def __init__(self) -> None:
        self.challenges: dict[str, OtpChallenge] = {}

    def save(self, phone: str, challenge: OtpChallenge) -> None:
        self.challenges[phone] = challenge

    def get(self, phone: str) -> OtpChallenge | None:
        return self.challenges.get(phone)

    def delete(self, phone: str) -> None:
        self.challenges.pop(phone, None)


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
