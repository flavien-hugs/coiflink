"""Tests unitaires — règles de domaine « rendez-vous » (US-3.7, #21).

Couvre `domain/appointment.py` sans I/O ni base de données.

Cas traités :
- `require_services` : tuple vide → `AppointmentServiceRequired`, non-vide → OK ;
- `validate_booking_window` : `end <= start` → `SlotUnavailable`, `end > start` → OK ;
- `compute_end_time` : calcul normal, somme multi-prestations, franchissement minuit →
  `SlotUnavailable` ;
- Invariants des dataclasses (`BookedService`, `AppointmentToCreate`, `Appointment`) :
  champs préservés, valeurs par défaut, immutabilité.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

import pytest

from coiflink_api.domain.appointment import (
    ALLOWED_STATUS_TRANSITIONS,
    Appointment,
    AppointmentToCreate,
    AppointmentUpdate,
    BookedService,
    CLIENT_CANCELLABLE_STATUSES,
    CLIENT_MODIFIABLE_STATUSES,
    MAX_CANCELLATION_REASON_LENGTH,
    REVENUE_STATUSES,
    TERMINAL_STATUSES,
    compute_end_time,
    counts_towards_revenue,
    is_client_cancellable,
    is_client_modifiable,
    is_valid_transition,
    normalize_cancellation_reason,
    require_services,
    validate_booking_window,
)
from coiflink_api.domain.errors import AppointmentServiceRequired, SlotUnavailable

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_CLIENT_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_HAIRDRESSER_ID = uuid.UUID("33333333-0000-0000-0000-000000000003")
_SERVICE_ID = uuid.UUID("44444444-0000-0000-0000-000000000004")
_PRICE = decimal.Decimal("5000.00")
_DATE = datetime.date(2026, 8, 3)
_START = datetime.time(9, 0)
_END = datetime.time(10, 0)


# ---------------------------------------------------------------------------
# require_services
# ---------------------------------------------------------------------------


class TestRequireServices:
    def test_empty_tuple_raises(self) -> None:
        with pytest.raises(AppointmentServiceRequired):
            require_services(())

    def test_single_service_accepted(self) -> None:
        service = BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE)
        require_services((service,))  # ne doit pas lever

    def test_multiple_services_accepted(self) -> None:
        s1 = BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE)
        s2 = BookedService(service_id=uuid.uuid4(), price_at_booking=_PRICE)
        require_services((s1, s2))  # ne doit pas lever

    def test_error_message_is_neutral(self) -> None:
        with pytest.raises(AppointmentServiceRequired) as exc_info:
            require_services(())
        assert exc_info.value.args[0]  # message non vide
        assert "prestation" in exc_info.value.args[0].lower()


# ---------------------------------------------------------------------------
# validate_booking_window
# ---------------------------------------------------------------------------


class TestValidateBookingWindow:
    def test_end_after_start_accepted(self) -> None:
        validate_booking_window(_START, _END)  # ne doit pas lever

    def test_end_equal_start_raises(self) -> None:
        with pytest.raises(SlotUnavailable):
            validate_booking_window(_START, _START)

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(SlotUnavailable):
            validate_booking_window(_END, _START)

    def test_one_minute_window_accepted(self) -> None:
        validate_booking_window(datetime.time(9, 0), datetime.time(9, 1))  # ne doit pas lever


# ---------------------------------------------------------------------------
# compute_end_time
# ---------------------------------------------------------------------------


class TestComputeEndTime:
    def test_single_service_60_minutes(self) -> None:
        end = compute_end_time(datetime.time(9, 0), 60)
        assert end == datetime.time(10, 0)

    def test_multi_service_sum_of_durations(self) -> None:
        # 30 + 45 = 75 minutes
        end = compute_end_time(datetime.time(9, 0), 75)
        assert end == datetime.time(10, 15)

    def test_midnight_overflow_raises_slot_unavailable(self) -> None:
        # 23:30 + 60 min = 00:30 (lendemain) → non modélisable
        with pytest.raises(SlotUnavailable):
            compute_end_time(datetime.time(23, 30), 60)

    def test_exactly_at_1440_raises(self) -> None:
        with pytest.raises(SlotUnavailable):
            compute_end_time(datetime.time(0, 0), 24 * 60)

    def test_result_just_before_midnight(self) -> None:
        end = compute_end_time(datetime.time(23, 0), 59)
        assert end == datetime.time(23, 59)

    def test_zero_duration_same_as_start(self) -> None:
        # 0 minutes = heure identique (cas dégénéré admis par compute_end_time)
        end = compute_end_time(datetime.time(10, 0), 0)
        assert end == datetime.time(10, 0)


# ---------------------------------------------------------------------------
# BookedService — invariants dataclass
# ---------------------------------------------------------------------------


class TestBookedService:
    def test_fields_preserved(self) -> None:
        service = BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE)
        assert service.service_id == _SERVICE_ID
        assert service.price_at_booking == _PRICE

    def test_immutable(self) -> None:
        service = BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE)
        with pytest.raises((AttributeError, TypeError)):
            service.price_at_booking = decimal.Decimal("0.00")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AppointmentToCreate — invariants dataclass
# ---------------------------------------------------------------------------


class TestAppointmentToCreate:
    def _make(self) -> AppointmentToCreate:
        return AppointmentToCreate(
            salon_id=_SALON_ID,
            client_id=_CLIENT_ID,
            hairdresser_id=_HAIRDRESSER_ID,
            date=_DATE,
            start_time=_START,
            end_time=_END,
            services=(BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE),),
        )

    def test_fields_preserved(self) -> None:
        appt = self._make()
        assert appt.salon_id == _SALON_ID
        assert appt.client_id == _CLIENT_ID
        assert appt.hairdresser_id == _HAIRDRESSER_ID

    def test_default_status_is_pending(self) -> None:
        appt = self._make()
        assert appt.status == "PENDING"

    def test_default_client_note_is_none(self) -> None:
        appt = self._make()
        assert appt.client_note is None

    def test_hairdresser_id_optional(self) -> None:
        appt = AppointmentToCreate(
            salon_id=_SALON_ID,
            client_id=_CLIENT_ID,
            hairdresser_id=None,
            date=_DATE,
            start_time=_START,
            end_time=_END,
            services=(BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE),),
        )
        assert appt.hairdresser_id is None


# ---------------------------------------------------------------------------
# Appointment — invariants dataclass (entité de lecture)
# ---------------------------------------------------------------------------


class TestAppointment:
    def _make(self, *, hairdresser_id: uuid.UUID | None = _HAIRDRESSER_ID) -> Appointment:
        return Appointment(
            id=_SALON_ID,  # uuid quelconque pour l'id
            salon_id=_SALON_ID,
            client_id=_CLIENT_ID,
            hairdresser_id=hairdresser_id,
            date=_DATE,
            start_time=_START,
            end_time=_END,
            status="PENDING",
            client_note=None,
            created_at=datetime.datetime(2026, 1, 1),
        )

    def test_fields_preserved(self) -> None:
        appt = self._make()
        assert appt.salon_id == _SALON_ID
        assert appt.client_id == _CLIENT_ID
        assert appt.hairdresser_id == _HAIRDRESSER_ID
        assert appt.date == _DATE
        assert appt.start_time == _START
        assert appt.end_time == _END
        assert appt.status == "PENDING"
        assert appt.client_note is None

    def test_services_default_empty_tuple(self) -> None:
        appt = self._make()
        assert appt.services == ()
        assert isinstance(appt.services, tuple)

    def test_hairdresser_id_optional(self) -> None:
        appt = self._make(hairdresser_id=None)
        assert appt.hairdresser_id is None

    def test_immutable(self) -> None:
        appt = self._make()
        with pytest.raises((AttributeError, TypeError)):
            appt.status = "CONFIRMED"  # type: ignore[misc]

    def test_services_stored_as_tuple(self) -> None:
        svc = BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE)
        appt = Appointment(
            id=_SALON_ID,
            salon_id=_SALON_ID,
            client_id=_CLIENT_ID,
            hairdresser_id=None,
            date=_DATE,
            start_time=_START,
            end_time=_END,
            status="PENDING",
            client_note="Note.",
            created_at=datetime.datetime(2026, 1, 1),
            services=(svc,),
        )
        assert len(appt.services) == 1
        assert appt.services[0].service_id == _SERVICE_ID


# ---------------------------------------------------------------------------
# is_client_modifiable (US-3.2, #23)
# ---------------------------------------------------------------------------


class TestIsClientModifiable:
    """Règle de domaine §8.1 : un RDV terminé/terminal est verrouillé côté client."""

    def test_pending_is_modifiable(self) -> None:
        assert is_client_modifiable("PENDING") is True

    def test_confirmed_is_modifiable(self) -> None:
        assert is_client_modifiable("CONFIRMED") is True

    def test_completed_is_not_modifiable(self) -> None:
        assert is_client_modifiable("COMPLETED") is False

    def test_cancelled_is_not_modifiable(self) -> None:
        assert is_client_modifiable("CANCELLED") is False

    def test_no_show_is_not_modifiable(self) -> None:
        assert is_client_modifiable("NO_SHOW") is False

    def test_unknown_status_is_not_modifiable(self) -> None:
        # Un statut inconnu (évolution serveur) est refusé par construction.
        assert is_client_modifiable("FUTURE_STATUS") is False

    def test_empty_string_is_not_modifiable(self) -> None:
        assert is_client_modifiable("") is False

    def test_lowercase_pending_not_modifiable(self) -> None:
        # Les valeurs enum sont stockées en MAJUSCULES : la comparaison est stricte.
        assert is_client_modifiable("pending") is False

    def test_deny_by_default_on_arbitrary_value(self) -> None:
        assert is_client_modifiable("WHATEVER") is False


# ---------------------------------------------------------------------------
# CLIENT_MODIFIABLE_STATUSES (US-3.2, #23)
# ---------------------------------------------------------------------------


class TestClientModifiableStatuses:
    def test_contains_pending(self) -> None:
        assert "PENDING" in CLIENT_MODIFIABLE_STATUSES

    def test_contains_confirmed(self) -> None:
        assert "CONFIRMED" in CLIENT_MODIFIABLE_STATUSES

    def test_does_not_contain_completed(self) -> None:
        assert "COMPLETED" not in CLIENT_MODIFIABLE_STATUSES

    def test_does_not_contain_cancelled(self) -> None:
        assert "CANCELLED" not in CLIENT_MODIFIABLE_STATUSES

    def test_does_not_contain_no_show(self) -> None:
        assert "NO_SHOW" not in CLIENT_MODIFIABLE_STATUSES

    def test_is_tuple_type(self) -> None:
        assert isinstance(CLIENT_MODIFIABLE_STATUSES, tuple)

    def test_exactly_two_statuses(self) -> None:
        assert len(CLIENT_MODIFIABLE_STATUSES) == 2


# ---------------------------------------------------------------------------
# AppointmentUpdate — VO re-planification (US-3.2, #23)
# ---------------------------------------------------------------------------


class TestAppointmentUpdate:
    """Valeur objet portant la cible d'une modification (sémantique *replace*)."""

    def _make(self) -> AppointmentUpdate:
        return AppointmentUpdate(
            date=_DATE,
            start_time=_START,
            end_time=_END,
            hairdresser_id=_HAIRDRESSER_ID,
            client_note="Note.",
            services=(BookedService(service_id=_SERVICE_ID, price_at_booking=_PRICE),),
        )

    def test_fields_preserved(self) -> None:
        update = self._make()
        assert update.date == _DATE
        assert update.start_time == _START
        assert update.end_time == _END
        assert update.hairdresser_id == _HAIRDRESSER_ID
        assert update.client_note == "Note."
        assert len(update.services) == 1
        assert update.services[0].service_id == _SERVICE_ID

    def test_hairdresser_id_optional(self) -> None:
        update = AppointmentUpdate(
            date=_DATE,
            start_time=_START,
            end_time=_END,
            hairdresser_id=None,
            client_note=None,
            services=(),
        )
        assert update.hairdresser_id is None
        assert update.client_note is None
        assert update.services == ()

    def test_immutable(self) -> None:
        update = self._make()
        with pytest.raises((AttributeError, TypeError)):
            update.date = datetime.date(2099, 1, 1)  # type: ignore[misc]

    def test_no_salon_id_field(self) -> None:
        # anti-élévation §11.2 : `AppointmentUpdate` ne porte jamais `salon_id`.
        update = self._make()
        assert not hasattr(update, "salon_id")

    def test_no_client_id_field(self) -> None:
        # anti-élévation §11.2 : `AppointmentUpdate` ne porte jamais `client_id`.
        update = self._make()
        assert not hasattr(update, "client_id")

    def test_no_status_field(self) -> None:
        # Le statut reste inchangé lors de la modification (client ne le fixe pas).
        update = self._make()
        assert not hasattr(update, "status")


