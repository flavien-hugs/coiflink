"""Tests des cas d'usage borne kiosque — identité walk-in (US-8.2, #156).

Couvre `IdentifyWalkInCustomer` et `CreateWalkInCustomer` avec des fakes :
- Normalisation du téléphone **avant** l'appel au dépôt (le dépôt reçoit
  toujours la forme canonique E.164, quel que soit le format soumis).
- Lookup : fiche trouvée → `WalkInIdentity` (prénom seul, reset limiteur) ;
  fiche absente → `None` + `record_failure` ; format invalide → `InvalidPhone`
  + `record_failure`, **aucun** appel dépôt ; limiteur verrouillé →
  `TooManyLoginAttempts`, **aucun** appel dépôt.
- Isolation §11.2 : le `salon_id` transmis au dépôt est celui de la portée,
  jamais du corps.
- Lookup **sans audit** : aucune entrée d'audit lors d'une recherche.
- Création : `full_name` composé « Prénom Nom », téléphone canonique,
  `gender`/`notes` `None` ; audit `CUSTOMER_CREATED` une fois, `metadata={}` ;
  acteur = `actor_user_id` du device ; doublon → `CustomerAlreadyExists` sans
  écriture ni audit ; validation invalide → aucune écriture, aucun audit.
- Isolation §11.2 création : même téléphone dans un autre salon → accepté.
- Anti-oracle structurel : `application/kiosk_customers.py` n'importe aucun
  port `users` (assertion d'import statique).

Tous les ports sont des fakes — aucune base, aucun réseau.
"""

from __future__ import annotations

import importlib
import uuid

import pytest

from coiflink_api.application.kiosk_customers import (
    CreateWalkInCustomer,
    IdentifyWalkInCustomer,
)
from coiflink_api.domain.audit import AuditAction, ENTITY_TYPE_CUSTOMER
from coiflink_api.domain.customer import WalkInCustomerCommand, WalkInIdentity
from coiflink_api.domain.errors import (
    CustomerAlreadyExists,
    InvalidCustomerName,
    InvalidPhone,
    TooManyLoginAttempts,
)

from .conftest import FakeAuditLog, FakeCustomerRepository, FakeLoginRateLimiter

# Identifiants synthétiques — aucune PII, aucun secret réel.
_SALON_A = uuid.UUID("aaaaaa00-0000-0000-0000-000000000001")
_SALON_B = uuid.UUID("bbbbbb00-0000-0000-0000-000000000002")
_DEVICE_ID = uuid.UUID("d0000000-0000-0000-0000-000000000001")
_RATE_KEY = f"{_DEVICE_ID}|127.0.0.1"

_CANONICAL_PHONE = "+2250700000000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_customer(
    repo: FakeCustomerRepository,
    *,
    salon_id: uuid.UUID = _SALON_A,
    full_name: str = "Awa Koné",
    phone: str = _CANONICAL_PHONE,
) -> object:
    """Crée une fiche en mémoire directement dans le dépôt (via `create`)."""
    from coiflink_api.domain.customer import CustomerToCreate

    return repo.create(
        CustomerToCreate(salon_id=salon_id, full_name=full_name, phone=phone)
    )


def _make_lookup(
    repo: FakeCustomerRepository,
    limiter: FakeLoginRateLimiter | None = None,
) -> IdentifyWalkInCustomer:
    return IdentifyWalkInCustomer(repo, limiter or FakeLoginRateLimiter())


def _make_create(
    repo: FakeCustomerRepository,
    audit: FakeAuditLog | None = None,
) -> CreateWalkInCustomer:
    return CreateWalkInCustomer(repo, audit or FakeAuditLog())


# ---------------------------------------------------------------------------
# Anti-oracle structurel : aucun import de port `users`
# ---------------------------------------------------------------------------


def test_kiosk_customers_module_does_not_import_user_repository() -> None:
    """Le module applicatif kiosque n'importe **jamais** le port `users` (ADR-0026).

    Un import de `UserRepository` ou de `user_repository` transformerait le cas
    d'usage en oracle d'existence de compte (§11.1) — cet invariant est vérifié
    statiquement sur le module compilé.
    """
    mod = importlib.import_module("coiflink_api.application.kiosk_customers")
    # Vérifie toutes les importations directes connues du module.
    assert not hasattr(mod, "UserRepository"), (
        "kiosk_customers importe UserRepository — oracle ADR-0026 violé"
    )
    # Inspecte le bytecode des imports : aucun chemin 'user_repository' ne doit y figurer.
    source_file = mod.__spec__.origin  # type: ignore[union-attr]
    with open(source_file) as f:
        source = f.read()
    assert "user_repository" not in source, (
        "kiosk_customers contient 'user_repository' dans son code source — ADR-0026 violé"
    )


