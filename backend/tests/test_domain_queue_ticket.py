"""Tests unitaires — domaine `queue_ticket` (US-8.3, #157).

Couvre (aucune I/O, domaine pur) :
- `estimate_wait_minutes` : position nulle, position croissante, aucune coiffeuse
  active (jamais de `ZeroDivisionError`), arrondi (jamais une troncature), durée
  nulle, cas dégénérés combinés.
- Machine à états `can_transition` / `assert_transition` : table de vérité complète
  (5 statuts, toutes les transitions autorisées et refusées).
- `validate_service_ids` : tuple vide → `InvalidQueueTicketServices` ; non-vide → ok.
- Constantes : `QUEUE_TICKET_STATUSES`, `QUEUE_TICKET_ACTIVE_STATUSES`,
  `QUEUE_TICKET_PENDING_STATUSES`, `DEFAULT_WAIT_MINUTES_NO_STAFF`.
"""

from __future__ import annotations

import uuid

import pytest

from coiflink_api.domain.errors import (
    InvalidQueueTicketServices,
    InvalidQueueTicketTransition,
)
from coiflink_api.domain.queue_ticket import (
    ALLOWED_QUEUE_TICKET_TRANSITIONS,
    DEFAULT_WAIT_MINUTES_NO_STAFF,
    QUEUE_TICKET_ACTIVE_STATUSES,
    QUEUE_TICKET_PENDING_STATUSES,
    QUEUE_TICKET_STATUSES,
    assert_transition,
    can_transition,
    estimate_wait_minutes,
    validate_service_ids,
)


# ---------------------------------------------------------------------------
# estimate_wait_minutes
# ---------------------------------------------------------------------------


class TestEstimateWaitMinutes:
    def test_position_zero_returns_zero(self) -> None:
        result = estimate_wait_minutes(
            position=0, average_service_minutes=30.0, active_hairdresser_count=2
        )
        assert result == 0

    def test_negative_position_returns_zero(self) -> None:
        result = estimate_wait_minutes(
            position=-1, average_service_minutes=30.0, active_hairdresser_count=2
        )
        assert result == 0

    def test_no_active_hairdresser_returns_fallback_constant(self) -> None:
        result = estimate_wait_minutes(
            position=5, average_service_minutes=30.0, active_hairdresser_count=0
        )
        assert result == DEFAULT_WAIT_MINUTES_NO_STAFF

    def test_no_active_hairdresser_never_raises_zero_division(self) -> None:
        # Régression : un salon sans coiffeuse active ne doit jamais produire
        # ZeroDivisionError — le filet explicite retourne la constante documentée.
        result = estimate_wait_minutes(
            position=1, average_service_minutes=20.0, active_hairdresser_count=0
        )
        assert isinstance(result, int)
        assert result == DEFAULT_WAIT_MINUTES_NO_STAFF

    def test_negative_hairdresser_count_treated_as_zero_staff(self) -> None:
        result = estimate_wait_minutes(
            position=2, average_service_minutes=10.0, active_hairdresser_count=-1
        )
        assert result == DEFAULT_WAIT_MINUTES_NO_STAFF

    def test_zero_average_service_minutes_returns_zero(self) -> None:
        result = estimate_wait_minutes(
            position=3, average_service_minutes=0.0, active_hairdresser_count=2
        )
        assert result == 0

    def test_negative_average_service_minutes_returns_zero(self) -> None:
        result = estimate_wait_minutes(
            position=3, average_service_minutes=-5.0, active_hairdresser_count=2
        )
        assert result == 0

    def test_nominal_single_position_one_hairdresser(self) -> None:
        # 1 ticket devant × 30 min / 1 coiffeuse = 30 min
        result = estimate_wait_minutes(
            position=1, average_service_minutes=30.0, active_hairdresser_count=1
        )
        assert result == 30

    def test_nominal_two_positions_two_hairdressers(self) -> None:
        # 2 tickets × 30 min / 2 coiffeuses = 30 min
        result = estimate_wait_minutes(
            position=2, average_service_minutes=30.0, active_hairdresser_count=2
        )
        assert result == 30

    def test_wait_increases_with_position(self) -> None:
        params = dict(average_service_minutes=20.0, active_hairdresser_count=2)
        w1 = estimate_wait_minutes(position=1, **params)
        w3 = estimate_wait_minutes(position=3, **params)
        w6 = estimate_wait_minutes(position=6, **params)
        assert w1 < w3 < w6

    def test_rounding_not_truncation(self) -> None:
        # 1 ticket × 5 min / 3 coiffeuses = 1.666… → round → 2 (jamais troncature = 1)
        result = estimate_wait_minutes(
            position=1, average_service_minutes=5.0, active_hairdresser_count=3
        )
        assert result == 2

    def test_result_is_always_int(self) -> None:
        result = estimate_wait_minutes(
            position=2, average_service_minutes=7.5, active_hairdresser_count=3
        )
        assert isinstance(result, int)

    def test_result_is_always_non_negative(self) -> None:
        result = estimate_wait_minutes(
            position=0, average_service_minutes=30.0, active_hairdresser_count=1
        )
        assert result >= 0

    def test_default_wait_minutes_no_staff_is_positive_int(self) -> None:
        assert isinstance(DEFAULT_WAIT_MINUTES_NO_STAFF, int)
        assert DEFAULT_WAIT_MINUTES_NO_STAFF > 0


# ---------------------------------------------------------------------------
# Machine à états : can_transition / assert_transition
# ---------------------------------------------------------------------------


