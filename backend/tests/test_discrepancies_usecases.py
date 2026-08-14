"""Tests unitaires — cas d'usage `ListCashDiscrepancies` (US-5.4, #36).

Tous les ports sont remplacés par des fakes (conftest.py) : pas de base, pas de réseau.

Couvre :
- page vide quand aucun écart ;
- un seul écart retourné sans filtre ;
- isolation par salon (écarts d'un autre salon exclus — §11.2) ;
- filtre `date_from` (exclut les écarts antérieurs) ;
- filtre `date_to` (exclut les écarts postérieurs) ;
- plage de dates : single-day, plage correcte ;
- pagination `limit`/`offset` ;
- `total` cohérent sous filtre (différent de la taille de la page) ;
- `total` sans filtre ;
- filtre sans correspondance → page vide + total = 0 ;
- tri déterministe `issued_date DESC, ticket_number DESC, queue_ticket_id DESC`
  (plus récent d'abord) ;
- `ListCashDiscrepancies` ne déclenche **aucune** écriture ni audit ;
- résolution `client_name` transmise depuis le dépôt.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from coiflink_api.application.discrepancies import ListCashDiscrepancies
from coiflink_api.domain.discrepancy import CashDiscrepancy, validate_discrepancy_filter

from .conftest import FakePaymentRepository

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")

_DATE_A = datetime.date(2026, 3, 1)    # plus ancien
_DATE_B = datetime.date(2026, 3, 15)   # intermédiaire
_DATE_C = datetime.date(2026, 3, 31)   # plus récent

_TICKET_EARLY = 3
_TICKET_LATE = 14

_NO_FILTER = validate_discrepancy_filter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_discrepancy(
    *,
    queue_ticket_id: uuid.UUID | None = None,
    salon_id: uuid.UUID = _SALON_ID,
    issued_date: datetime.date = _DATE_B,
    ticket_number: int = _TICKET_EARLY,
    customer_profile_id: uuid.UUID | None = None,
    expected_amount: decimal.Decimal = decimal.Decimal("5000.00"),
    client_name: str | None = None,
) -> CashDiscrepancy:
    return CashDiscrepancy(
        queue_ticket_id=queue_ticket_id or uuid.uuid4(),
        salon_id=salon_id,
        ticket_number=ticket_number,
        issued_date=issued_date,
        completed_at=datetime.datetime.combine(
            issued_date, datetime.time(10, 0), tzinfo=datetime.timezone.utc
        ),
        customer_profile_id=customer_profile_id or uuid.uuid4(),
        expected_amount=expected_amount,
        client_name=client_name,
    )


# ---------------------------------------------------------------------------
# Page vide / liste complète
# ---------------------------------------------------------------------------


class TestListCashDiscrepanciesEmpty:
    def test_no_discrepancies_returns_empty_page(self) -> None:
        repo = FakePaymentRepository()
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=50, offset=0
        )
        assert page == ()
        assert total == 0

    def test_single_discrepancy_returned(self) -> None:
        d = _make_discrepancy()
        repo = FakePaymentRepository(discrepancies=[d])
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=50, offset=0
        )
        assert total == 1
        assert len(page) == 1
        assert page[0].queue_ticket_id == d.queue_ticket_id

    def test_multiple_discrepancies_all_returned(self) -> None:
        ds = [_make_discrepancy(issued_date=_DATE_A),
              _make_discrepancy(issued_date=_DATE_B),
              _make_discrepancy(issued_date=_DATE_C)]
        repo = FakePaymentRepository(discrepancies=ds)
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=50, offset=0
        )
        assert total == 3
        assert len(page) == 3


# ---------------------------------------------------------------------------
# Isolation par salon (§11.2)
# ---------------------------------------------------------------------------


class TestListCashDiscrepanciesSalonIsolation:
    def test_other_salon_discrepancy_excluded(self) -> None:
        """Un écart du salon B est invisible depuis la requête du salon A."""
        d = _make_discrepancy(salon_id=_OTHER_SALON_ID)
        repo = FakePaymentRepository(discrepancies=[d])
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=50, offset=0
        )
        assert total == 0
        assert page == ()

    def test_only_own_salon_discrepancies_returned(self) -> None:
        da = _make_discrepancy(salon_id=_SALON_ID, issued_date=_DATE_B)
        db = _make_discrepancy(salon_id=_OTHER_SALON_ID, issued_date=_DATE_B)
        repo = FakePaymentRepository(discrepancies=[da, db])
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=50, offset=0
        )
        assert total == 1
        assert page[0].queue_ticket_id == da.queue_ticket_id


# ---------------------------------------------------------------------------
# Filtre par date
# ---------------------------------------------------------------------------


class TestListCashDiscrepanciesDateFilter:
    def test_date_from_excludes_earlier(self) -> None:
        old = _make_discrepancy(issued_date=_DATE_A)
        recent = _make_discrepancy(issued_date=_DATE_C)
        repo = FakePaymentRepository(discrepancies=[old, recent])
        f = validate_discrepancy_filter(date_from=_DATE_B)
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].issued_date == _DATE_C

    def test_date_to_excludes_later(self) -> None:
        old = _make_discrepancy(issued_date=_DATE_A)
        recent = _make_discrepancy(issued_date=_DATE_C)
        repo = FakePaymentRepository(discrepancies=[old, recent])
        f = validate_discrepancy_filter(date_to=_DATE_B)
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].issued_date == _DATE_A

    def test_date_range_includes_both_bounds(self) -> None:
        da = _make_discrepancy(issued_date=_DATE_A)
        db = _make_discrepancy(issued_date=_DATE_B)
        dc = _make_discrepancy(issued_date=_DATE_C)
        repo = FakePaymentRepository(discrepancies=[da, db, dc])
        f = validate_discrepancy_filter(date_from=_DATE_A, date_to=_DATE_B)
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 2
        dates = {d.issued_date for d in page}
        assert _DATE_A in dates
        assert _DATE_B in dates
        assert _DATE_C not in dates

    def test_single_day_filter_matches_only_that_day(self) -> None:
        d_match = _make_discrepancy(issued_date=_DATE_B)
        d_miss = _make_discrepancy(issued_date=_DATE_A)
        repo = FakePaymentRepository(discrepancies=[d_match, d_miss])
        f = validate_discrepancy_filter(date_from=_DATE_B, date_to=_DATE_B)
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].issued_date == _DATE_B

    def test_no_match_returns_empty(self) -> None:
        d = _make_discrepancy(issued_date=_DATE_A)
        repo = FakePaymentRepository(discrepancies=[d])
        f = validate_discrepancy_filter(date_from=_DATE_C, date_to=_DATE_C)
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 0
        assert page == ()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestListCashDiscrepanciesPagination:
    def _seed_n(self, n: int) -> FakePaymentRepository:
        ds = [
            _make_discrepancy(
                issued_date=datetime.date(2026, 1, i + 1),
            )
            for i in range(n)
        ]
        return FakePaymentRepository(discrepancies=ds)

    def test_limit_respected(self) -> None:
        repo = self._seed_n(10)
        page, _ = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=3, offset=0
        )
        assert len(page) == 3

    def test_offset_respected(self) -> None:
        repo = self._seed_n(5)
        page_0, _ = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=2, offset=0
        )
        page_2, _ = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=2, offset=2
        )
        ids_0 = {d.queue_ticket_id for d in page_0}
        ids_2 = {d.queue_ticket_id for d in page_2}
        assert ids_0.isdisjoint(ids_2), "offset ne doit pas chevaucher la première page"

    def test_total_reflects_full_filtered_count(self) -> None:
        """Le `total` reflète la cardinalité du filtre, pas la taille de la page."""
        repo = self._seed_n(10)
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=3, offset=0
        )
        assert total == 10
        assert len(page) == 3

    def test_offset_beyond_total_returns_empty(self) -> None:
        repo = self._seed_n(3)
        page, total = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=100
        )
        assert total == 3
        assert page == ()


# ---------------------------------------------------------------------------
# Tri déterministe (plus récent d'abord)
# ---------------------------------------------------------------------------


class TestListCashDiscrepanciesSortOrder:
    def test_most_recent_date_first(self) -> None:
        old = _make_discrepancy(issued_date=_DATE_A)
        recent = _make_discrepancy(issued_date=_DATE_C)
        repo = FakePaymentRepository(discrepancies=[old, recent])
        page, _ = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=0
        )
        assert page[0].issued_date == _DATE_C
        assert page[1].issued_date == _DATE_A

    def test_same_date_higher_ticket_number_first(self) -> None:
        """À date égale, le numéro de ticket le plus élevé apparaît en tête."""
        early = _make_discrepancy(issued_date=_DATE_B, ticket_number=_TICKET_EARLY)
        late = _make_discrepancy(issued_date=_DATE_B, ticket_number=_TICKET_LATE)
        repo = FakePaymentRepository(discrepancies=[early, late])
        page, _ = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=0
        )
        assert page[0].ticket_number == _TICKET_LATE
        assert page[1].ticket_number == _TICKET_EARLY

    def test_insertion_order_irrelevant(self) -> None:
        """Le tri est stable quel que soit l'ordre d'insertion."""
        d1 = _make_discrepancy(issued_date=_DATE_C)  # récent inséré en premier
        d2 = _make_discrepancy(issued_date=_DATE_A)  # ancien inséré en second
        repo = FakePaymentRepository(discrepancies=[d1, d2])
        page, _ = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=0
        )
        assert page[0].issued_date >= page[1].issued_date


# ---------------------------------------------------------------------------
# Lecture pure — aucune écriture / aucun audit
# ---------------------------------------------------------------------------


class TestListCashDiscrepanciesPurity:
    def test_no_payments_created(self) -> None:
        repo = FakePaymentRepository()
        ListCashDiscrepancies(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=10, offset=0)
        assert repo.created == []

    def test_no_mark_adjusted_called(self) -> None:
        d = _make_discrepancy()
        repo = FakePaymentRepository(discrepancies=[d])
        ListCashDiscrepancies(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=10, offset=0)
        assert repo.mark_adjusted_calls == []

    def test_list_calls_both_repo_methods(self) -> None:
        """Use case appelle `list_*` et `count_*` (page + total)."""
        repo = FakePaymentRepository()
        ListCashDiscrepancies(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=10, offset=0)
        assert len(repo.list_completed_calls) == 1
        assert len(repo.count_completed_calls) == 1

    def test_repo_calls_use_correct_salon_id(self) -> None:
        repo = FakePaymentRepository()
        ListCashDiscrepancies(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=5, offset=0)
        salon_id_list, _, _, _ = repo.list_completed_calls[0]
        salon_id_count, _ = repo.count_completed_calls[0]
        assert salon_id_list == _SALON_ID
        assert salon_id_count == _SALON_ID


# ---------------------------------------------------------------------------
# Résolution du nom de client
# ---------------------------------------------------------------------------


class TestListCashDiscrepanciesClientName:
    def test_client_name_preserved_when_set(self) -> None:
        d = _make_discrepancy(client_name="Awa Koné")
        repo = FakePaymentRepository(discrepancies=[d])
        page, _ = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=0
        )
        assert page[0].client_name == "Awa Koné"

    def test_client_name_none_when_not_set(self) -> None:
        d = _make_discrepancy(client_name=None)
        repo = FakePaymentRepository(discrepancies=[d])
        page, _ = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=0
        )
        assert page[0].client_name is None

    def test_expected_amount_preserved(self) -> None:
        d = _make_discrepancy(expected_amount=decimal.Decimal("12500.00"))
        repo = FakePaymentRepository(discrepancies=[d])
        page, _ = ListCashDiscrepancies(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=0
        )
        assert page[0].expected_amount == decimal.Decimal("12500.00")