# ---------------------------------------------------------------------------
# is_client_cancellable (US-3.3, #24)
# ---------------------------------------------------------------------------


class TestIsClientCancellable:
    """Règle de domaine §8.1 : un RDV terminé/terminal est verrouillé pour l'annulation."""

    def test_pending_is_cancellable(self) -> None:
        assert is_client_cancellable("PENDING") is True

    def test_confirmed_is_cancellable(self) -> None:
        assert is_client_cancellable("CONFIRMED") is True

    def test_completed_is_not_cancellable(self) -> None:
        assert is_client_cancellable("COMPLETED") is False

    def test_cancelled_is_not_cancellable(self) -> None:
        # Un RDV déjà annulé est terminal : idempotence refusée (→ 409).
        assert is_client_cancellable("CANCELLED") is False

    def test_no_show_is_not_cancellable(self) -> None:
        assert is_client_cancellable("NO_SHOW") is False

    def test_unknown_status_is_not_cancellable(self) -> None:
        assert is_client_cancellable("FUTURE_STATUS") is False

    def test_empty_string_is_not_cancellable(self) -> None:
        assert is_client_cancellable("") is False

    def test_lowercase_pending_not_cancellable(self) -> None:
        # Les valeurs enum sont stockées en MAJUSCULES : comparaison stricte.
        assert is_client_cancellable("pending") is False

    def test_deny_by_default_on_arbitrary_value(self) -> None:
        assert is_client_cancellable("WHATEVER") is False