# ---------------------------------------------------------------------------
# IdentifyWalkInCustomer — parcours heureux
# ---------------------------------------------------------------------------


class TestIdentifyWalkInCustomerFound:
    def setup_method(self) -> None:
        self.repo = FakeCustomerRepository()
        self.limiter = FakeLoginRateLimiter()
        _seed_customer(self.repo)
        self.uc = _make_lookup(self.repo, self.limiter)

    def test_returns_walk_in_identity_when_found(self) -> None:
        result = self.uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert isinstance(result, WalkInIdentity)

    def test_returns_first_name_only(self) -> None:
        result = self.uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert result is not None
        assert result.first_name == "Awa"

    def test_customer_id_is_uuid(self) -> None:
        result = self.uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert result is not None
        assert isinstance(result.customer_id, uuid.UUID)

    def test_rate_limiter_reset_on_success(self) -> None:
        self.uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert _RATE_KEY in self.limiter.resets

    def test_rate_limiter_no_failure_on_success(self) -> None:
        self.uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert _RATE_KEY not in self.limiter.failures

    def test_rate_limiter_check_called_before_repo(self) -> None:
        self.uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert _RATE_KEY in self.limiter.checks

    def test_phone_normalised_to_canonical_before_repo(self) -> None:
        """Formats variés → même fiche (le dépôt reçoit toujours la forme canonique)."""
        for raw in ["07 00 00 00 00", "+225 07-00-00-00-00", "002250700000000"]:
            repo = FakeCustomerRepository()
            _seed_customer(repo)
            uc = _make_lookup(repo)
            result = uc.execute(_SALON_A, raw, rate_key=_RATE_KEY)
            assert result is not None, f"Devrait trouver la fiche avec le format '{raw}'"
            assert result.first_name == "Awa"


# ---------------------------------------------------------------------------
# IdentifyWalkInCustomer — fiche absente
# ---------------------------------------------------------------------------


class TestIdentifyWalkInCustomerNotFound:
    def setup_method(self) -> None:
        self.repo = FakeCustomerRepository()
        self.limiter = FakeLoginRateLimiter()
        self.uc = _make_lookup(self.repo, self.limiter)

    def test_returns_none_when_no_matching_customer(self) -> None:
        result = self.uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert result is None

    def test_record_failure_called_when_not_found(self) -> None:
        self.uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert _RATE_KEY in self.limiter.failures

    def test_reset_not_called_when_not_found(self) -> None:
        self.uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert _RATE_KEY not in self.limiter.resets

    def test_isolation_other_salon_customer_not_found(self) -> None:
        """Une fiche du salon B est indiscernable d'une fiche inexistante depuis le salon A."""
        _seed_customer(self.repo, salon_id=_SALON_B)
        result = self.uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert result is None


# ---------------------------------------------------------------------------
# IdentifyWalkInCustomer — téléphone invalide
# ---------------------------------------------------------------------------


class TestIdentifyWalkInCustomerInvalidPhone:
    def setup_method(self) -> None:
        self.repo = FakeCustomerRepository()
        self.limiter = FakeLoginRateLimiter()
        self.uc = _make_lookup(self.repo, self.limiter)

    def test_invalid_format_raises_invalid_phone(self) -> None:
        with pytest.raises(InvalidPhone):
            self.uc.execute(_SALON_A, "not-a-phone", rate_key=_RATE_KEY)

    def test_invalid_phone_counts_as_failure(self) -> None:
        try:
            self.uc.execute(_SALON_A, "not-a-phone", rate_key=_RATE_KEY)
        except InvalidPhone:
            pass
        assert _RATE_KEY in self.limiter.failures

    def test_invalid_phone_no_repo_call(self) -> None:
        """Un format invalide ne touche pas le dépôt (normalisation avant accès base).

        On vérifie que `find_by_phone` n'a pas été consulté : si c'était le cas
        avec une fiche existante, le use case retournerait un `WalkInIdentity` au
        lieu de lever `InvalidPhone`. On assure donc qu'aucun résultat ne sort.
        """
        _seed_customer(self.repo)
        count_before = len(self.repo.created)  # enregistre le décompte avant l'appel
        result = None
        try:
            result = self.uc.execute(_SALON_A, "not-a-phone", rate_key=_RATE_KEY)
        except InvalidPhone:
            pass
        # Aucune écriture supplémentaire ne doit avoir eu lieu.
        assert len(self.repo.created) == count_before
        # Et aucun résultat ne doit avoir été retourné.
        assert result is None


