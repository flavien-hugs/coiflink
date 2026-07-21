"""Moteur de **disponibilité** : calcul pur des créneaux libres (US-3.7, #21).

Module de domaine **pur** (ADR-0008) : aucune dépendance FastAPI/SQLAlchemy/I/O.
Il exploite les **horaires d'ouverture** (`domain/opening_hours.py`, #16), la
**durée** d'une prestation (`domain/service.py`, #17) et la liste des créneaux
**déjà réservés** pour produire, de façon **déterministe**, les créneaux
réservables d'une date et d'un coiffeur donnés.

Hypothèses (spec §Goals, §Risks) :

- **Fuseau Africa/Abidjan = UTC+0** : cohérent avec la colonne générée `slot
  tsrange` du schéma (non-`tstzrange`). Les `datetime.time` du domaine sont donc
  interprétés « heure locale = UTC » ; `now` (exclusion des créneaux passés) est un
  `datetime` **naïf** dans ce même repère.
- **Créneau fermé-ouvert `[start, end)`** : deux créneaux dos-à-dos (`end == start`)
  ne sont **pas** en conflit — même sémantique que l'opérateur `&&` de `tsrange` et
  que l'adjacence tolérée des intervalles d'horaires (#16).

Le moteur ne porte **pas** la garantie anti double-réservation : celle-ci est
portée par la contrainte d'exclusion PostgreSQL `ex_appointments_hairdresser_slot`
(schéma #3). Ici, la vérification de disponibilité n'est qu'une **aide** (UX et
défense en profondeur), jamais le juge de dernier ressort.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from coiflink_api.domain.opening_hours import DAY_KEYS, OpeningHours

# Granularité de la grille de créneaux par défaut (spec §Open Questions : pas
# paramétrable, valeur MVP 15 min). Un pas plus fin densifie l'offre de créneaux.
DEFAULT_GRANULARITY_MINUTES = 15

# Bornes d'une journée en minutes (00:00 inclus → 24:00 exclu). Les heures
# d'ouverture (#16) sont bornées à `23:59`, donc tout créneau valide reste < 1440.
_MINUTES_PER_DAY = 24 * 60


def _time_to_minutes(value: datetime.time) -> int:
    """Minutes écoulées depuis minuit pour une `time` (secondes ignorées)."""

    return value.hour * 60 + value.minute


def _minutes_to_time(minutes: int) -> datetime.time:
    """`time` correspondant à un nombre de minutes depuis minuit (`0 ≤ m < 1440`)."""

    return datetime.time(hour=minutes // 60, minute=minutes % 60)


@dataclass(frozen=True)
class SlotRange:
    """Créneau **fermé-ouvert** `[start, end)` daté (`date`, `start`, `end`).

    L'adjacence `end == start` de deux créneaux n'est pas un conflit (cf. module).
    """

    date: datetime.date
    start: datetime.time
    end: datetime.time


def overlaps(first: SlotRange, second: SlotRange) -> bool:
    """Vrai si deux créneaux **se chevauchent** (intersection non vide).

    Chevauchement strict fermé-ouvert : `a.start < b.end and b.start < a.end`.
    L'adjacence (`a.end == b.start`) n'est **pas** un chevauchement. Deux créneaux
    de dates différentes ne se chevauchent jamais.
    """

    if first.date != second.date:
        return False
    return first.start < second.end and second.start < first.end


def intervals_for_date(
    hours: OpeningHours, date: datetime.date
) -> tuple[tuple[int, int], ...]:
    """Intervalles d'ouverture **effectifs** d'une date, en minutes `(start, end)`.

    Une **exception datée** (`ExceptionalDay`) **prime** sur le programme
    hebdomadaire : fermée ⇒ `()` (aucun créneau), ouverte ⇒ ses intervalles. En
    l'absence d'exception, le `DaySchedule` du jour de la semaine
    (`DAY_KEYS[date.weekday()]`) est retenu, ou `()` si le jour est fermé/absent.
    """

    for exception in hours.exceptions:
        if exception.date == date:
            if exception.closed:
                return ()
            return tuple(
                (_time_to_minutes_str(i.start), _time_to_minutes_str(i.end))
                for i in exception.intervals
            )

    day_key = DAY_KEYS[date.weekday()]
    for schedule in hours.weekly:
        if schedule.day == day_key:
            return tuple(
                (_time_to_minutes_str(i.start), _time_to_minutes_str(i.end))
                for i in schedule.intervals
            )
    return ()


def _time_to_minutes_str(value: str) -> int:
    """Minutes depuis minuit d'une heure `HH:MM` (validée par #16)."""

    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def free_slots(
    hours: OpeningHours,
    date: datetime.date,
    duration_minutes: int,
    booked: tuple[SlotRange, ...],
    *,
    granularity_minutes: int = DEFAULT_GRANULARITY_MINUTES,
    now: datetime.datetime | None = None,
    min_lead_minutes: int = 0,
) -> tuple[SlotRange, ...]:
    """Créneaux **libres** de `duration_minutes` pour `date`, triés et dédupliqués.

    Pour chaque intervalle d'ouverture effectif (`intervals_for_date`), génère les
    créneaux candidats de longueur `duration_minutes` par pas de
    `granularity_minutes`, en ne gardant que ceux **entièrement contenus** dans
    l'intervalle (une prestation qui ne « rentre » pas est écartée). Sont **exclus**
    les créneaux qui **chevauchent** un `booked` et, quand `now` est fourni, les
    créneaux **passés** (début `< now + min_lead_minutes`).

    Garanties : `granularity_minutes` et `duration_minutes` doivent être `> 0`
    (contrat du domaine — la durée d'une prestation est déjà `> 0`, #17).
    """

    if duration_minutes <= 0 or granularity_minutes <= 0:
        return ()

    now_minute = None
    if now is not None:
        # Position de `now` (+ délai minimal) dans la journée `date`, en minutes.
        delta = datetime.datetime.combine(date, datetime.time()) - datetime.datetime(
            now.year, now.month, now.day
        )
        offset_days_minutes = int(delta.total_seconds() // 60)
        threshold = _time_to_minutes(now.time()) + min_lead_minutes
        # Minute (dans `date`) avant laquelle un créneau est « passé ».
        now_minute = threshold - offset_days_minutes

    slots: list[SlotRange] = []
    seen: set[tuple[int, int]] = set()
    for interval_start, interval_end in intervals_for_date(hours, date):
        candidate = interval_start
        while candidate + duration_minutes <= interval_end:
            slot_start, slot_end = candidate, candidate + duration_minutes
            candidate += granularity_minutes
            if now_minute is not None and slot_start < now_minute:
                continue
            key = (slot_start, slot_end)
            if key in seen:
                continue
            slot = SlotRange(
                date=date,
                start=_minutes_to_time(slot_start),
                end=_minutes_to_time(slot_end),
            )
            if any(overlaps(slot, taken) for taken in booked):
                continue
            seen.add(key)
            slots.append(slot)

    slots.sort(key=lambda s: (s.start, s.end))
    return tuple(slots)


def is_offered(
    hours: OpeningHours,
    slot: SlotRange,
    duration_minutes: int,
    booked: tuple[SlotRange, ...],
    *,
    granularity_minutes: int = DEFAULT_GRANULARITY_MINUTES,
    now: datetime.datetime | None = None,
) -> bool:
    """Vrai si `slot` figure dans l'offre réservable (défense en profondeur).

    Prédicat utilisé par `BookAppointment` **avant** l'arbitrage base : rejette un
    créneau hors horaires, mal aligné sur la grille, d'une durée incohérente, passé
    ou déjà occupé. La longueur du `slot` doit être **exactement** `duration_minutes`.
    """

    if _time_to_minutes(slot.end) - _time_to_minutes(slot.start) != duration_minutes:
        return False
    candidates = free_slots(
        hours,
        slot.date,
        duration_minutes,
        booked,
        granularity_minutes=granularity_minutes,
        now=now,
    )
    return slot in candidates


def add_minutes(start: datetime.time, minutes: int) -> datetime.time | None:
    """`start + minutes` en `time`, ou `None` si le résultat franchit minuit.

    Un créneau qui déborderait sur le lendemain n'est pas modélisable par le schéma
    (`slot` = plage intra-journée) : l'appelant traduit `None` en indisponibilité.
    """

    total = _time_to_minutes(start) + minutes
    if total >= _MINUTES_PER_DAY:
        return None
    return _minutes_to_time(total)


__all__ = [
    "DEFAULT_GRANULARITY_MINUTES",
    "SlotRange",
    "overlaps",
    "intervals_for_date",
    "free_slots",
    "is_offered",
    "add_minutes",
]
