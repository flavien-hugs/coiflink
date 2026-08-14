"""Tests unitaires — domaine `audit` (US-2.3, #17).

Couvre :
- `AuditAction` : domaine fermé, valeurs string, membre check ;
- `AuditEntry` : construction, `metadata` par défaut, `salon_id` par défaut,
  invariant de non-fuite (aucun champ PII/secret) ;
- `ENTITY_TYPE_SERVICE` : constante de type d'entité ;
- `AUDIT_ACTION_CATEGORY`/`ACTIONS_BY_CATEGORY` : exhaustivité de la table de
  catégorisation (page gérante « Journal d'audit », réorganisation du tableau
  de bord) ;
- `AuditLogEntry` : projection de lecture (nom d'acteur, catégorie) ;
- `validate_audit_log_filter` : plage ordonnée + catégorie fermée.

Aucune base, aucun réseau — domaine pur.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from coiflink_api.domain.audit import (
    ACTIONS_BY_CATEGORY,
    AUDIT_ACTION_CATEGORY,
    AUDIT_CATEGORIES,
    ENTITY_TYPE_CASH_JOURNAL,
    ENTITY_TYPE_CUSTOMER,
    ENTITY_TYPE_TERMINAL_DEVICE,
    ENTITY_TYPE_PAYMENT,
    ENTITY_TYPE_QUEUE_TICKET,
    ENTITY_TYPE_SALON,
    ENTITY_TYPE_SERVICE,
    AuditAction,
    AuditEntry,
    AuditLogEntry,
    validate_audit_log_filter,
)
from coiflink_api.domain.errors import InvalidAuditLogFilter


# ---------------------------------------------------------------------------
# AuditAction
# ---------------------------------------------------------------------------


class TestAuditAction:
    def test_service_created_value(self) -> None:
        assert AuditAction.SERVICE_CREATED == "SERVICE_CREATED"

    def test_service_updated_value(self) -> None:
        assert AuditAction.SERVICE_UPDATED == "SERVICE_UPDATED"

    def test_service_deactivated_value(self) -> None:
        assert AuditAction.SERVICE_DEACTIVATED == "SERVICE_DEACTIVATED"

    def test_service_reactivated_value(self) -> None:
        assert AuditAction.SERVICE_REACTIVATED == "SERVICE_REACTIVATED"

    def test_salon_updated_value(self) -> None:
        assert AuditAction.SALON_UPDATED == "SALON_UPDATED"

    def test_customer_created_value(self) -> None:
        assert AuditAction.CUSTOMER_CREATED == "CUSTOMER_CREATED"

    def test_customer_note_updated_value(self) -> None:
        assert AuditAction.CUSTOMER_NOTE_UPDATED == "CUSTOMER_NOTE_UPDATED"

    def test_customer_updated_value(self) -> None:
        assert AuditAction.CUSTOMER_UPDATED == "CUSTOMER_UPDATED"

    def test_payment_recorded_value(self) -> None:
        assert AuditAction.PAYMENT_RECORDED == "PAYMENT_RECORDED"

    def test_cash_adjusted_value(self) -> None:
        assert AuditAction.CASH_ADJUSTED == "CASH_ADJUSTED"

    def test_campaign_created_value(self) -> None:
        assert AuditAction.CAMPAIGN_CREATED == "CAMPAIGN_CREATED"

    def test_terminal_device_provisioned_value(self) -> None:
        assert AuditAction.TERMINAL_DEVICE_PROVISIONED == "TERMINAL_DEVICE_PROVISIONED"

    def test_terminal_device_revoked_value(self) -> None:
        assert AuditAction.TERMINAL_DEVICE_REVOKED == "TERMINAL_DEVICE_REVOKED"

    def test_queue_ticket_started_value(self) -> None:
        assert AuditAction.QUEUE_TICKET_STARTED == "QUEUE_TICKET_STARTED"

    def test_queue_ticket_completed_value(self) -> None:
        assert AuditAction.QUEUE_TICKET_COMPLETED == "QUEUE_TICKET_COMPLETED"

    def test_queue_ticket_cancelled_value(self) -> None:
        assert AuditAction.QUEUE_TICKET_CANCELLED == "QUEUE_TICKET_CANCELLED"

    def test_exactly_twenty_one_actions_defined(self) -> None:
        assert len(list(AuditAction)) == 21

    def test_values_are_strings(self) -> None:
        for action in AuditAction:
            assert isinstance(action.value, str)

    def test_string_comparison_works(self) -> None:
        assert AuditAction.SERVICE_CREATED.value == "SERVICE_CREATED"

    def test_all_expected_actions_present(self) -> None:
        names = {a.name for a in AuditAction}
        assert names == {
            "SERVICE_CREATED",
            "SERVICE_UPDATED",
            "SERVICE_DEACTIVATED",
            "SERVICE_REACTIVATED",
            "SALON_UPDATED",
            "CUSTOMER_CREATED",
            "CUSTOMER_NOTE_UPDATED",
            "CUSTOMER_UPDATED",
            "PAYMENT_RECORDED",
            "CASH_ADJUSTED",
            "CAMPAIGN_CREATED",
            "EMPLOYEE_CREATED",
            "EMPLOYEE_UPDATED",
            "EMPLOYEE_DEACTIVATED",
            "EMPLOYEE_REACTIVATED",
            "TERMINAL_DEVICE_PROVISIONED",
            "TERMINAL_DEVICE_REVOKED",
            "QUEUE_TICKET_STARTED",
            "QUEUE_TICKET_COMPLETED",
            "QUEUE_TICKET_SERVICES_UPDATED",
            "QUEUE_TICKET_CANCELLED",
        }


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------


class TestAuditEntry:
    _ACTOR = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    _SALON = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
    _ENTITY = uuid.UUID("cccccccc-0000-0000-0000-000000000003")

    def _make(self, **kwargs):  # type: ignore[no-untyped-def]
        defaults = dict(
            action=AuditAction.SERVICE_CREATED.value,
            actor_user_id=self._ACTOR,
            entity_type=ENTITY_TYPE_SERVICE,
            entity_id=self._ENTITY,
        )
        defaults.update(kwargs)
        return AuditEntry(**defaults)

    def test_construction_minimal(self) -> None:
        entry = self._make()
        assert entry.action == "SERVICE_CREATED"
        assert entry.actor_user_id == self._ACTOR
        assert entry.entity_type == ENTITY_TYPE_SERVICE
        assert entry.entity_id == self._ENTITY

    def test_salon_id_defaults_to_none(self) -> None:
        entry = self._make()
        assert entry.salon_id is None

    def test_metadata_defaults_to_empty_dict(self) -> None:
        entry = self._make()
        assert entry.metadata == {}

    def test_salon_id_can_be_set(self) -> None:
        entry = self._make(salon_id=self._SALON)
        assert entry.salon_id == self._SALON

    def test_metadata_can_carry_changed_fields(self) -> None:
        entry = self._make(metadata={"changed": ["price", "name"]})
        assert entry.metadata["changed"] == ["price", "name"]

    def test_entry_is_frozen(self) -> None:
        entry = self._make()
        import pytest
        with pytest.raises((AttributeError, TypeError)):
            entry.action = "OTHER"  # type: ignore[misc]

    def test_no_pii_field_names(self) -> None:
        entry = self._make()
        field_names = {f.name for f in entry.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        forbidden = {"phone", "email", "password", "address", "name", "token"}
        assert not field_names & forbidden, (
            f"AuditEntry contient des champs PII potentiels : {field_names & forbidden}"
        )

    def test_actor_user_id_is_opaque_uuid(self) -> None:
        entry = self._make()
        assert isinstance(entry.actor_user_id, uuid.UUID)

    def test_metadata_is_dict(self) -> None:
        entry = self._make(metadata={"changed": ["duration_minutes"]})
        assert isinstance(entry.metadata, dict)

    def test_metadata_does_not_contain_secret_keys(self) -> None:
        entry = self._make(metadata={"changed": ["price"]})
        forbidden_keys = {"token", "password", "secret", "hash"}
        actual_keys = set(entry.metadata.keys())
        assert not actual_keys & forbidden_keys


# ---------------------------------------------------------------------------
# ENTITY_TYPE_SERVICE
# ---------------------------------------------------------------------------


class TestEntityTypeService:
    def test_value_is_string(self) -> None:
        assert isinstance(ENTITY_TYPE_SERVICE, str)

    def test_value_is_service(self) -> None:
        assert ENTITY_TYPE_SERVICE == "service"


# ---------------------------------------------------------------------------
# ENTITY_TYPE_SALON
# ---------------------------------------------------------------------------


class TestEntityTypeSalon:
    def test_value_is_string(self) -> None:
        assert isinstance(ENTITY_TYPE_SALON, str)

    def test_value_is_salon(self) -> None:
        assert ENTITY_TYPE_SALON == "salon"


# ---------------------------------------------------------------------------
# ENTITY_TYPE_CUSTOMER (US-4.1, #28)
# ---------------------------------------------------------------------------


class TestEntityTypeCustomer:
    def test_value_is_string(self) -> None:
        assert isinstance(ENTITY_TYPE_CUSTOMER, str)

    def test_value_is_customer(self) -> None:
        assert ENTITY_TYPE_CUSTOMER == "customer"


# ---------------------------------------------------------------------------
# ENTITY_TYPE_PAYMENT / ENTITY_TYPE_CASH_JOURNAL (US-5.3, #34)
# ---------------------------------------------------------------------------


class TestEntityTypePayment:
    def test_value_is_string(self) -> None:
        assert isinstance(ENTITY_TYPE_PAYMENT, str)

    def test_value_is_payment(self) -> None:
        assert ENTITY_TYPE_PAYMENT == "payment"


class TestEntityTypeCashJournal:
    def test_value_is_string(self) -> None:
        assert isinstance(ENTITY_TYPE_CASH_JOURNAL, str)

    def test_value_is_cash_journal(self) -> None:
        assert ENTITY_TYPE_CASH_JOURNAL == "cash_journal"


# ---------------------------------------------------------------------------
# ENTITY_TYPE_TERMINAL_DEVICE (US-8.1, #155)
# ---------------------------------------------------------------------------


class TestEntityTypeTerminalDevice:
    def test_value_is_string(self) -> None:
        assert isinstance(ENTITY_TYPE_TERMINAL_DEVICE, str)

    def test_value_is_terminal_device(self) -> None:
        assert ENTITY_TYPE_TERMINAL_DEVICE == "terminal_device"


# ---------------------------------------------------------------------------
# ENTITY_TYPE_QUEUE_TICKET (US-8.3, #157)
# ---------------------------------------------------------------------------


class TestEntityTypeQueueTicket:
    def test_value_is_string(self) -> None:
        assert isinstance(ENTITY_TYPE_QUEUE_TICKET, str)

    def test_value_is_queue_ticket(self) -> None:
        assert ENTITY_TYPE_QUEUE_TICKET == "queue_ticket"


# ---------------------------------------------------------------------------
# AUDIT_ACTION_CATEGORY / ACTIONS_BY_CATEGORY (page « Journal d'audit »)
# ---------------------------------------------------------------------------


class TestAuditActionCategoryExhaustiveness:
    """Fige l'exhaustivité de la table action → catégorie (miroir matrice permissions).

    Une action absente de `AUDIT_ACTION_CATEGORY` est une **régression** : ce
    test échoue dès qu'une nouvelle valeur est ajoutée à `AuditAction` sans
    l'y catégoriser — jamais un défaut silencieux côté dépôt.
    """

    def test_every_action_has_a_category(self) -> None:
        missing = [a.value for a in AuditAction if a.value not in AUDIT_ACTION_CATEGORY]
        assert missing == [], f"Actions non catégorisées : {missing}"

    def test_no_extra_entries_beyond_defined_actions(self) -> None:
        action_values = {a.value for a in AuditAction}
        assert set(AUDIT_ACTION_CATEGORY.keys()) == action_values

    def test_every_category_value_is_closed(self) -> None:
        for category in AUDIT_ACTION_CATEGORY.values():
            assert category in AUDIT_CATEGORIES

    def test_seven_categories_defined(self) -> None:
        assert len(AUDIT_CATEGORIES) == 7

    def test_service_actions_are_prestations(self) -> None:
        for action in (
            AuditAction.SERVICE_CREATED,
            AuditAction.SERVICE_UPDATED,
            AuditAction.SERVICE_DEACTIVATED,
            AuditAction.SERVICE_REACTIVATED,
        ):
            assert AUDIT_ACTION_CATEGORY[action.value] == "prestations"

    def test_payment_and_cash_actions_are_paiements_caisse(self) -> None:
        assert AUDIT_ACTION_CATEGORY[AuditAction.PAYMENT_RECORDED.value] == "paiements_caisse"
        assert AUDIT_ACTION_CATEGORY[AuditAction.CASH_ADJUSTED.value] == "paiements_caisse"

    def test_customer_and_campaign_actions_are_clients(self) -> None:
        for action in (
            AuditAction.CUSTOMER_CREATED,
            AuditAction.CUSTOMER_NOTE_UPDATED,
            AuditAction.CUSTOMER_UPDATED,
            AuditAction.CAMPAIGN_CREATED,
        ):
            assert AUDIT_ACTION_CATEGORY[action.value] == "clients"

    def test_employee_actions_are_employes(self) -> None:
        for action in (
            AuditAction.EMPLOYEE_CREATED,
            AuditAction.EMPLOYEE_UPDATED,
            AuditAction.EMPLOYEE_DEACTIVATED,
            AuditAction.EMPLOYEE_REACTIVATED,
        ):
            assert AUDIT_ACTION_CATEGORY[action.value] == "employes"

    def test_terminal_device_actions_are_bornes(self) -> None:
        for action in (
            AuditAction.TERMINAL_DEVICE_PROVISIONED,
            AuditAction.TERMINAL_DEVICE_REVOKED,
        ):
            assert AUDIT_ACTION_CATEGORY[action.value] == "bornes"

    def test_queue_ticket_actions_are_file_attente(self) -> None:
        for action in (
            AuditAction.QUEUE_TICKET_STARTED,
            AuditAction.QUEUE_TICKET_COMPLETED,
            AuditAction.QUEUE_TICKET_SERVICES_UPDATED,
            AuditAction.QUEUE_TICKET_CANCELLED,
        ):
            assert AUDIT_ACTION_CATEGORY[action.value] == "file_attente"

    def test_salon_updated_is_salon(self) -> None:
        assert AUDIT_ACTION_CATEGORY[AuditAction.SALON_UPDATED.value] == "salon"


class TestActionsByCategory:
    def test_every_category_key_present(self) -> None:
        assert set(ACTIONS_BY_CATEGORY.keys()) == set(AUDIT_CATEGORIES)

    def test_union_of_all_categories_covers_every_action(self) -> None:
        all_actions = {a.value for a in AuditAction}
        union = {action for actions in ACTIONS_BY_CATEGORY.values() for action in actions}
        assert union == all_actions

    def test_categories_are_disjoint(self) -> None:
        seen: set[str] = set()
        for actions in ACTIONS_BY_CATEGORY.values():
            overlap = seen & set(actions)
            assert not overlap, f"Action(s) dans plusieurs catégories : {overlap}"
            seen |= set(actions)

    def test_prestations_actions_derived_correctly(self) -> None:
        assert set(ACTIONS_BY_CATEGORY["prestations"]) == {
            "SERVICE_CREATED",
            "SERVICE_UPDATED",
            "SERVICE_DEACTIVATED",
            "SERVICE_REACTIVATED",
        }


# ---------------------------------------------------------------------------
# AuditLogEntry (projection de lecture, page « Journal d'audit »)
# ---------------------------------------------------------------------------


class TestAuditLogEntry:
    _ID = uuid.UUID("dddddddd-0000-0000-0000-000000000004")
    _ACTOR = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    _ENTITY = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
    _CREATED_AT = datetime.datetime(2026, 8, 7, 10, 0, tzinfo=datetime.timezone.utc)

    def _make(self, **kwargs):  # type: ignore[no-untyped-def]
        defaults = dict(
            id=self._ID,
            action=AuditAction.SERVICE_UPDATED.value,
            category="prestations",
            entity_type=ENTITY_TYPE_SERVICE,
            entity_id=self._ENTITY,
            actor_name="Awa Koné",
            created_at=self._CREATED_AT,
        )
        defaults.update(kwargs)
        return AuditLogEntry(**defaults)

    def test_construction(self) -> None:
        entry = self._make()
        assert entry.id == self._ID
        assert entry.action == "SERVICE_UPDATED"
        assert entry.category == "prestations"
        assert entry.actor_name == "Awa Koné"
        assert entry.created_at == self._CREATED_AT

    def test_is_frozen(self) -> None:
        entry = self._make()
        with pytest.raises((AttributeError, TypeError)):
            entry.actor_name = "Autre"  # type: ignore[misc]

    def test_no_metadata_field(self) -> None:
        """`AuditLogEntry` n'expose jamais `metadata` — aucune valeur à exposer."""
        field_names = {
            f.name for f in AuditLogEntry.__dataclass_fields__.values()  # type: ignore[attr-defined]
        }
        assert "metadata" not in field_names