class TestCanTransition:
    """Vérification de la table de vérité complète."""

    # --- Transitions autorisées ---

    def test_waiting_to_called(self) -> None:
        assert can_transition("waiting", "called") is True

    def test_waiting_to_in_progress(self) -> None:
        # Prise en charge directe (walk-in sans appel intermédiaire).
        assert can_transition("waiting", "in_progress") is True

    def test_waiting_to_expired(self) -> None:
        assert can_transition("waiting", "expired") is True

    def test_called_to_in_progress(self) -> None:
        assert can_transition("called", "in_progress") is True

    def test_called_to_expired(self) -> None:
        assert can_transition("called", "expired") is True

    def test_in_progress_to_done(self) -> None:
        assert can_transition("in_progress", "done") is True

    # --- Transitions interdites ---

    def test_done_to_any_is_false(self) -> None:
        for target in QUEUE_TICKET_STATUSES:
            assert can_transition("done", target) is False, (
                f"done → {target} devrait être interdit"
            )

    def test_expired_to_any_is_false(self) -> None:
        for target in QUEUE_TICKET_STATUSES:
            assert can_transition("expired", target) is False, (
                f"expired → {target} devrait être interdit"
            )

    def test_in_progress_to_waiting_is_false(self) -> None:
        assert can_transition("in_progress", "waiting") is False

    def test_in_progress_to_called_is_false(self) -> None:
        assert can_transition("in_progress", "called") is False

    def test_in_progress_to_expired_is_false(self) -> None:
        assert can_transition("in_progress", "expired") is False

    def test_waiting_to_done_is_false(self) -> None:
        assert can_transition("waiting", "done") is False

    def test_called_to_waiting_is_false(self) -> None:
        assert can_transition("called", "waiting") is False

    def test_called_to_done_is_false(self) -> None:
        assert can_transition("called", "done") is False

    def test_same_status_is_always_false(self) -> None:
        for status in QUEUE_TICKET_STATUSES:
            assert can_transition(status, status) is False, (
                f"X → X devrait être interdit pour {status}"
            )

    def test_unknown_source_status_returns_false(self) -> None:
        assert can_transition("unknown_status", "waiting") is False

    def test_unknown_target_status_returns_false(self) -> None:
        assert can_transition("waiting", "unknown_status") is False


class TestAssertTransition:
    def test_valid_transition_does_not_raise(self) -> None:
        # Ne lève pas — toutes les transitions valides.
        assert_transition("waiting", "called")
        assert_transition("waiting", "in_progress")
        assert_transition("called", "in_progress")
        assert_transition("in_progress", "done")

    def test_invalid_transition_raises(self) -> None:
        with pytest.raises(InvalidQueueTicketTransition):
            assert_transition("done", "waiting")

    def test_terminal_status_raises(self) -> None:
        with pytest.raises(InvalidQueueTicketTransition):
            assert_transition("expired", "waiting")

    def test_identity_transition_raises(self) -> None:
        with pytest.raises(InvalidQueueTicketTransition):
            assert_transition("waiting", "waiting")

    def test_unknown_transition_raises(self) -> None:
        with pytest.raises(InvalidQueueTicketTransition):
            assert_transition("waiting", "nonexistent")

    def test_exception_message_is_not_empty(self) -> None:
        with pytest.raises(InvalidQueueTicketTransition) as exc_info:
            assert_transition("done", "called")
        assert str(exc_info.value)


# ---------------------------------------------------------------------------
# validate_service_ids
# ---------------------------------------------------------------------------


class TestValidateServiceIds:
    def test_empty_tuple_raises_invalid_services(self) -> None:
        with pytest.raises(InvalidQueueTicketServices):
            validate_service_ids(())

    def test_single_service_is_accepted(self) -> None:
        sid = uuid.uuid4()
        result = validate_service_ids((sid,))
        assert result == (sid,)

    def test_multiple_services_are_accepted(self) -> None:
        sids = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        result = validate_service_ids(sids)
        assert result == sids

    def test_returns_same_tuple_unmodified(self) -> None:
        sids = (uuid.uuid4(),)
        result = validate_service_ids(sids)
        assert result is sids

    def test_error_message_is_not_empty(self) -> None:
        with pytest.raises(InvalidQueueTicketServices) as exc_info:
            validate_service_ids(())
        assert str(exc_info.value)


# ---------------------------------------------------------------------------
# Constantes (invariants déclaratifs)
# ---------------------------------------------------------------------------


class TestQueueTicketConstants:
    def test_statuses_contains_five_values(self) -> None:
        assert len(QUEUE_TICKET_STATUSES) == 5

    def test_statuses_contains_expected_values(self) -> None:
        assert set(QUEUE_TICKET_STATUSES) == {
            "waiting",
            "called",
            "in_progress",
            "done",
            "expired",
        }

    def test_active_statuses_excludes_expired(self) -> None:
        assert "expired" not in QUEUE_TICKET_ACTIVE_STATUSES

    def test_active_statuses_contains_four_values(self) -> None:
        assert len(QUEUE_TICKET_ACTIVE_STATUSES) == 4

    def test_active_statuses_contains_expected_values(self) -> None:
        assert set(QUEUE_TICKET_ACTIVE_STATUSES) == {
            "waiting",
            "called",
            "in_progress",
            "done",
        }

    def test_pending_statuses_is_waiting_and_in_progress(self) -> None:
        assert set(QUEUE_TICKET_PENDING_STATUSES) == {"waiting", "in_progress"}

    def test_allowed_transitions_covers_all_statuses(self) -> None:
        for status in QUEUE_TICKET_STATUSES:
            assert status in ALLOWED_QUEUE_TICKET_TRANSITIONS, (
                f"Statut {status!r} absent de la table de transitions"
            )

    def test_terminal_statuses_have_empty_target_sets(self) -> None:
        assert ALLOWED_QUEUE_TICKET_TRANSITIONS["done"] == frozenset()
        assert ALLOWED_QUEUE_TICKET_TRANSITIONS["expired"] == frozenset()
