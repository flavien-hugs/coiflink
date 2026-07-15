"""Structure, validation et normalisation des **horaires d'ouverture** (US-2.2, #16).

Module de domaine **pur** (ADR-0008) : aucune dépendance FastAPI/SQLAlchemy/I/O.
Il fixe le **contrat JSONB** de la colonne `salons.opening_hours` (laissée `NULL`
à la création par #15) et porte les quatre dimensions de US-2.2 :

- **horaires par jour** : pour chaque jour de la semaine, une liste d'intervalles ;
- **jours fermés** : un jour sans intervalle (absent ou `[]`) est fermé ;
- **pauses** : plusieurs intervalles dans un même jour — le trou entre deux
  intervalles *est* la pause (ex. `08:00–12:00` puis `14:00–18:00`) ;
- **jours exceptionnels** : des surcharges **datées** (fermeture ou horaires
  exceptionnels pour une date précise).

Règles de validation (autorité métier, jamais une contrainte `CHECK` SQL) :

- clés de jour ⊂ `DAY_KEYS`, sans doublon ;
- heures `HH:MM` 24h (`00:00`–`23:59`), `end` strictement `>` `start` (pas
  d'intervalle nul, inversé, ni de passage minuit) ;
- intervalles d'un même jour triés et **non chevauchants** (l'adjacence
  `end == start` du suivant est autorisée — c'est une journée continue) ;
- exceptions à **dates distinctes** ; `closed=true` ⇒ aucun intervalle ;
  `closed=false` ⇒ au moins un intervalle valide ;
- **non-vacuité utile** : au moins un intervalle d'ouverture doit exister
  (hebdomadaire **ou** exception ouverte) — sans quoi un JSONB « configuré » mais
  entièrement fermé mentirait sur `is_bookable` (§8.3) ;
- **bornes de robustesse** : ≤ `MAX_INTERVALS_PER_DAY` intervalles par jour et
  ≤ `MAX_EXCEPTIONS` exceptions (budget latence/stockage, PRD §12).

Toute incohérence lève `InvalidOpeningHours` (message **neutre**, sans PII ni
détail SQL). `to_jsonb` produit la forme **canonique normalisée** (clés minuscules,
intervalles triés, `version`, `timezone`) écrite en base et relue telle quelle.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from coiflink_api.domain.errors import InvalidOpeningHours

# Clés de jour canoniques, dans l'ordre de la semaine (lun→dim).
DAY_KEYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Version du schéma JSONB (permet une évolution future sans ambiguïté).
OPENING_HOURS_SCHEMA_VERSION = 1

# Fuseau par défaut — marché MVP mono-région (Côte d'Ivoire, UTC+00). Non éditable
# dans l'UI ; stocké pour que la réservation (#21+) dispose déjà du champ.
DEFAULT_TIMEZONE = "Africa/Abidjan"

# Bornes de robustesse (anti-gonflement de la ligne JSONB).
MAX_INTERVALS_PER_DAY = 6
MAX_EXCEPTIONS = 366

# `HH:MM` 24h, `00:00`–`23:59` (zéro-padding imposé ⇒ comparaison lexicographique
# = comparaison chronologique).
_TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

_INTERVAL_KEYS = frozenset({"start", "end"})
_EXCEPTION_KEYS = frozenset({"date", "closed", "intervals"})
_TOP_LEVEL_KEYS = frozenset({"version", "timezone", "weekly", "exceptions"})


@dataclass(frozen=True)
class TimeInterval:
    """Intervalle d'ouverture `HH:MM`–`HH:MM` (24h), `end` strictement `>` `start`."""

    start: str
    end: str


@dataclass(frozen=True)
class DaySchedule:
    """Programme d'un jour : `intervals` vide ⇒ fermé ; `>1` ⇒ pause(s)."""

    day: str
    intervals: tuple[TimeInterval, ...]


@dataclass(frozen=True)
class ExceptionalDay:
    """Surcharge datée : `closed=True` ⇒ fermé ; sinon horaires exceptionnels."""

    date: datetime.date
    closed: bool
    intervals: tuple[TimeInterval, ...]