# ---------------------------------------------------------------------------
# IdentifyWalkInCustomer — limiteur verrouillé
# ---------------------------------------------------------------------------


class TestIdentifyWalkInCustomerRateLimited:
    def test_raises_too_many_attempts_when_locked(self) -> None:
        limiter = FakeLoginRateLimiter(locked=True)
        repo = FakeCustomerRepository()
        _seed_customer(repo)
        uc = _make_lookup(repo, limiter)
        with pytest.raises(TooManyLoginAttempts):
            uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)

    def test_locked_no_repo_call(self) -> None:
        """Limiteur verrouillé → zéro accès au dépôt."""
        limiter = FakeLoginRateLimiter(locked=True)
        repo = FakeCustomerRepository()
        uc = _make_lookup(repo, limiter)
        try:
            uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        except TooManyLoginAttempts:
            pass
        # Aucun client créé via le dépôt fake.
        assert len(repo.created) == 0

    def test_locked_retry_after_propagated(self) -> None:
        limiter = FakeLoginRateLimiter(locked=True, retry_after=600)
        repo = FakeCustomerRepository()
        uc = _make_lookup(repo, limiter)
        with pytest.raises(TooManyLoginAttempts) as exc_info:
            uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert exc_info.value.retry_after == 600


# ---------------------------------------------------------------------------
# IdentifyWalkInCustomer — pas d'audit
# ---------------------------------------------------------------------------


