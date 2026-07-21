"""Tests unitaires — moteur de disponibilité pur (US-3.7, #21).

Couvre `domain/availability.py` sans aucune I/O ni base de données.

Cas traités :
- `overlaps` : chevauchement strict fermé-ouvert, adjacence tolérée, dates différentes ;
- `intervals_for_date` : jour absent (fermé), exception fermée prime, exception ouverte
  prime, programme hebdomadaire par défaut, pauses (deux intervalles) ;
- `free_slots` : cas de base, jour fermé, service trop long, pauses, adjacence dos-à-dos,
  créneaux chevauchant un `booked`, exclusion des créneaux passés (`now`), granularité,
  tri et déduplication, valeurs invalides (`duration=0`) ;
- `is_offered` : créneau dans l'offre, hors offre (hors horaires, mal aligné, durée ≠),
  créneau passé ou déjà occupé ;
- `add_minutes` : calcul normal, résultat franchissant minuit.
"""

from __future__ import annotations

import datetime


from coiflink_api.domain.availability import (
    SlotRange,
    add_minutes,
    free_slots,
    intervals_for_date,
    is_offered,
    overlaps,
)
from coiflink_api.domain.opening_hours import parse_opening_hours

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE = datetime.date(2026, 8, 3)  # lundi

_HOURS_MON_9_17 = parse_opening_hours({"weekly": {"mon": [{"start": "09:00", "end": "17:00"}]}})
_HOURS_MON_PAUSES = parse_opening_hours(
    {
        "weekly": {
            "mon": [
                {"start": "08:00", "end": "12:00"},
                {"start": "14:00", "end": "18:00"},
            ]
        }
    }
)
_HOURS_MON_30MIN = parse_opening_hours({"weekly": {"mon": [{"start": "09:00", "end": "09:30"}]}})


def _slot(start: str, end: str, date: datetime.date = _DATE) -> SlotRange:
    h_s, m_s = map(int, start.split(":"))
    h_e, m_e = map(int, end.split(":"))
    return SlotRange(
        date=date,
        start=datetime.time(h_s, m_s),
        end=datetime.time(h_e, m_e),
    )


# ---------------------------------------------------------------------------
# overlaps
# ---------------------------------------------------------------------------


class TestOverlaps:
    def test_distinct_dates_never_overlap(self) -> None:
        a = _slot("09:00", "10:00", datetime.date(2026, 8, 3))
        b = _slot("09:00", "10:00", datetime.date(2026, 8, 4))
        assert not overlaps(a, b)

    def test_strict_overlap_returns_true(self) -> None:
        a = _slot("09:00", "10:00")
        b = _slot("09:30", "10:30")
        assert overlaps(a, b)

    def test_adjacency_end_equal_start_not_overlap(self) -> None:
        # [09:00, 10:00) adjacent à [10:00, 11:00) — pas de conflit
        a = _slot("09:00", "10:00")
        b = _slot("10:00", "11:00")
        assert not overlaps(a, b)

    def test_adjacency_reversed_not_overlap(self) -> None:
        a = _slot("10:00", "11:00")
        b = _slot("09:00", "10:00")
        assert not overlaps(a, b)

    def test_containment_returns_true(self) -> None:
        a = _slot("09:00", "12:00")
        b = _slot("10:00", "11:00")
        assert overlaps(a, b)

    def test_one_minute_overlap_returns_true(self) -> None:
        a = _slot("09:00", "10:01")
        b = _slot("10:00", "11:00")
        assert overlaps(a, b)

    def test_identical_slots_overlap(self) -> None:
        a = _slot("09:00", "10:00")
        assert overlaps(a, a)

    def test_no_overlap_when_strictly_before(self) -> None:
        a = _slot("09:00", "10:00")
        b = _slot("11:00", "12:00")
        assert not overlaps(a, b)

    def test_symmetric_for_overlapping_pair(self) -> None:
        a = _slot("09:00", "10:00")
        b = _slot("09:30", "10:30")
        assert overlaps(a, b) == overlaps(b, a)

    def test_symmetric_for_adjacent_pair(self) -> None:
        a = _slot("09:00", "10:00")
        b = _slot("10:00", "11:00")
        assert overlaps(a, b) == overlaps(b, a)
        assert not overlaps(a, b)

    def test_symmetric_for_disjoint_pair(self) -> None:
        a = _slot("09:00", "10:00")
        b = _slot("11:00", "12:00")
        assert overlaps(a, b) == overlaps(b, a)
        assert not overlaps(a, b)