@dataclass(frozen=True)
class OpeningHours:
    """Forme canonique des horaires d'un salon (sérialisée en JSONB)."""

    version: int
    timezone: str
    weekly: tuple[DaySchedule, ...]
    exceptions: tuple[ExceptionalDay, ...]


def _parse_intervals(raw: object, *, context: str) -> tuple[TimeInterval, ...]:
    """Valide, ordonne et vérifie la non-chevauchance d'une liste d'intervalles."""

    if not isinstance(raw, list):
        raise InvalidOpeningHours("Les horaires doivent être une liste d'intervalles.")
    if len(raw) > MAX_INTERVALS_PER_DAY:
        raise InvalidOpeningHours(
            f"Trop d'intervalles pour {context} (maximum {MAX_INTERVALS_PER_DAY})."
        )

    parsed: list[TimeInterval] = []
    for item in raw:
        if not isinstance(item, dict) or not _INTERVAL_KEYS.issuperset(item.keys()):
            raise InvalidOpeningHours("Intervalle d'horaire mal formé.")
        start = item.get("start")
        end = item.get("end")
        if not isinstance(start, str) or not _TIME_RE.match(start):
            raise InvalidOpeningHours("Heure de début invalide (format attendu HH:MM).")
        if not isinstance(end, str) or not _TIME_RE.match(end):
            raise InvalidOpeningHours("Heure de fin invalide (format attendu HH:MM).")
        if end <= start:
            raise InvalidOpeningHours(
                "L'heure de fin doit être postérieure à l'heure de début."
            )
        parsed.append(TimeInterval(start=start, end=end))

    parsed.sort(key=lambda interval: interval.start)
    # Non-chevauchement : le début de chaque intervalle est ≥ à la fin du précédent
    # (l'adjacence `end == start` est tolérée — journée continue).
    for previous, current in zip(parsed, parsed[1:], strict=False):
        if current.start < previous.end:
            raise InvalidOpeningHours("Des intervalles d'horaires se chevauchent.")

    return tuple(parsed)


def _parse_weekly(raw: object) -> tuple[DaySchedule, ...]:
    """Valide le dict `{jour: [intervalles]}` ; jour absent ⇒ fermé."""

    if not isinstance(raw, dict):
        raise InvalidOpeningHours("Les horaires hebdomadaires sont mal formés.")

    schedules: list[DaySchedule] = []
    seen: set[str] = set()
    for day_key, intervals in raw.items():
        day = day_key.lower() if isinstance(day_key, str) else None
        if day not in DAY_KEYS:
            raise InvalidOpeningHours("Jour de la semaine inconnu.")
        if day in seen:
            raise InvalidOpeningHours("Jour de la semaine en double.")
        seen.add(day)
        schedules.append(
            DaySchedule(day=day, intervals=_parse_intervals(intervals, context=day))
        )

    # Ordre canonique (lun→dim) — seuls les jours ouverts sont conservés.
    schedules.sort(key=lambda schedule: DAY_KEYS.index(schedule.day))
    return tuple(schedule for schedule in schedules if schedule.intervals)


