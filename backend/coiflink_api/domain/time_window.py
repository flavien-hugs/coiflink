"""Conversion « jour civil `Africa/Abidjan` → bornes UTC inclusives » (domaine pur).

Petit module **partagé** portant la logique de fuseau des lectures financières :
le fuseau du salon (`SALON_TIMEZONE`, `Africa/Abidjan` = UTC+0, convention #21) et
la conversion d'un **jour civil** en bornes `datetime` UTC **inclusives** —
`[jour 00:00:00, jour 23:59:59.999999]` — pour comparer directement à une colonne
`created_at` (`timezone-aware`).

Extrait de `domain/transaction.py` (#35) pour être réutilisé sans duplication par
les autres surfaces filtrées par plage de dates sur `created_at` (p. ex. la
supervision agrégée des transactions, #37). `transaction.py` ré-exporte ces
symboles pour ne pas casser les imports existants. Conforme à l'hexagonal
(ADR-0008) : aucune dépendance framework/I/O.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

# Fuseau des jours civils du salon (Africa/Abidjan = UTC+0, convention #21).
SALON_TIMEZONE = ZoneInfo("Africa/Abidjan")


def day_start_utc(day: datetime.date) -> datetime.datetime:
    """Borne basse UTC (inclusive) du jour civil `Africa/Abidjan` (00:00:00)."""

    local = datetime.datetime.combine(day, datetime.time.min, tzinfo=SALON_TIMEZONE)
    return local.astimezone(datetime.timezone.utc)


def day_end_utc(day: datetime.date) -> datetime.datetime:
    """Borne haute UTC (inclusive) du jour civil `Africa/Abidjan` (23:59:59.999999)."""

    local = datetime.datetime.combine(
        day, datetime.time(23, 59, 59, 999999), tzinfo=SALON_TIMEZONE
    )
    return local.astimezone(datetime.timezone.utc)


__all__ = ["SALON_TIMEZONE", "day_start_utc", "day_end_utc"]