# ---------------------------------------------------------------------------
# intervals_for_date
# ---------------------------------------------------------------------------


class TestIntervalsForDate:
    def test_open_day_returns_interval(self) -> None:
        result = intervals_for_date(_HOURS_MON_9_17, _DATE)
        assert result == ((9 * 60, 17 * 60),)

    def test_closed_day_returns_empty(self) -> None:
        # _DATE est un lundi ; les horaires ne définissent que lundi → mardi = fermé
        tuesday = datetime.date(2026, 8, 4)
        result = intervals_for_date(_HOURS_MON_9_17, tuesday)
        assert result == ()

    def test_exception_closed_overrides_open_weekly(self) -> None:
        hours = parse_opening_hours(
            {
                "weekly": {"mon": [{"start": "09:00", "end": "17:00"}]},
                "exceptions": [
                    {"date": "2026-08-03", "closed": True, "intervals": []}
                ],
            }
        )
        result = intervals_for_date(hours, _DATE)
        assert result == ()

    def test_exception_open_overrides_weekly_intervals(self) -> None:
        hours = parse_opening_hours(
            {
                "weekly": {"mon": [{"start": "09:00", "end": "17:00"}]},
                "exceptions": [
                    {
                        "date": "2026-08-03",
                        "closed": False,
                        "intervals": [{"start": "10:00", "end": "12:00"}],
                    }
                ],
            }
        )
        result = intervals_for_date(hours, _DATE)
        assert result == ((10 * 60, 12 * 60),)

    def test_two_intervals_pause(self) -> None:
        result = intervals_for_date(_HOURS_MON_PAUSES, _DATE)
        assert result == ((8 * 60, 12 * 60), (14 * 60, 18 * 60))

    def test_exception_date_not_matching_uses_weekly(self) -> None:
        hours = parse_opening_hours(
            {
                "weekly": {"mon": [{"start": "09:00", "end": "17:00"}]},
                "exceptions": [
                    {"date": "2026-08-04", "closed": True, "intervals": []}
                ],
            }
        )
        result = intervals_for_date(hours, _DATE)
        assert result == ((9 * 60, 17 * 60),)


# ---------------------------------------------------------------------------
# free_slots
# ---------------------------------------------------------------------------


