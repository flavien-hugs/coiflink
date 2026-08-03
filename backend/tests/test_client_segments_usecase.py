"""Tests unitaires — cas d'usage `SummarizeActiveClients` (US-6.4, #42).

Port remplacé par un fake en mémoire : aucune I/O, aucune base.

Couvre :
- `segment_active_clients` appelé **une** fois avec `HISTORY_STATUSES`
  (`COMPLETED`) — jamais soumis par l'appelant (§8.1, « réalisées uniquement ») ;
- `salon_id` et les bornes `date_from`/`date_to` transmis tels quels au port ;
- `ClientSegments` assemblé correctement (compteurs, période échouée) ;
- cas « aucun profil » → tous les compteurs à `0` (état vide légitime) ;
- lecture pure : aucune méthode d'écriture déclenchée (§11.4).
"""

from __future__ import annotations

import datetime
import uuid

from coiflink_api.application.client_segments import SummarizeActiveClients
from coiflink_api.domain.client_segments import ClientVisitProfile
from coiflink_api.domain.visit import HISTORY_STATUSES

# ---------------------------------------------------------------------------
# Fake AppointmentRepository (lecture seule)
# ---------------------------------------------------------------------------


class FakeActiveClientsAppointmentRepository:
    """Fake du port `AppointmentRepository` pour `SummarizeActiveClients` (#42).

    `profiles` est le tuple de `ClientVisitProfile` retourné par
    `segment_active_clients`. `calls` enregistre chaque appel pour vérification.
    Les méthodes de mutation lèvent `NotImplementedError` : toute écriture
    accidentelle est immédiatement visible (lecture pure, §11.4).
    """

    def __init__(
        self, profiles: tuple[ClientVisitProfile, ...] = ()
    ) -> None:
        self._profiles = profiles
        self.calls: list[dict] = []

    def segment_active_clients(  # type: ignore[no-untyped-def]
        self, salon_id, *, statuses, date_from, date_to
    ):
        self.calls.append(
            {
                "salon_id": salon_id,
                "statuses": statuses,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return self._profiles

    def create(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError("SummarizeActiveClients ne doit pas écrire")

    def update(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def cancel(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def set_status(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def assign_hairdresser(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def booked_slots(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def get_owned(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def get_in_salon(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_client(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_salon(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def list_for_hairdresser(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def count_by_status_for_day(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def demand_by_service(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000042")
_DATE_FROM = datetime.date(2026, 8, 1)
_DATE_TO = datetime.date(2026, 8, 31)

_PROFILE_NEW = ClientVisitProfile(
    first_visit=datetime.date(2026, 8, 15),
    visits_in_period=1,
    visits_before=0,
)
_PROFILE_RECURRING = ClientVisitProfile(
    first_visit=datetime.date(2026, 7, 1),
    visits_in_period=2,
    visits_before=3,
)
_PROFILE_INACTIVE = ClientVisitProfile(
    first_visit=datetime.date(2026, 6, 1),
    visits_in_period=0,
    visits_before=1,
)


# ---------------------------------------------------------------------------
# Arguments transmis au port
# ---------------------------------------------------------------------------


class TestSummarizeActiveClientsPortArgs:
    def test_segment_active_clients_called_once(self) -> None:
        repo = FakeActiveClientsAppointmentRepository()
        SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert len(repo.calls) == 1

    def test_salon_id_forwarded(self) -> None:
        repo = FakeActiveClientsAppointmentRepository()
        SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert repo.calls[0]["salon_id"] == _SALON_ID

    def test_history_statuses_imposed(self) -> None:
        """Seul HISTORY_STATUSES (COMPLETED) est imposé — jamais soumis par l'appelant (§8.1)."""
        repo = FakeActiveClientsAppointmentRepository()
        SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert repo.calls[0]["statuses"] == HISTORY_STATUSES

    def test_completed_in_imposed_statuses(self) -> None:
        repo = FakeActiveClientsAppointmentRepository()
        SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert "COMPLETED" in repo.calls[0]["statuses"]

    def test_date_from_forwarded(self) -> None:
        repo = FakeActiveClientsAppointmentRepository()
        SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert repo.calls[0]["date_from"] == _DATE_FROM

    def test_date_to_forwarded(self) -> None:
        repo = FakeActiveClientsAppointmentRepository()
        SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert repo.calls[0]["date_to"] == _DATE_TO

    def test_both_date_bounds_forwarded(self) -> None:
        repo = FakeActiveClientsAppointmentRepository()
        SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        call = repo.calls[0]
        assert call["date_from"] == _DATE_FROM
        assert call["date_to"] == _DATE_TO

    def test_no_write_triggered(self) -> None:
        """Lecture pure : aucune méthode d'écriture ne doit être appelée (§11.4)."""
        repo = FakeActiveClientsAppointmentRepository()
        SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        # Si une méthode d'écriture avait été appelée, NotImplementedError aurait été levée.


# ---------------------------------------------------------------------------
# Assemblage du ClientSegments
# ---------------------------------------------------------------------------


class TestSummarizeActiveClientsAssembly:
    def test_new_count_correct(self) -> None:
        repo = FakeActiveClientsAppointmentRepository(
            profiles=(_PROFILE_NEW, _PROFILE_NEW, _PROFILE_RECURRING)
        )
        result = SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert result.new == 2

    def test_recurring_count_correct(self) -> None:
        repo = FakeActiveClientsAppointmentRepository(
            profiles=(_PROFILE_NEW, _PROFILE_RECURRING)
        )
        result = SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert result.recurring == 1

    def test_inactive_count_correct(self) -> None:
        repo = FakeActiveClientsAppointmentRepository(
            profiles=(_PROFILE_INACTIVE, _PROFILE_INACTIVE)
        )
        result = SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert result.inactive == 2

    def test_active_equals_new_plus_recurring(self) -> None:
        repo = FakeActiveClientsAppointmentRepository(
            profiles=(_PROFILE_NEW, _PROFILE_RECURRING, _PROFILE_INACTIVE)
        )
        result = SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert result.active == result.new + result.recurring

    def test_date_from_echoed_in_result(self) -> None:
        repo = FakeActiveClientsAppointmentRepository()
        result = SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert result.date_from == _DATE_FROM

    def test_date_to_echoed_in_result(self) -> None:
        repo = FakeActiveClientsAppointmentRepository()
        result = SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert result.date_to == _DATE_TO

    def test_result_has_no_pii(self) -> None:
        """Le résultat ne porte aucun identifiant de client (§11.3)."""
        repo = FakeActiveClientsAppointmentRepository(
            profiles=(_PROFILE_NEW, _PROFILE_RECURRING)
        )
        result = SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )
        assert not hasattr(result, "client_id")
        assert not hasattr(result, "user_id")
        assert not hasattr(result, "appointment_id")


# ---------------------------------------------------------------------------
# Cas « aucun profil »
# ---------------------------------------------------------------------------


class TestSummarizeActiveClientsEmpty:
    def _execute(self):  # type: ignore[no-untyped-def]
        repo = FakeActiveClientsAppointmentRepository(profiles=())
        return SummarizeActiveClients(repo).execute(
            _SALON_ID, date_from=_DATE_FROM, date_to=_DATE_TO
        )

    def test_new_zero(self) -> None:
        assert self._execute().new == 0

    def test_recurring_zero(self) -> None:
        assert self._execute().recurring == 0

    def test_inactive_zero(self) -> None:
        assert self._execute().inactive == 0

    def test_active_zero(self) -> None:
        assert self._execute().active == 0

    def test_empty_not_an_error(self) -> None:
        """Un salon sans RDV `COMPLETED` retourne un résultat vide, pas une erreur."""
        self._execute()