# ---------------------------------------------------------------------------
# CLIENT_CANCELLABLE_STATUSES (US-3.3, #24)
# ---------------------------------------------------------------------------


class TestClientCancellableStatuses:
    def test_contains_pending(self) -> None:
        assert "PENDING" in CLIENT_CANCELLABLE_STATUSES

    def test_contains_confirmed(self) -> None:
        assert "CONFIRMED" in CLIENT_CANCELLABLE_STATUSES

    def test_does_not_contain_completed(self) -> None:
        assert "COMPLETED" not in CLIENT_CANCELLABLE_STATUSES

    def test_does_not_contain_cancelled(self) -> None:
        assert "CANCELLED" not in CLIENT_CANCELLABLE_STATUSES

    def test_does_not_contain_no_show(self) -> None:
        assert "NO_SHOW" not in CLIENT_CANCELLABLE_STATUSES

    def test_is_tuple_type(self) -> None:
        assert isinstance(CLIENT_CANCELLABLE_STATUSES, tuple)

    def test_exactly_two_statuses(self) -> None:
        assert len(CLIENT_CANCELLABLE_STATUSES) == 2


# ---------------------------------------------------------------------------
# normalize_cancellation_reason (US-3.3, #24)
# ---------------------------------------------------------------------------


class TestNormalizeCancellationReason:
    def test_none_returns_none(self) -> None:
        assert normalize_cancellation_reason(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_cancellation_reason("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_cancellation_reason("   ") is None

    def test_newline_only_returns_none(self) -> None:
        assert normalize_cancellation_reason("\n\t") is None

    def test_trims_leading_and_trailing_spaces(self) -> None:
        result = normalize_cancellation_reason("  empêchement  ")
        assert result == "empêchement"

    def test_non_empty_reason_returned_as_is(self) -> None:
        assert normalize_cancellation_reason("Changement de plan.") == "Changement de plan."

    def test_truncates_at_max_length(self) -> None:
        long = "x" * (MAX_CANCELLATION_REASON_LENGTH + 100)
        result = normalize_cancellation_reason(long)
        assert result is not None
        assert len(result) == MAX_CANCELLATION_REASON_LENGTH

    def test_exactly_max_length_not_truncated(self) -> None:
        exact = "x" * MAX_CANCELLATION_REASON_LENGTH
        result = normalize_cancellation_reason(exact)
        assert result == exact

    def test_one_below_max_length_not_truncated(self) -> None:
        almost = "x" * (MAX_CANCELLATION_REASON_LENGTH - 1)
        result = normalize_cancellation_reason(almost)
        assert result == almost

    def test_motif_with_spaces_truncation_still_trims(self) -> None:
        # Même un motif long est d'abord trimmé puis tronqué.
        padded = "  " + "y" * (MAX_CANCELLATION_REASON_LENGTH + 50) + "  "
        result = normalize_cancellation_reason(padded)
        assert result is not None
        assert not result.startswith(" ")
        assert not result.endswith(" ")
        assert len(result) == MAX_CANCELLATION_REASON_LENGTH


# ---------------------------------------------------------------------------
# counts_towards_revenue / REVENUE_STATUSES (US-3.3, #24)
# ---------------------------------------------------------------------------


class TestCountsTowardsRevenue:
    """Invariant §8.1 : CANCELLED n'est jamais comptabilisé dans le CA."""

    def test_completed_counts_towards_revenue(self) -> None:
        assert counts_towards_revenue("COMPLETED") is True

    def test_cancelled_does_not_count(self) -> None:
        assert counts_towards_revenue("CANCELLED") is False

    def test_pending_does_not_count(self) -> None:
        assert counts_towards_revenue("PENDING") is False

    def test_confirmed_does_not_count(self) -> None:
        assert counts_towards_revenue("CONFIRMED") is False

    def test_no_show_does_not_count(self) -> None:
        assert counts_towards_revenue("NO_SHOW") is False

    def test_unknown_status_does_not_count(self) -> None:
        assert counts_towards_revenue("FUTURE_STATUS") is False

    def test_empty_string_does_not_count(self) -> None:
        assert counts_towards_revenue("") is False


class TestRevenueStatuses:
    def test_contains_completed(self) -> None:
        assert "COMPLETED" in REVENUE_STATUSES

    def test_does_not_contain_cancelled(self) -> None:
        assert "CANCELLED" not in REVENUE_STATUSES

    def test_does_not_contain_pending(self) -> None:
        assert "PENDING" not in REVENUE_STATUSES

    def test_does_not_contain_confirmed(self) -> None:
        assert "CONFIRMED" not in REVENUE_STATUSES

    def test_does_not_contain_no_show(self) -> None:
        assert "NO_SHOW" not in REVENUE_STATUSES

    def test_is_tuple_type(self) -> None:
        assert isinstance(REVENUE_STATUSES, tuple)


# ---------------------------------------------------------------------------
# TERMINAL_STATUSES (US-3.4, #25)
# ---------------------------------------------------------------------------


class TestTerminalStatuses:
    """Statuts sans aucune transition sortante — verrouillés (§8.1, #25)."""

    def test_is_frozenset(self) -> None:
        assert isinstance(TERMINAL_STATUSES, frozenset)

    def test_contains_cancelled(self) -> None:
        assert "CANCELLED" in TERMINAL_STATUSES

    def test_contains_completed(self) -> None:
        assert "COMPLETED" in TERMINAL_STATUSES

    def test_contains_no_show(self) -> None:
        assert "NO_SHOW" in TERMINAL_STATUSES

    def test_exactly_three_statuses(self) -> None:
        assert len(TERMINAL_STATUSES) == 3

    def test_pending_not_terminal(self) -> None:
        assert "PENDING" not in TERMINAL_STATUSES

    def test_confirmed_not_terminal(self) -> None:
        assert "CONFIRMED" not in TERMINAL_STATUSES

    def test_terminal_statuses_match_empty_transitions(self) -> None:
        # Invariant : TERMINAL_STATUSES doit coïncider avec les clés de
        # ALLOWED_STATUS_TRANSITIONS dont la valeur est un frozenset vide.
        from_table = frozenset(
            k for k, v in ALLOWED_STATUS_TRANSITIONS.items() if not v
        )
        assert TERMINAL_STATUSES == from_table


# ---------------------------------------------------------------------------
# ALLOWED_STATUS_TRANSITIONS (US-3.4, #25)
# ---------------------------------------------------------------------------


class TestAllowedStatusTransitions:
    """Structure de la table des transitions gérant (§8.1, #25)."""

    def test_is_dict(self) -> None:
        assert isinstance(ALLOWED_STATUS_TRANSITIONS, dict)

    def test_all_five_statuses_have_entry(self) -> None:
        expected = {"PENDING", "CONFIRMED", "CANCELLED", "COMPLETED", "NO_SHOW"}
        assert set(ALLOWED_STATUS_TRANSITIONS.keys()) == expected

    def test_values_are_frozensets(self) -> None:
        for v in ALLOWED_STATUS_TRANSITIONS.values():
            assert isinstance(v, frozenset)

    def test_pending_transitions(self) -> None:
        assert ALLOWED_STATUS_TRANSITIONS["PENDING"] == frozenset(
            {"CONFIRMED", "CANCELLED", "NO_SHOW"}
        )

    def test_confirmed_transitions(self) -> None:
        assert ALLOWED_STATUS_TRANSITIONS["CONFIRMED"] == frozenset(
            {"COMPLETED", "CANCELLED", "NO_SHOW"}
        )

    def test_cancelled_is_terminal(self) -> None:
        assert ALLOWED_STATUS_TRANSITIONS["CANCELLED"] == frozenset()

    def test_completed_is_terminal(self) -> None:
        assert ALLOWED_STATUS_TRANSITIONS["COMPLETED"] == frozenset()

    def test_no_show_is_terminal(self) -> None:
        assert ALLOWED_STATUS_TRANSITIONS["NO_SHOW"] == frozenset()

    def test_pending_cannot_reach_completed_directly(self) -> None:
        assert "COMPLETED" not in ALLOWED_STATUS_TRANSITIONS["PENDING"]

    def test_confirmed_cannot_reach_pending(self) -> None:
        assert "PENDING" not in ALLOWED_STATUS_TRANSITIONS["CONFIRMED"]


# ---------------------------------------------------------------------------
# is_valid_transition (US-3.4, #25)
# ---------------------------------------------------------------------------


class TestIsValidTransition:
    """Machine à états gérant : deny-by-default (§8.1, #25).

    Chaque transition **autorisée** renvoie `True` ; toute autre combinaison
    (terminale, identité, interdite, statut inconnu) renvoie `False`.
    """

    # --- Transitions autorisées -------------------------------------------

    def test_pending_to_confirmed(self) -> None:
        assert is_valid_transition("PENDING", "CONFIRMED") is True

    def test_pending_to_cancelled(self) -> None:
        assert is_valid_transition("PENDING", "CANCELLED") is True

    def test_pending_to_no_show(self) -> None:
        assert is_valid_transition("PENDING", "NO_SHOW") is True

    def test_confirmed_to_completed(self) -> None:
        assert is_valid_transition("CONFIRMED", "COMPLETED") is True

    def test_confirmed_to_cancelled(self) -> None:
        assert is_valid_transition("CONFIRMED", "CANCELLED") is True

    def test_confirmed_to_no_show(self) -> None:
        assert is_valid_transition("CONFIRMED", "NO_SHOW") is True

    # --- États terminaux verrouillés (§8.1) --------------------------------

    def test_cancelled_to_pending_is_forbidden(self) -> None:
        assert is_valid_transition("CANCELLED", "PENDING") is False

    def test_cancelled_to_confirmed_is_forbidden(self) -> None:
        assert is_valid_transition("CANCELLED", "CONFIRMED") is False

    def test_cancelled_to_completed_is_forbidden(self) -> None:
        assert is_valid_transition("CANCELLED", "COMPLETED") is False

    def test_cancelled_to_no_show_is_forbidden(self) -> None:
        assert is_valid_transition("CANCELLED", "NO_SHOW") is False

    def test_completed_to_pending_is_forbidden(self) -> None:
        assert is_valid_transition("COMPLETED", "PENDING") is False

    def test_completed_to_confirmed_is_forbidden(self) -> None:
        assert is_valid_transition("COMPLETED", "CONFIRMED") is False

    def test_no_show_to_pending_is_forbidden(self) -> None:
        assert is_valid_transition("NO_SHOW", "PENDING") is False

    def test_no_show_to_confirmed_is_forbidden(self) -> None:
        assert is_valid_transition("NO_SHOW", "CONFIRMED") is False

    # --- Identité refusée (pas de no-op silencieux, deny-by-default) ------

    def test_pending_to_pending_is_identity(self) -> None:
        assert is_valid_transition("PENDING", "PENDING") is False

    def test_confirmed_to_confirmed_is_identity(self) -> None:
        assert is_valid_transition("CONFIRMED", "CONFIRMED") is False

    def test_cancelled_to_cancelled_is_identity(self) -> None:
        assert is_valid_transition("CANCELLED", "CANCELLED") is False

    def test_completed_to_completed_is_identity(self) -> None:
        assert is_valid_transition("COMPLETED", "COMPLETED") is False

    def test_no_show_to_no_show_is_identity(self) -> None:
        assert is_valid_transition("NO_SHOW", "NO_SHOW") is False

    # --- Transitions interdites (non listées dans la table) ---------------

    def test_pending_to_completed_is_forbidden(self) -> None:
        # Il faut d'abord confirmer (PENDING → CONFIRMED → COMPLETED).
        assert is_valid_transition("PENDING", "COMPLETED") is False

    def test_confirmed_to_pending_is_forbidden(self) -> None:
        # Pas de retour arrière au MVP (deny-by-default).
        assert is_valid_transition("CONFIRMED", "PENDING") is False

    # --- Statuts inconnus : refus systématique (deny-by-default) ----------

    def test_unknown_current_returns_false(self) -> None:
        assert is_valid_transition("UNKNOWN", "CONFIRMED") is False

    def test_unknown_target_returns_false(self) -> None:
        assert is_valid_transition("PENDING", "UNKNOWN") is False

    def test_empty_string_current_returns_false(self) -> None:
        assert is_valid_transition("", "CONFIRMED") is False

    def test_empty_string_target_returns_false(self) -> None:
        assert is_valid_transition("PENDING", "") is False

    def test_lowercase_values_return_false(self) -> None:
        # Valeurs stockées en MAJUSCULES (source de vérité du CHECK SQL).
        assert is_valid_transition("pending", "confirmed") is False

    def test_both_unknown_returns_false(self) -> None:
        assert is_valid_transition("FUTURE_FROM", "FUTURE_TO") is False