class TestFreeSlots:
    def test_closed_day_returns_no_slots(self) -> None:
        tuesday = datetime.date(2026, 8, 4)
        result = free_slots(_HOURS_MON_9_17, tuesday, 60, ())
        assert result == ()

    def test_duration_zero_returns_no_slots(self) -> None:
        result = free_slots(_HOURS_MON_9_17, _DATE, 0, ())
        assert result == ()

    def test_granularity_zero_returns_no_slots(self) -> None:
        result = free_slots(_HOURS_MON_9_17, _DATE, 30, (), granularity_minutes=0)
        assert result == ()

    def test_service_longer_than_interval_returns_no_slots(self) -> None:
        # Intervalle = 30 min ; prestation = 60 min → ne rentre pas
        result = free_slots(_HOURS_MON_30MIN, _DATE, 60, ())
        assert result == ()

    def test_service_exactly_fills_interval(self) -> None:
        # Intervalle = 30 min ; prestation = 30 min → exactement un créneau
        result = free_slots(_HOURS_MON_30MIN, _DATE, 30, ())
        assert len(result) == 1
        assert result[0] == _slot("09:00", "09:30")

    def test_basic_granularity_15min(self) -> None:
        result = free_slots(_HOURS_MON_9_17, _DATE, 60, (), granularity_minutes=15)
        # De 09:00 à 16:00 par pas de 15 min = (16*60 - 9*60)//15 + 1 − 1 créneaux
        # De 09:00 à 16:00 (exclure 16:45+60=17:45 > 17:00) : dernier start = 16:00
        starts = [s.start for s in result]
        assert datetime.time(9, 0) in starts
        assert datetime.time(16, 0) in starts
        assert datetime.time(16, 15) not in starts  # 16:15+60 = 17:15 > 17:00

    def test_results_sorted_by_start(self) -> None:
        result = free_slots(_HOURS_MON_9_17, _DATE, 30, (), granularity_minutes=30)
        starts = [s.start for s in result]
        assert starts == sorted(starts)

    def test_booked_slot_excluded(self) -> None:
        booked = (_slot("09:00", "10:00"),)
        result = free_slots(_HOURS_MON_9_17, _DATE, 60, booked, granularity_minutes=60)
        for slot in result:
            assert not overlaps(slot, booked[0])

    def test_booked_slot_does_not_remove_non_overlapping(self) -> None:
        booked = (_slot("09:00", "10:00"),)
        result = free_slots(_HOURS_MON_9_17, _DATE, 60, booked, granularity_minutes=60)
        assert any(s.start >= datetime.time(10, 0) for s in result)

    def test_pause_no_slot_spans_gap(self) -> None:
        # Intervalle matin 08:00-12:00, après-midi 14:00-18:00 (pause 12:00-14:00).
        # Avec prestation 120 min (2 h), pas de créneau ne doit chevaucher la pause.
        result = free_slots(_HOURS_MON_PAUSES, _DATE, 120, (), granularity_minutes=60)
        for slot in result:
            assert slot.end <= datetime.time(12, 0) or slot.start >= datetime.time(14, 0)

    def test_adjacent_booked_slots_not_conflicting(self) -> None:
        # Deux créneaux dos-à-dos : [09:00,10:00) et [10:00,11:00).
        # Si [09:00,10:00) est réservé, [10:00,11:00) doit rester disponible.
        booked = (_slot("09:00", "10:00"),)
        result = free_slots(_HOURS_MON_9_17, _DATE, 60, booked, granularity_minutes=60)
        assert _slot("10:00", "11:00") in result

    def test_past_slots_excluded_when_now_provided(self) -> None:
        # now = 10:00 le même jour → les créneaux commençant avant 10:00 sont exclus
        now = datetime.datetime(_DATE.year, _DATE.month, _DATE.day, 10, 0)
        result = free_slots(_HOURS_MON_9_17, _DATE, 60, (), now=now)
        for slot in result:
            assert slot.start >= datetime.time(10, 0)

    def test_past_slots_not_excluded_when_now_is_none(self) -> None:
        result = free_slots(_HOURS_MON_9_17, _DATE, 60, (), now=None)
        assert any(s.start == datetime.time(9, 0) for s in result)

    def test_future_date_past_slots_ignored(self) -> None:
        # now est dans un autre jour (hier) → aucun créneau n'est « passé »
        yesterday = datetime.datetime(2026, 8, 2, 23, 59)
        result = free_slots(_HOURS_MON_9_17, _DATE, 60, (), now=yesterday)
        assert any(s.start == datetime.time(9, 0) for s in result)

    def test_min_lead_minutes_shifts_threshold(self) -> None:
        # now = 09:00, min_lead = 30 → les créneaux commençant avant 09:30 exclus
        now = datetime.datetime(_DATE.year, _DATE.month, _DATE.day, 9, 0)
        result = free_slots(
            _HOURS_MON_9_17, _DATE, 30, (), now=now, min_lead_minutes=30
        )
        for slot in result:
            assert slot.start >= datetime.time(9, 30)

    def test_no_duplicate_slots(self) -> None:
        # Deux intervalles adjacents — aucun doublon ne doit apparaître.
        hours = parse_opening_hours(
            {
                "weekly": {
                    "mon": [
                        {"start": "09:00", "end": "10:00"},
                        {"start": "10:00", "end": "11:00"},
                    ]
                }
            }
        )
        result = free_slots(hours, _DATE, 30, (), granularity_minutes=30)
        keys = [(s.start, s.end) for s in result]
        assert len(keys) == len(set(keys))

    def test_granularity_30min_correct_count(self) -> None:
        # 09:00-11:00 (2 h), prestation 30 min, pas 30 min → [09:00, 09:30, 10:00, 10:30]
        hours = parse_opening_hours({"weekly": {"mon": [{"start": "09:00", "end": "11:00"}]}})
        result = free_slots(hours, _DATE, 30, (), granularity_minutes=30)
        assert len(result) == 4
        assert result[0] == _slot("09:00", "09:30")
        assert result[-1] == _slot("10:30", "11:00")

    def test_negative_duration_returns_empty(self) -> None:
        result = free_slots(_HOURS_MON_9_17, _DATE, -60, ())
        assert result == ()

    def test_now_on_next_day_all_slots_excluded(self) -> None:
        # now = lendemain 00:00 : tous les créneaux d'aujourd'hui sont « passés »
        tomorrow = datetime.datetime.combine(
            _DATE + datetime.timedelta(days=1), datetime.time()
        )
        result = free_slots(_HOURS_MON_9_17, _DATE, 60, (), now=tomorrow)
        assert result == ()

    def test_all_booked_slots_returns_empty(self) -> None:
        # Chaque heure de 09:00 à 17:00 est réservée → aucun créneau libre
        booked = tuple(
            _slot(f"{h:02d}:00", f"{h + 1:02d}:00") for h in range(9, 17)
        )
        result = free_slots(_HOURS_MON_9_17, _DATE, 60, booked, granularity_minutes=60)
        assert result == ()


