"""Tests unitaires — module de domaine `opening_hours` (US-2.2, #16).

Couvre `parse_opening_hours` et `to_jsonb` sans aucune I/O. Cas traités :
horaires par jour, jours fermés, pauses, intervalles invalides, jours
exceptionnels, non-vacuité utile, normalisation (idempotence), bornes de
robustesse.  Chaque erreur lève `InvalidOpeningHours` avec un message neutre.
"""

from __future__ import annotations

import datetime

import pytest

from coiflink_api.domain.errors import InvalidOpeningHours
from coiflink_api.domain.opening_hours import (
    DAY_KEYS,
    DEFAULT_TIMEZONE,
    MAX_EXCEPTIONS,
    MAX_INTERVALS_PER_DAY,
    OPENING_HOURS_SCHEMA_VERSION,
    parse_opening_hours,
    to_jsonb,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SINGLE_INTERVAL = [{"start": "09:00", "end": "17:00"}]
_TWO_INTERVALS = [
    {"start": "08:00", "end": "12:00"},
    {"start": "14:00", "end": "18:00"},
]
_MINIMAL_VALID = {"weekly": {"mon": _SINGLE_INTERVAL}}


# ---------------------------------------------------------------------------
# Horaires par jour — cas valides
# ---------------------------------------------------------------------------


class TestValidDailySchedules:
    def test_single_day_single_interval_accepted(self) -> None:
        result = parse_opening_hours(_MINIMAL_VALID)
        assert len(result.weekly) == 1
        assert result.weekly[0].day == "mon"
        assert len(result.weekly[0].intervals) == 1

    def test_all_seven_days_accepted(self) -> None:
        weekly = {day: _SINGLE_INTERVAL for day in DAY_KEYS}
        result = parse_opening_hours({"weekly": weekly})
        assert len(result.weekly) == 7

    def test_week_ordered_canonically(self) -> None:
        # Provide days out of order; result must be sorted mon→sun.
        payload = {"weekly": {"fri": _SINGLE_INTERVAL, "mon": _SINGLE_INTERVAL}}
        result = parse_opening_hours(payload)
        assert result.weekly[0].day == "mon"
        assert result.weekly[1].day == "fri"

    def test_uppercase_day_key_normalised_to_lowercase(self) -> None:
        payload = {"weekly": {"MON": _SINGLE_INTERVAL}}
        result = parse_opening_hours(payload)
        assert result.weekly[0].day == "mon"

    def test_mixed_case_day_key_accepted(self) -> None:
        payload = {"weekly": {"Tue": _SINGLE_INTERVAL}}
        result = parse_opening_hours(payload)
        assert result.weekly[0].day == "tue"


class TestUnknownDayKeys:
    @pytest.mark.parametrize(
        "bad_day",
        ["lundi", "mo", "monday", "1", "tue ", " tue", "fr"],
    )
    def test_unknown_day_key_raises(self, bad_day: str) -> None:
        payload = {"weekly": {bad_day: _SINGLE_INTERVAL}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_duplicate_day_after_normalisation_raises(self) -> None:
        # "mon" and "MON" both normalise to "mon" → duplicate.
        payload = {"weekly": {"mon": _SINGLE_INTERVAL, "MON": _SINGLE_INTERVAL}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_unknown_top_level_key_raises(self) -> None:
        payload = {"weekly": {"mon": _SINGLE_INTERVAL}, "extra_key": "value"}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_non_dict_payload_raises(self) -> None:
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(["mon", "08:00"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Jours fermés
# ---------------------------------------------------------------------------


class TestClosedDays:
    def test_empty_intervals_list_is_closed_and_accepted(self) -> None:
        # A day with [] is parsed without error but treated as closed (filtered out
        # of the weekly tuple because it has no intervals).
        payload = {"weekly": {"mon": _SINGLE_INTERVAL, "tue": []}}
        result = parse_opening_hours(payload)
        days = [s.day for s in result.weekly]
        assert "tue" not in days  # closed day not in weekly result

    def test_absent_day_is_treated_as_closed(self) -> None:
        # Days not listed in weekly are implicitly closed — no error.
        result = parse_opening_hours(_MINIMAL_VALID)
        days = [s.day for s in result.weekly]
        assert "tue" not in days
        assert "sun" not in days

    def test_all_days_empty_raises_non_vacuity(self) -> None:
        # All days explicitly closed → no opening interval → rejected.
        payload = {"weekly": {day: [] for day in DAY_KEYS}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)


# ---------------------------------------------------------------------------
# Pauses (plusieurs intervalles par jour)
# ---------------------------------------------------------------------------


class TestPauses:
    def test_two_disjoint_intervals_accepted(self) -> None:
        payload = {"weekly": {"mon": _TWO_INTERVALS}}
        result = parse_opening_hours(payload)
        assert len(result.weekly[0].intervals) == 2

    def test_intervals_sorted_by_start_time(self) -> None:
        # Intervals provided in reverse order must be sorted.
        payload = {
            "weekly": {
                "mon": [
                    {"start": "14:00", "end": "18:00"},
                    {"start": "08:00", "end": "12:00"},
                ]
            }
        }
        result = parse_opening_hours(payload)
        intervals = result.weekly[0].intervals
        assert intervals[0].start == "08:00"
        assert intervals[1].start == "14:00"

    def test_adjacent_intervals_accepted(self) -> None:
        # end == start of next: journée continue, non chevauchant.
        payload = {
            "weekly": {
                "mon": [
                    {"start": "08:00", "end": "12:00"},
                    {"start": "12:00", "end": "18:00"},
                ]
            }
        }
        result = parse_opening_hours(payload)
        assert len(result.weekly[0].intervals) == 2

    def test_max_intervals_per_day_accepted(self) -> None:
        intervals = [
            {"start": f"0{i}:00", "end": f"0{i}:30"} for i in range(MAX_INTERVALS_PER_DAY)
        ]
        payload = {"weekly": {"mon": intervals}}
        result = parse_opening_hours(payload)
        assert len(result.weekly[0].intervals) == MAX_INTERVALS_PER_DAY


# ---------------------------------------------------------------------------
# Intervalles invalides
# ---------------------------------------------------------------------------


class TestInvalidIntervals:
    def test_end_before_start_raises(self) -> None:
        payload = {"weekly": {"mon": [{"start": "18:00", "end": "08:00"}]}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_end_equal_start_raises(self) -> None:
        payload = {"weekly": {"mon": [{"start": "08:00", "end": "08:00"}]}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_overlapping_intervals_raises(self) -> None:
        payload = {
            "weekly": {
                "mon": [
                    {"start": "08:00", "end": "12:00"},
                    {"start": "11:00", "end": "15:00"},
                ]
            }
        }
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    @pytest.mark.parametrize(
        "bad_start",
        ["8:00", "25:00", "24:00", "12:60", "08:00:00", "8h", "", "noon"],
    )
    def test_malformed_start_time_raises(self, bad_start: str) -> None:
        payload = {"weekly": {"mon": [{"start": bad_start, "end": "18:00"}]}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    @pytest.mark.parametrize(
        "bad_end",
        ["8:00", "25:00", "24:00", "12:60", "", "23:60"],
    )
    def test_malformed_end_time_raises(self, bad_end: str) -> None:
        payload = {"weekly": {"mon": [{"start": "08:00", "end": bad_end}]}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_interval_missing_start_raises(self) -> None:
        payload = {"weekly": {"mon": [{"end": "18:00"}]}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_interval_missing_end_raises(self) -> None:
        payload = {"weekly": {"mon": [{"start": "08:00"}]}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_non_list_intervals_raises(self) -> None:
        payload = {"weekly": {"mon": "08:00-18:00"}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_non_dict_weekly_raises(self) -> None:
        payload = {"weekly": ["mon", "08:00"]}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)


# ---------------------------------------------------------------------------
# Jours exceptionnels
# ---------------------------------------------------------------------------


class TestExceptionalDays:
    def test_closed_exception_without_intervals_accepted(self) -> None:
        payload = {
            **_MINIMAL_VALID,
            "exceptions": [{"date": "2026-08-07", "closed": True}],
        }
        result = parse_opening_hours(payload)
        assert len(result.exceptions) == 1
        assert result.exceptions[0].closed is True
        assert result.exceptions[0].intervals == ()

    def test_open_exception_with_intervals_accepted(self) -> None:
        payload = {
            **_MINIMAL_VALID,
            "exceptions": [
                {
                    "date": "2026-12-24",
                    "closed": False,
                    "intervals": [{"start": "08:00", "end": "13:00"}],
                }
            ],
        }
        result = parse_opening_hours(payload)
        assert result.exceptions[0].closed is False
        assert len(result.exceptions[0].intervals) == 1

    def test_closed_exception_with_intervals_raises(self) -> None:
        payload = {
            **_MINIMAL_VALID,
            "exceptions": [
                {
                    "date": "2026-08-07",
                    "closed": True,
                    "intervals": [{"start": "09:00", "end": "13:00"}],
                }
            ],
        }
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_open_exception_without_intervals_raises(self) -> None:
        payload = {
            **_MINIMAL_VALID,
            "exceptions": [{"date": "2026-08-07", "closed": False, "intervals": []}],
        }
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_duplicate_exception_dates_raises(self) -> None:
        payload = {
            **_MINIMAL_VALID,
            "exceptions": [
                {"date": "2026-08-07", "closed": True},
                {"date": "2026-08-07", "closed": True},
            ],
        }
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    @pytest.mark.parametrize(
        "bad_date",
        ["2026-13-01", "2026-00-01", "2026/08/07", "07-08-2026", "2026-8-7", "not-a-date"],
    )
    def test_invalid_exception_date_raises(self, bad_date: str) -> None:
        payload = {
            **_MINIMAL_VALID,
            "exceptions": [{"date": bad_date, "closed": True}],
        }
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_exceptions_sorted_by_date(self) -> None:
        payload = {
            **_MINIMAL_VALID,
            "exceptions": [
                {"date": "2026-12-24", "closed": True},
                {"date": "2026-08-07", "closed": True},
            ],
        }
        result = parse_opening_hours(payload)
        assert result.exceptions[0].date == datetime.date(2026, 8, 7)
        assert result.exceptions[1].date == datetime.date(2026, 12, 24)

    def test_exception_date_accepts_date_object(self) -> None:
        payload = {
            **_MINIMAL_VALID,
            "exceptions": [
                {"date": datetime.date(2026, 8, 7), "closed": True},
            ],
        }
        result = parse_opening_hours(payload)
        assert result.exceptions[0].date == datetime.date(2026, 8, 7)

    def test_non_list_exceptions_raises(self) -> None:
        payload = {**_MINIMAL_VALID, "exceptions": "2026-08-07"}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_none_exceptions_treated_as_empty(self) -> None:
        # `None` for exceptions is handled (returns empty tuple).
        payload = {**_MINIMAL_VALID, "exceptions": None}
        result = parse_opening_hours(payload)
        assert result.exceptions == ()


# ---------------------------------------------------------------------------
# Non-vacuité utile
# ---------------------------------------------------------------------------


class TestNonVacuity:
    def test_empty_weekly_and_no_exceptions_raises(self) -> None:
        payload = {"weekly": {}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_only_closed_exceptions_raises(self) -> None:
        payload = {
            "exceptions": [{"date": "2026-08-07", "closed": True}],
        }
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_only_open_exception_accepted(self) -> None:
        # Weekly absent but one open exception → satisfies non-vacuity.
        payload = {
            "exceptions": [
                {
                    "date": "2026-08-07",
                    "closed": False,
                    "intervals": [{"start": "09:00", "end": "17:00"}],
                }
            ],
        }
        result = parse_opening_hours(payload)
        assert len(result.exceptions) == 1


# ---------------------------------------------------------------------------
# Fuseau horaire
# ---------------------------------------------------------------------------


class TestTimezone:
    def test_missing_timezone_defaults_to_africa_abidjan(self) -> None:
        result = parse_opening_hours(_MINIMAL_VALID)
        assert result.timezone == DEFAULT_TIMEZONE

    def test_none_timezone_defaults(self) -> None:
        payload = {**_MINIMAL_VALID, "timezone": None}
        result = parse_opening_hours(payload)
        assert result.timezone == DEFAULT_TIMEZONE

    def test_custom_timezone_preserved(self) -> None:
        payload = {**_MINIMAL_VALID, "timezone": "Europe/Paris"}
        result = parse_opening_hours(payload)
        assert result.timezone == "Europe/Paris"

    def test_timezone_stripped_of_whitespace(self) -> None:
        payload = {**_MINIMAL_VALID, "timezone": "  Africa/Abidjan  "}
        result = parse_opening_hours(payload)
        assert result.timezone == "Africa/Abidjan"

    def test_empty_timezone_raises(self) -> None:
        payload = {**_MINIMAL_VALID, "timezone": ""}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_whitespace_only_timezone_raises(self) -> None:
        payload = {**_MINIMAL_VALID, "timezone": "   "}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)


# ---------------------------------------------------------------------------
# Bornes de robustesse
# ---------------------------------------------------------------------------


class TestRobustnessBounds:
    def test_too_many_intervals_per_day_raises(self) -> None:
        intervals = [
            {"start": f"0{i}:00", "end": f"0{i}:30"}
            for i in range(MAX_INTERVALS_PER_DAY + 1)
        ]
        payload = {"weekly": {"mon": intervals}}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_too_many_exceptions_raises(self) -> None:
        exceptions = [
            {"date": (datetime.date(2027, 1, 1) + datetime.timedelta(days=i)).isoformat(), "closed": True}
            for i in range(MAX_EXCEPTIONS + 1)
        ]
        payload = {**_MINIMAL_VALID, "exceptions": exceptions}
        with pytest.raises(InvalidOpeningHours):
            parse_opening_hours(payload)

    def test_max_exceptions_accepted(self) -> None:
        exceptions = [
            {"date": (datetime.date(2027, 1, 1) + datetime.timedelta(days=i)).isoformat(), "closed": True}
            for i in range(MAX_EXCEPTIONS)
        ]
        # MAX_EXCEPTIONS closed exceptions + at least one open week slot.
        payload = {**_MINIMAL_VALID, "exceptions": exceptions}
        result = parse_opening_hours(payload)
        assert len(result.exceptions) == MAX_EXCEPTIONS


# ---------------------------------------------------------------------------
# Normalisation et to_jsonb
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_to_jsonb_contains_version(self) -> None:
        hours = parse_opening_hours(_MINIMAL_VALID)
        jsonb = to_jsonb(hours)
        assert jsonb["version"] == OPENING_HOURS_SCHEMA_VERSION

    def test_to_jsonb_contains_default_timezone(self) -> None:
        hours = parse_opening_hours(_MINIMAL_VALID)
        jsonb = to_jsonb(hours)
        assert jsonb["timezone"] == DEFAULT_TIMEZONE

    def test_to_jsonb_weekly_keys_lowercase(self) -> None:
        payload = {"weekly": {"MON": _SINGLE_INTERVAL}}
        hours = parse_opening_hours(payload)
        jsonb = to_jsonb(hours)
        assert "mon" in jsonb["weekly"]
        assert "MON" not in jsonb["weekly"]

    def test_to_jsonb_intervals_sorted(self) -> None:
        payload = {
            "weekly": {
                "mon": [
                    {"start": "14:00", "end": "18:00"},
                    {"start": "08:00", "end": "12:00"},
                ]
            }
        }
        hours = parse_opening_hours(payload)
        jsonb = to_jsonb(hours)
        intervals = jsonb["weekly"]["mon"]
        assert intervals[0]["start"] == "08:00"
        assert intervals[1]["start"] == "14:00"

    def test_to_jsonb_closed_days_excluded(self) -> None:
        # Day with [] → filtered out from weekly in the JSONB.
        payload = {"weekly": {"mon": _SINGLE_INTERVAL, "tue": []}}
        hours = parse_opening_hours(payload)
        jsonb = to_jsonb(hours)
        assert "tue" not in jsonb["weekly"]
        assert "mon" in jsonb["weekly"]

    def test_to_jsonb_exceptions_have_date_as_iso_string(self) -> None:
        payload = {
            **_MINIMAL_VALID,
            "exceptions": [{"date": "2026-08-07", "closed": True}],
        }
        hours = parse_opening_hours(payload)
        jsonb = to_jsonb(hours)
        assert jsonb["exceptions"][0]["date"] == "2026-08-07"

    def test_parse_to_jsonb_idempotent(self) -> None:
        payload = {
            "weekly": {
                "mon": _TWO_INTERVALS,
                "fri": [{"start": "09:00", "end": "17:00"}],
            },
            "exceptions": [
                {"date": "2026-08-07", "closed": True},
                {
                    "date": "2026-12-24",
                    "closed": False,
                    "intervals": [{"start": "08:00", "end": "13:00"}],
                },
            ],
        }
        hours_1 = parse_opening_hours(payload)
        jsonb = to_jsonb(hours_1)
        hours_2 = parse_opening_hours(jsonb)
        assert hours_1 == hours_2

    def test_parse_idempotent_single_interval(self) -> None:
        hours_1 = parse_opening_hours(_MINIMAL_VALID)
        hours_2 = parse_opening_hours(to_jsonb(hours_1))
        assert hours_1 == hours_2