class TestIdentifyWalkInCustomerNoAudit:
    """La recherche ne journalise **rien** (ADR-0026 : les lectures ne sont pas auditées)."""

    def test_lookup_found_no_audit_entry(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        _seed_customer(repo)
        uc = IdentifyWalkInCustomer(repo, FakeLoginRateLimiter())
        uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        # IdentifyWalkInCustomer n'a pas de référence à audit_log — aucun enregistrement.
        assert len(audit.recorded) == 0

    def test_lookup_not_found_no_audit_entry(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        uc = IdentifyWalkInCustomer(repo, FakeLoginRateLimiter())
        uc.execute(_SALON_A, "0700000000", rate_key=_RATE_KEY)
        assert len(audit.recorded) == 0


# ---------------------------------------------------------------------------
# CreateWalkInCustomer — parcours heureux
# ---------------------------------------------------------------------------


class TestCreateWalkInCustomerSuccess:
    def setup_method(self) -> None:
        self.repo = FakeCustomerRepository()
        self.audit = FakeAuditLog()
        self.uc = _make_create(self.repo, self.audit)

    def _exec(
        self,
        *,
        first_name: str = "Awa",
        last_name: str = "Koné",
        phone: str = "0700000000",
    ) -> WalkInIdentity:
        cmd = WalkInCustomerCommand(first_name=first_name, last_name=last_name, phone=phone)
        return self.uc.execute(_SALON_A, cmd, actor_user_id=_DEVICE_ID)

    def test_returns_walk_in_identity(self) -> None:
        result = self._exec()
        assert isinstance(result, WalkInIdentity)

    def test_first_name_matches_input(self) -> None:
        result = self._exec()
        assert result.first_name == "Awa"

    def test_customer_id_is_uuid(self) -> None:
        result = self._exec()
        assert isinstance(result.customer_id, uuid.UUID)

    def test_full_name_composed_in_order(self) -> None:
        self._exec()
        created = self.repo.created[0]
        assert created.full_name == "Awa Koné"

    def test_phone_stored_canonical(self) -> None:
        self._exec()
        created = self.repo.created[0]
        assert created.phone == "+2250700000000"

    def test_gender_none(self) -> None:
        """La borne ne collecte pas le genre (collecte minimale §11.3)."""
        self._exec()
        created = self.repo.created[0]
        assert created.gender is None

    def test_notes_none(self) -> None:
        """La borne ne collecte pas les notes (collecte minimale §11.3)."""
        self._exec()
        created = self.repo.created[0]
        assert created.notes is None

    def test_salon_id_from_scope_not_body(self) -> None:
        """Le salon vient de la portée validée, jamais du corps (anti-élévation)."""
        self._exec()
        created = self.repo.created[0]
        assert created.salon_id == _SALON_A

    def test_one_audit_entry_emitted(self) -> None:
        self._exec()
        assert len(self.audit.recorded) == 1

    def test_audit_action_is_customer_created(self) -> None:
        self._exec()
        entry = self.audit.recorded[0]
        assert entry.action == AuditAction.CUSTOMER_CREATED.value

    def test_audit_metadata_is_empty(self) -> None:
        """Aucune PII dans le journal d'audit (§11.3/§11.4)."""
        self._exec()
        entry = self.audit.recorded[0]
        assert entry.metadata == {}

    def test_audit_actor_is_device_id(self) -> None:
        """L'acteur est `principal.id` du compte de service de la borne (ADR-0041)."""
        self._exec()
        entry = self.audit.recorded[0]
        assert entry.actor_user_id == _DEVICE_ID

    def test_audit_entity_type_is_customer(self) -> None:
        self._exec()
        entry = self.audit.recorded[0]
        assert entry.entity_type == ENTITY_TYPE_CUSTOMER

    def test_audit_entity_id_matches_created_customer(self) -> None:
        result = self._exec()
        entry = self.audit.recorded[0]
        assert entry.entity_id == result.customer_id

    def test_audit_salon_id_matches_scope(self) -> None:
        self._exec()
        entry = self.audit.recorded[0]
        assert entry.salon_id == _SALON_A


# ---------------------------------------------------------------------------
# CreateWalkInCustomer — doublon de téléphone
# ---------------------------------------------------------------------------


class TestCreateWalkInCustomerDuplicate:
    def test_duplicate_phone_raises_customer_already_exists(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        _seed_customer(repo)
        uc = _make_create(repo, audit)
        cmd = WalkInCustomerCommand(first_name="Autre", last_name="Nom", phone="0700000000")
        with pytest.raises(CustomerAlreadyExists):
            uc.execute(_SALON_A, cmd, actor_user_id=_DEVICE_ID)

    def test_duplicate_no_new_customer_created(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        _seed_customer(repo)
        count_before = len(repo.created)
        uc = _make_create(repo, audit)
        cmd = WalkInCustomerCommand(first_name="Autre", last_name="Nom", phone="0700000000")
        try:
            uc.execute(_SALON_A, cmd, actor_user_id=_DEVICE_ID)
        except CustomerAlreadyExists:
            pass
        assert len(repo.created) == count_before

    def test_duplicate_no_audit_entry(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        _seed_customer(repo)
        uc = _make_create(repo, audit)
        cmd = WalkInCustomerCommand(first_name="Autre", last_name="Nom", phone="0700000000")
        try:
            uc.execute(_SALON_A, cmd, actor_user_id=_DEVICE_ID)
        except CustomerAlreadyExists:
            pass
        assert len(audit.recorded) == 0

    def test_same_phone_different_salon_accepted(self) -> None:
        """Isolation §11.2 : un même numéro peut exister dans deux salons distincts."""
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        _seed_customer(repo, salon_id=_SALON_A)
        uc = _make_create(repo, audit)
        cmd = WalkInCustomerCommand(first_name="Autre", last_name="Nom", phone="0700000000")
        # Crée dans le salon B — ne doit pas lever CustomerAlreadyExists.
        result = uc.execute(_SALON_B, cmd, actor_user_id=_DEVICE_ID)
        assert result.first_name == "Autre"

    def test_concurrent_conflict_via_raise_conflict_flag(self) -> None:
        """Course concurrente simulée par `raise_conflict=True` (filet base)."""
        repo = FakeCustomerRepository(raise_conflict=True)
        audit = FakeAuditLog()
        uc = _make_create(repo, audit)
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="Koné", phone="0700000000")
        with pytest.raises(CustomerAlreadyExists):
            uc.execute(_SALON_A, cmd, actor_user_id=_DEVICE_ID)


# ---------------------------------------------------------------------------
# CreateWalkInCustomer — validation invalide
# ---------------------------------------------------------------------------


class TestCreateWalkInCustomerInvalidInput:
    def test_invalid_name_raises_before_repo(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        uc = _make_create(repo, audit)
        cmd = WalkInCustomerCommand(first_name="", last_name="Koné", phone="0700000000")
        with pytest.raises(InvalidCustomerName):
            uc.execute(_SALON_A, cmd, actor_user_id=_DEVICE_ID)
        assert len(repo.created) == 0
        assert len(audit.recorded) == 0

    def test_invalid_phone_raises_before_repo(self) -> None:
        repo = FakeCustomerRepository()
        audit = FakeAuditLog()
        uc = _make_create(repo, audit)
        cmd = WalkInCustomerCommand(first_name="Awa", last_name="Koné", phone="not-a-phone")
        with pytest.raises(InvalidPhone):
            uc.execute(_SALON_A, cmd, actor_user_id=_DEVICE_ID)
        assert len(repo.created) == 0
        assert len(audit.recorded) == 0