# ---------------------------------------------------------------------------
# is_offered
# ---------------------------------------------------------------------------


class TestIsOffered:
    def test_offered_slot_returns_true(self) -> None:
        slot = _slot("09:00", "10:00")
        assert is_offered(_HOURS_MON_9_17, slot, 60, (), granularity_minutes=60)

    def test_wrong_duration_returns_false(self) -> None:
        # Créneau 09:00-10:30 mais duration_minutes=60 → durée incohérente
        slot = _slot("09:00", "10:30")
        assert not is_offered(_HOURS_MON_9_17, slot, 60, (), granularity_minutes=60)

    def test_outside_hours_returns_false(self) -> None:
        slot = _slot("18:00", "19:00")
        assert not is_offered(_HOURS_MON_9_17, slot, 60, (), granularity_minutes=60)

    def test_misaligned_grid_returns_false(self) -> None:
        # Grille 15 min, créneau non aligné (09:07 n'est pas sur la grille)
        slot = _slot("09:07", "10:07")
        assert not is_offered(_HOURS_MON_9_17, slot, 60, (), granularity_minutes=15)

    def test_booked_slot_returns_false(self) -> None:
        booked = (_slot("09:00", "10:00"),)
        slot = _slot("09:00", "10:00")
        assert not is_offered(_HOURS_MON_9_17, slot, 60, booked, granularity_minutes=60)

    def test_past_slot_returns_false(self) -> None:
        now = datetime.datetime(_DATE.year, _DATE.month, _DATE.day, 10, 0)
        slot = _slot("09:00", "10:00")
        assert not is_offered(_HOURS_MON_9_17, slot, 60, (), now=now, granularity_minutes=60)

    def test_closed_day_returns_false(self) -> None:
        tuesday = datetime.date(2026, 8, 4)
        slot = SlotRange(date=tuesday, start=datetime.time(9, 0), end=datetime.time(10, 0))
        assert not is_offered(_HOURS_MON_9_17, slot, 60, ())

    def test_slot_adjacent_to_booked_is_offered(self) -> None:
        # [09:00, 10:00) adjacent à [10:00, 11:00) : l'adjacence n'est pas un conflit.
        booked = (_slot("10:00", "11:00"),)
        slot = _slot("09:00", "10:00")
        assert is_offered(_HOURS_MON_9_17, slot, 60, booked, granularity_minutes=60)


# ---------------------------------------------------------------------------
# add_minutes
# ---------------------------------------------------------------------------


class TestAddMinutes:
    def test_normal_addition(self) -> None:
        result = add_minutes(datetime.time(9, 0), 30)
        assert result == datetime.time(9, 30)

    def test_addition_to_end_of_day_before_midnight(self) -> None:
        result = add_minutes(datetime.time(23, 59), 0)
        assert result == datetime.time(23, 59)

    def test_midnight_overflow_returns_none(self) -> None:
        result = add_minutes(datetime.time(23, 30), 60)
        assert result is None

    def test_exactly_1440_returns_none(self) -> None:
        result = add_minutes(datetime.time(0, 0), 24 * 60)
        assert result is None

    def test_zero_minutes(self) -> None:
        t = datetime.time(10, 15)
        assert add_minutes(t, 0) == t
