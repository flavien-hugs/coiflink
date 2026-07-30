"""Tests unitaires — `domain/time_window.py`.

Couvre directement les symboles exportés (`SALON_TIMEZONE`, `day_start_utc`,
`day_end_utc`) **sans** passer par `validate_platform_summary_filter`. Les
tests UTC vérifient qu'Africa/Abidjan = UTC+0 (convention #21) : la conversion
est une identité pour les dates — `day_start_utc(d)` retourne exactement
`datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=UTC)`.

Aucun I/O — domaine pur.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from coiflink_api.domain.time_window import SALON_TIMEZONE, day_end_utc, day_start_utc

# ---------------------------------------------------------------------------
# Dates réutilisées
# ---------------------------------------------------------------------------

_DATE_A = datetime.date(2026, 3, 1)
_DATE_B = datetime.date(2026, 3, 31)
_DATE_C = datetime.date(2026, 4, 15)

_UTC = datetime.timezone.utc


# ---------------------------------------------------------------------------
# SALON_TIMEZONE — Africa/Abidjan = UTC+0
# ---------------------------------------------------------------------------


class TestSalonTimezone:
    def test_is_africa_abidjan(self) -> None:
        assert SALON_TIMEZONE == ZoneInfo("Africa/Abidjan")

    def test_key_is_africa_abidjan(self) -> None:
        assert SALON_TIMEZONE.key == "Africa/Abidjan"

    def test_offset_is_zero(self) -> None:
        """Africa/Abidjan = UTC+0 : décalage nul pour toute date civile."""
        ref = datetime.datetime(2026, 3, 15, 12, 0, 0, tzinfo=SALON_TIMEZONE)
        assert ref.utcoffset() == datetime.timedelta(0)

    def test_offset_is_zero_in_northern_winter(self) -> None:
        """Africa/Abidjan ne pratique pas le DST : UTC+0 toute l'année."""
        ref = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=SALON_TIMEZONE)
        assert ref.utcoffset() == datetime.timedelta(0)


# ---------------------------------------------------------------------------
# day_start_utc — borne basse UTC du jour civil
# ---------------------------------------------------------------------------


class TestDayStartUtc:
    def test_returns_datetime(self) -> None:
        assert isinstance(day_start_utc(_DATE_A), datetime.datetime)

    def test_is_timezone_aware(self) -> None:
        assert day_start_utc(_DATE_A).tzinfo is not None

    def test_hour_is_midnight(self) -> None:
        assert day_start_utc(_DATE_A).hour == 0

    def test_minute_is_zero(self) -> None:
        assert day_start_utc(_DATE_A).minute == 0

    def test_second_is_zero(self) -> None:
        assert day_start_utc(_DATE_A).second == 0

    def test_microsecond_is_zero(self) -> None:
        assert day_start_utc(_DATE_A).microsecond == 0

    def test_date_year_preserved(self) -> None:
        assert day_start_utc(_DATE_A).year == _DATE_A.year

    def test_date_month_preserved(self) -> None:
        assert day_start_utc(_DATE_A).month == _DATE_A.month

    def test_date_day_preserved(self) -> None:
        assert day_start_utc(_DATE_A).day == _DATE_A.day

    def test_africa_abidjan_utc_plus_zero_no_shift(self) -> None:
        """Africa/Abidjan = UTC+0 : aucun décalage — le résultat est minuit UTC."""
        result = day_start_utc(_DATE_A)
        expected = datetime.datetime(2026, 3, 1, 0, 0, 0, 0, tzinfo=_UTC)
        assert result == expected

    def test_another_date(self) -> None:
        result = day_start_utc(_DATE_C)
        expected = datetime.datetime(2026, 4, 15, 0, 0, 0, 0, tzinfo=_UTC)
        assert result == expected

    def test_different_dates_produce_different_results(self) -> None:
        assert day_start_utc(_DATE_A) != day_start_utc(_DATE_B)

    def test_result_is_before_day_end(self) -> None:
        assert day_start_utc(_DATE_A) < day_end_utc(_DATE_A)


# ---------------------------------------------------------------------------
# day_end_utc — borne haute UTC du jour civil (23:59:59.999999)
# ---------------------------------------------------------------------------


class TestDayEndUtc:
    def test_returns_datetime(self) -> None:
        assert isinstance(day_end_utc(_DATE_B), datetime.datetime)

    def test_is_timezone_aware(self) -> None:
        assert day_end_utc(_DATE_B).tzinfo is not None

    def test_hour_is_23(self) -> None:
        assert day_end_utc(_DATE_B).hour == 23

    def test_minute_is_59(self) -> None:
        assert day_end_utc(_DATE_B).minute == 59

    def test_second_is_59(self) -> None:
        assert day_end_utc(_DATE_B).second == 59

    def test_microsecond_is_999999(self) -> None:
        assert day_end_utc(_DATE_B).microsecond == 999999

    def test_date_year_preserved(self) -> None:
        assert day_end_utc(_DATE_B).year == _DATE_B.year

    def test_date_month_preserved(self) -> None:
        assert day_end_utc(_DATE_B).month == _DATE_B.month

    def test_date_day_preserved(self) -> None:
        assert day_end_utc(_DATE_B).day == _DATE_B.day

    def test_africa_abidjan_utc_plus_zero_no_shift(self) -> None:
        """Africa/Abidjan = UTC+0 : aucun décalage — le résultat est 23:59:59.999999 UTC."""
        result = day_end_utc(_DATE_B)
        expected = datetime.datetime(2026, 3, 31, 23, 59, 59, 999999, tzinfo=_UTC)
        assert result == expected

    def test_another_date(self) -> None:
        result = day_end_utc(_DATE_C)
        expected = datetime.datetime(2026, 4, 15, 23, 59, 59, 999999, tzinfo=_UTC)
        assert result == expected

    def test_different_dates_produce_different_results(self) -> None:
        assert day_end_utc(_DATE_A) != day_end_utc(_DATE_C)

    def test_start_strictly_before_end_same_day(self) -> None:
        """La borne basse est strictement inférieure à la borne haute du même jour."""
        assert day_start_utc(_DATE_A) < day_end_utc(_DATE_A)

    def test_full_day_span_microseconds(self) -> None:
        """[00:00:00 → 23:59:59.999999] = 86 400 000 000 µs − 1 µs."""
        span = day_end_utc(_DATE_A) - day_start_utc(_DATE_A)
        assert span.total_seconds() == 86400 - 1 / 1_000_000
