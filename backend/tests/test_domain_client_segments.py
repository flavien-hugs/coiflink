"""Tests unitaires — domaine `client_segments` (US-6.4, #42).

Couvre `classify_client_segments` (fonction pure, déterministe) et les
dataclasses `ClientVisitProfile` / `ClientSegments` :
- classification **new** : visits_in_period > 0, visits_before == 0 ;
- classification **recurring** : visits_in_period > 0, visits_before > 0 ;
- classification **inactive** : visits_in_period == 0, visits_before > 0 ;
- cas de bord **future-only** : visits_in_period == 0, visits_before == 0
  → non compté dans aucun segment ;
- profils multiples → effectifs corrects ;
- `active == new + recurring` (propriété dérivée) ;
- mutuelle exclusivité : `new + recurring + inactive ≤ len(profiles)` ;
- entrée vide → tous les compteurs à `0` ;
- non-PII : `ClientVisitProfile` et `ClientSegments` ne portent aucun
  identifiant de client (§11.3 / ADR-0026) ;
- immuabilité (`frozen=True`).
"""

from __future__ import annotations

import datetime

import pytest

from coiflink_api.domain.client_segments import (
    ClientSegments,
    ClientVisitProfile,
    classify_client_segments,
)

# ---------------------------------------------------------------------------
# Constantes de test
# ---------------------------------------------------------------------------

_DATE_FROM = datetime.date(2026, 8, 1)
_DATE_TO = datetime.date(2026, 8, 31)
_DATE_BEFORE = datetime.date(2026, 7, 15)      # strictement avant _DATE_FROM
_DATE_IN_PERIOD = datetime.date(2026, 8, 15)   # dans [_DATE_FROM, _DATE_TO]
_DATE_AFTER = datetime.date(2026, 9, 5)        # après _DATE_TO


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_profile() -> ClientVisitProfile:
    """Client dont la première (et seule) visite tombe dans la période."""
    return ClientVisitProfile(
        first_visit=_DATE_IN_PERIOD,
        visits_in_period=1,
        visits_before=0,
    )


def _recurring_profile() -> ClientVisitProfile:
    """Client ayant une visite avant la période et une dans la période."""
    return ClientVisitProfile(
        first_visit=_DATE_BEFORE,
        visits_in_period=1,
        visits_before=1,
    )


def _inactive_profile() -> ClientVisitProfile:
    """Client ayant des visites avant la période, aucune dans la période."""
    return ClientVisitProfile(
        first_visit=_DATE_BEFORE,
        visits_in_period=0,
        visits_before=2,
    )


def _future_only_profile() -> ClientVisitProfile:
    """Client dont toutes les visites sont postérieures à date_to (cas de bord)."""
    return ClientVisitProfile(
        first_visit=_DATE_AFTER,
        visits_in_period=0,
        visits_before=0,
    )


# ---------------------------------------------------------------------------
# ClientVisitProfile — structure et immuabilité
# ---------------------------------------------------------------------------


class TestClientVisitProfile:
    def test_has_first_visit_field(self) -> None:
        p = _new_profile()
        assert p.first_visit == _DATE_IN_PERIOD

    def test_has_visits_in_period_field(self) -> None:
        p = _new_profile()
        assert p.visits_in_period == 1

    def test_has_visits_before_field(self) -> None:
        p = _inactive_profile()
        assert p.visits_before == 2

    def test_is_frozen(self) -> None:
        """ClientVisitProfile est immuable (frozen=True)."""
        p = _new_profile()
        with pytest.raises((AttributeError, TypeError)):
            p.visits_in_period = 99  # type: ignore[misc]

    def test_no_client_id_field(self) -> None:
        """Anti-oracle §11.1/§11.3 : pas de `client_id` dans le profil."""
        assert not hasattr(_new_profile(), "client_id")

    def test_no_appointment_id_field(self) -> None:
        """Anti-oracle §11.1/§11.3 : pas d'`appointment_id` dans le profil."""
        assert not hasattr(_new_profile(), "appointment_id")

    def test_no_name_field(self) -> None:
        assert not hasattr(_new_profile(), "name")

    def test_no_phone_field(self) -> None:
        assert not hasattr(_new_profile(), "phone")


# ---------------------------------------------------------------------------
# ClientSegments — structure, propriété `active`, immuabilité
# ---------------------------------------------------------------------------