# ---------------------------------------------------------------------------
# validate_audit_log_filter
# ---------------------------------------------------------------------------


class TestValidateAuditLogFilter:
    def test_no_criteria_returns_unconstrained_filter(self) -> None:
        result = validate_audit_log_filter()
        assert result.date_from is None
        assert result.date_to is None
        assert result.category is None

    def test_valid_date_range_accepted(self) -> None:
        result = validate_audit_log_filter(
            date_from=datetime.date(2026, 8, 1), date_to=datetime.date(2026, 8, 7)
        )
        assert result.date_from == datetime.date(2026, 8, 1)
        assert result.date_to == datetime.date(2026, 8, 7)

    def test_date_from_after_date_to_raises(self) -> None:
        with pytest.raises(InvalidAuditLogFilter):
            validate_audit_log_filter(
                date_from=datetime.date(2026, 8, 7), date_to=datetime.date(2026, 8, 1)
            )

    def test_equal_dates_accepted(self) -> None:
        result = validate_audit_log_filter(
            date_from=datetime.date(2026, 8, 7), date_to=datetime.date(2026, 8, 7)
        )
        assert result.date_from == result.date_to == datetime.date(2026, 8, 7)

    def test_valid_category_accepted(self) -> None:
        result = validate_audit_log_filter(category="prestations")
        assert result.category == "prestations"

    def test_unknown_category_raises(self) -> None:
        with pytest.raises(InvalidAuditLogFilter):
            validate_audit_log_filter(category="not-a-real-category")

    def test_empty_category_string_treated_as_none(self) -> None:
        result = validate_audit_log_filter(category="")
        assert result.category is None

    def test_whitespace_only_category_treated_as_none(self) -> None:
        result = validate_audit_log_filter(category="   ")
        assert result.category is None

    def test_error_message_does_not_repeat_invalid_category(self) -> None:
        try:
            validate_audit_log_filter(category="super-secret-category-xyz")
        except InvalidAuditLogFilter as exc:
            assert "super-secret-category-xyz" not in str(exc)
        else:
            pytest.fail("InvalidAuditLogFilter attendue")

    def test_all_seven_categories_individually_valid(self) -> None:
        for category in AUDIT_CATEGORIES:
            result = validate_audit_log_filter(category=category)
            assert result.category == category