def _parse_date(raw: object) -> datetime.date:
    """Accepte une `date` ISO (`YYYY-MM-DD`) ou un objet `date` déjà désérialisé."""

    if isinstance(raw, datetime.date) and not isinstance(raw, datetime.datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError as exc:
            raise InvalidOpeningHours("Date d'exception invalide (attendu AAAA-MM-JJ).") from exc
    raise InvalidOpeningHours("Date d'exception invalide (attendu AAAA-MM-JJ).")


def _parse_exceptions(raw: object) -> tuple[ExceptionalDay, ...]:
    """Valide les surcharges datées : dates distinctes, cohérence `closed`/intervals."""

    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise InvalidOpeningHours("Les jours exceptionnels sont mal formés.")
    if len(raw) > MAX_EXCEPTIONS:
        raise InvalidOpeningHours(
            f"Trop de jours exceptionnels (maximum {MAX_EXCEPTIONS})."
        )

    exceptions: list[ExceptionalDay] = []
    seen: set[datetime.date] = set()
    for item in raw:
        if not isinstance(item, dict) or not _EXCEPTION_KEYS.issuperset(item.keys()):
            raise InvalidOpeningHours("Jour exceptionnel mal formé.")
        date = _parse_date(item.get("date"))
        if date in seen:
            raise InvalidOpeningHours("Deux jours exceptionnels portent la même date.")
        seen.add(date)

        closed = item.get("closed", False)
        if not isinstance(closed, bool):
            raise InvalidOpeningHours("Le champ « fermé » doit être un booléen.")
        intervals = _parse_intervals(
            item.get("intervals") or [], context=f"exception {date.isoformat()}"
        )
        if closed and intervals:
            raise InvalidOpeningHours(
                "Un jour fermé ne peut pas porter d'horaires d'ouverture."
            )
        if not closed and not intervals:
            raise InvalidOpeningHours(
                "Un jour exceptionnel ouvert doit porter au moins un intervalle."
            )
        exceptions.append(
            ExceptionalDay(date=date, closed=closed, intervals=intervals)
        )

    exceptions.sort(key=lambda exception: exception.date)
    return tuple(exceptions)


def _parse_timezone(raw: object) -> str:
    """Retourne le fuseau fourni (chaîne non vide) ou le défaut serveur."""

    if raw is None:
        return DEFAULT_TIMEZONE
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidOpeningHours("Fuseau horaire invalide.")
    return raw.strip()


def parse_opening_hours(payload: object) -> OpeningHours:
    """Construit, **valide** et **normalise** la structure d'horaires canonique.

    Rejette toute clé/valeur inattendue et toute incohérence (`InvalidOpeningHours`).
    La **non-vacuité utile** garantit qu'aucun horaire entièrement fermé n'est
    accepté : `is_bookable` (structurel) ne peut donc pas mentir (§8.3).
    """

    if not isinstance(payload, dict):
        raise InvalidOpeningHours("Structure d'horaires invalide.")
    if not _TOP_LEVEL_KEYS.issuperset(payload.keys()):
        raise InvalidOpeningHours("Champ d'horaires inattendu.")

    weekly = _parse_weekly(payload.get("weekly") or {})
    exceptions = _parse_exceptions(payload.get("exceptions"))
    timezone = _parse_timezone(payload.get("timezone"))

    has_weekly_opening = any(schedule.intervals for schedule in weekly)
    has_open_exception = any(
        not exception.closed and exception.intervals for exception in exceptions
    )
    if not has_weekly_opening and not has_open_exception:
        raise InvalidOpeningHours(
            "Les horaires doivent comporter au moins un créneau d'ouverture."
        )

    return OpeningHours(
        version=OPENING_HOURS_SCHEMA_VERSION,
        timezone=timezone,
        weekly=weekly,
        exceptions=exceptions,
    )


def to_jsonb(hours: OpeningHours) -> dict:
    """Sérialise la forme canonique **normalisée** en dict JSONB (cible de la base)."""

    return {
        "version": hours.version,
        "timezone": hours.timezone,
        "weekly": {
            schedule.day: [
                {"start": interval.start, "end": interval.end}
                for interval in schedule.intervals
            ]
            for schedule in hours.weekly
        },
        "exceptions": [
            {
                "date": exception.date.isoformat(),
                "closed": exception.closed,
                "intervals": [
                    {"start": interval.start, "end": interval.end}
                    for interval in exception.intervals
                ],
            }
            for exception in hours.exceptions
        ],
    }


__all__ = [
    "DAY_KEYS",
    "OPENING_HOURS_SCHEMA_VERSION",
    "DEFAULT_TIMEZONE",
    "MAX_INTERVALS_PER_DAY",
    "MAX_EXCEPTIONS",
    "TimeInterval",
    "DaySchedule",
    "ExceptionalDay",
    "OpeningHours",
    "parse_opening_hours",
    "to_jsonb",
]