class TestClientSegments:
    def test_default_all_zeros(self) -> None:
        s = ClientSegments()
        assert s.new == 0
        assert s.recurring == 0
        assert s.inactive == 0

    def test_active_is_new_plus_recurring(self) -> None:
        s = ClientSegments(new=3, recurring=5, inactive=2)
        assert s.active == 8

    def test_active_is_zero_when_all_zero(self) -> None:
        assert ClientSegments().active == 0

    def test_active_excludes_inactive(self) -> None:
        """Inactifs exclus du décompte `active` : seuls nouveaux + récurrents."""
        s = ClientSegments(new=10, recurring=20, inactive=100)
        assert s.active == 30

    def test_is_frozen(self) -> None:
        s = ClientSegments(new=1)
        with pytest.raises((AttributeError, TypeError)):
            s.new = 99  # type: ignore[misc]

    def test_no_client_id_field(self) -> None:
        assert not hasattr(ClientSegments(new=1, recurring=2, inactive=3), "client_id")

    def test_no_user_id_field(self) -> None:
        assert not hasattr(ClientSegments(), "user_id")

    def test_date_from_echoed(self) -> None:
        s = ClientSegments(date_from=_DATE_FROM, date_to=_DATE_TO)
        assert s.date_from == _DATE_FROM

    def test_date_to_echoed(self) -> None:
        s = ClientSegments(date_from=_DATE_FROM, date_to=_DATE_TO)
        assert s.date_to == _DATE_TO

    def test_default_dates_none(self) -> None:
        s = ClientSegments()
        assert s.date_from is None
        assert s.date_to is None


# ---------------------------------------------------------------------------
# classify_client_segments — règle de classification (cas unitaires)
# ---------------------------------------------------------------------------


class TestClassifyClientSegmentsRule:
    def test_new_client_counted_as_new(self) -> None:
        """visits_in_period > 0, visits_before == 0 → nouveau."""
        result = classify_client_segments(
            (_new_profile(),), date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert result.new == 1
        assert result.recurring == 0
        assert result.inactive == 0

    def test_recurring_client_counted_as_recurring(self) -> None:
        """visits_in_period > 0, visits_before > 0 → récurrent."""
        result = classify_client_segments(
            (_recurring_profile(),), date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert result.recurring == 1
        assert result.new == 0
        assert result.inactive == 0

    def test_inactive_client_counted_as_inactive(self) -> None:
        """visits_in_period == 0, visits_before > 0 → inactif."""
        result = classify_client_segments(
            (_inactive_profile(),), date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert result.inactive == 1
        assert result.new == 0
        assert result.recurring == 0

    def test_future_only_client_in_no_segment(self) -> None:
        """visits_in_period == 0, visits_before == 0 → aucun segment."""
        result = classify_client_segments(
            (_future_only_profile(),), date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert result.new == 0
        assert result.recurring == 0
        assert result.inactive == 0

    def test_new_client_with_multiple_in_period_visits(self) -> None:
        """Plusieurs visites dans la période mais aucune avant → nouveau."""
        p = ClientVisitProfile(
            first_visit=_DATE_IN_PERIOD,
            visits_in_period=5,
            visits_before=0,
        )
        result = classify_client_segments((p,), date_from=_DATE_FROM, date_to=_DATE_TO)
        assert result.new == 1

    def test_recurring_client_with_many_visits(self) -> None:
        """Plusieurs visites dans la période et des visites avant → récurrent."""
        p = ClientVisitProfile(
            first_visit=_DATE_BEFORE,
            visits_in_period=3,
            visits_before=7,
        )
        result = classify_client_segments((p,), date_from=_DATE_FROM, date_to=_DATE_TO)
        assert result.recurring == 1

    def test_inactive_with_single_prior_visit(self) -> None:
        """Un seul visite avant la période, aucune dans la période → inactif."""
        p = ClientVisitProfile(
            first_visit=_DATE_BEFORE,
            visits_in_period=0,
            visits_before=1,
        )
        result = classify_client_segments((p,), date_from=_DATE_FROM, date_to=_DATE_TO)
        assert result.inactive == 1


# ---------------------------------------------------------------------------
# classify_client_segments — effectifs et mutuelle exclusivité (profils multiples)
# ---------------------------------------------------------------------------


class TestClassifyClientSegmentsMultiple:
    def _profiles(self) -> tuple[ClientVisitProfile, ...]:
        return (
            _new_profile(),
            _new_profile(),
            _recurring_profile(),
            _inactive_profile(),
            _inactive_profile(),
            _inactive_profile(),
            _future_only_profile(),
        )

    def _result(self) -> ClientSegments:
        return classify_client_segments(
            self._profiles(), date_from=_DATE_FROM, date_to=_DATE_TO
        )

    def test_new_count_correct(self) -> None:
        assert self._result().new == 2

    def test_recurring_count_correct(self) -> None:
        assert self._result().recurring == 1

    def test_inactive_count_correct(self) -> None:
        assert self._result().inactive == 3

    def test_active_equals_new_plus_recurring(self) -> None:
        r = self._result()
        assert r.active == r.new + r.recurring

    def test_mutual_exclusivity_sum_le_total(self) -> None:
        """new + recurring + inactive ≤ len(profiles) (le client future-only ne compte pas)."""
        r = self._result()
        assert r.new + r.recurring + r.inactive <= len(self._profiles())

    def test_future_only_not_counted(self) -> None:
        """Le profil future-only ne compte pas dans les trois segments."""
        r = self._result()
        # 7 profils, 6 segmentés (2+1+3), le 7e (future-only) non compté
        assert r.new + r.recurring + r.inactive == 6

    def test_no_double_counting(self) -> None:
        """Un profil compté dans un segment ne doit pas figurer dans un autre."""
        profiles = (_new_profile(), _recurring_profile(), _inactive_profile())
        r = classify_client_segments(profiles, date_from=_DATE_FROM, date_to=_DATE_TO)
        assert r.new == 1
        assert r.recurring == 1
        assert r.inactive == 1
        assert r.new + r.recurring + r.inactive == len(profiles)


# ---------------------------------------------------------------------------
# classify_client_segments — cas limites (edge cases)
# ---------------------------------------------------------------------------


class TestClassifyClientSegmentsEdgeCases:
    def test_empty_profiles_all_zeros(self) -> None:
        """Entrée vide → tous les compteurs à 0 (état vide légitime)."""
        result = classify_client_segments((), date_from=_DATE_FROM, date_to=_DATE_TO)
        assert result.new == 0
        assert result.recurring == 0
        assert result.inactive == 0
        assert result.active == 0

    def test_empty_profiles_period_echoed(self) -> None:
        """Les bornes de période sont échouées même pour une entrée vide."""
        result = classify_client_segments((), date_from=_DATE_FROM, date_to=_DATE_TO)
        assert result.date_from == _DATE_FROM
        assert result.date_to == _DATE_TO

    def test_only_future_clients_all_zeros(self) -> None:
        """Tous les profils sont futurs → aucun segment non nul."""
        profiles = (_future_only_profile(), _future_only_profile())
        result = classify_client_segments(profiles, date_from=_DATE_FROM, date_to=_DATE_TO)
        assert result.new == 0
        assert result.recurring == 0
        assert result.inactive == 0

    def test_single_day_period_new_client(self) -> None:
        """Période d'un seul jour : le segment `new` est atteignable."""
        single_day = datetime.date(2026, 8, 15)
        p = ClientVisitProfile(
            first_visit=single_day,
            visits_in_period=1,
            visits_before=0,
        )
        result = classify_client_segments((p,), date_from=single_day, date_to=single_day)
        assert result.new == 1

    def test_period_echoed_in_result(self) -> None:
        result = classify_client_segments(
            (_new_profile(),), date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert result.date_from == _DATE_FROM
        assert result.date_to == _DATE_TO

    def test_large_count_correct(self) -> None:
        """Données à grand volume : comptage correct."""
        profiles = tuple(
            ClientVisitProfile(
                first_visit=_DATE_IN_PERIOD,
                visits_in_period=1,
                visits_before=0,
            )
            for _ in range(500)
        )
        result = classify_client_segments(profiles, date_from=_DATE_FROM, date_to=_DATE_TO)
        assert result.new == 500
        assert result.recurring == 0
        assert result.inactive == 0

    def test_is_pure_no_io(self) -> None:
        """classify_client_segments est une fonction pure — pas d'accès externe."""
        classify_client_segments((), date_from=_DATE_FROM, date_to=_DATE_TO)

    def test_active_property_is_derived_not_stored(self) -> None:
        """`active` est calculé dynamiquement depuis `new + recurring`."""
        s = ClientSegments(new=7, recurring=3, inactive=99)
        assert s.active == 10


# ---------------------------------------------------------------------------
# Module __all__
# ---------------------------------------------------------------------------


class TestModuleExports:
    def test_all_exports_client_visit_profile(self) -> None:
        from coiflink_api.domain import client_segments as m

        assert "ClientVisitProfile" in m.__all__

    def test_all_exports_client_segments(self) -> None:
        from coiflink_api.domain import client_segments as m

        assert "ClientSegments" in m.__all__

    def test_all_exports_classify_client_segments(self) -> None:
        from coiflink_api.domain import client_segments as m

        assert "classify_client_segments" in m.__all__
