"""Tests unitaires — cas d'usage `ListTransactions` (US-5.2, #35).

Tous les ports sont remplacés par des fakes (conftest.py) : pas de base, pas de réseau.

Couvre :
- page vide quand aucun paiement ;
- tous les paiements retournés sans filtre ;
- isolation par salon (paiements d'un autre salon exclus, même sans filtre) ;
- filtrage par `payment_method` ;
- filtrage par `amount_min` / `amount_max` ;
- filtrage par `client_id` ;
- filtrage par plage de dates (`created_at_from`/`created_at_to`) ;
- combinaison de filtres en **ET** ;
- pagination `limit`/`offset` ;
- `total` cohérent sous filtre (et sans filtre) ;
- filtre sans correspondance → page vide + total = 0 ;
- tri déterministe `created_at DESC, id DESC` (plus récent d'abord) ;
- `ListTransactions` ne déclenche **aucune** écriture ni audit ;
- résolution `client_name` depuis `client_names` du fake.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from coiflink_api.application.transactions import ListTransactions
from coiflink_api.domain.enums import PaymentStatus
from coiflink_api.domain.payment import Payment
from coiflink_api.domain.transaction import validate_transaction_filter

from .conftest import FakeAuditLog, FakePaymentRepository

# ---------------------------------------------------------------------------
# Constantes partagées
# ---------------------------------------------------------------------------

_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_ACTOR_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_CLIENT_A = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_CLIENT_B = uuid.UUID("cccccccc-0000-0000-0000-000000000002")
_SERVICE_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")

# Deux horodatages distincts pour tester le tri / les filtres de date.
_AT_1 = datetime.datetime(2026, 3, 1, 8, 0, 0, tzinfo=datetime.timezone.utc)   # plus ancien
_AT_2 = datetime.datetime(2026, 3, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)  # plus récent

# Filtre vide (pas de contrainte).
_NO_FILTER = validate_transaction_filter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payment(
    *,
    payment_id: uuid.UUID | None = None,
    salon_id: uuid.UUID = _SALON_ID,
    amount: decimal.Decimal = decimal.Decimal("5000.00"),
    payment_method: str = "CASH",
    client_id: uuid.UUID | None = None,
    status: str = PaymentStatus.VALIDATED.value,
    created_at: datetime.datetime = _AT_1,
) -> Payment:
    return Payment(
        id=payment_id or uuid.uuid4(),
        salon_id=salon_id,
        amount=amount,
        currency="XOF",
        payment_method=payment_method,
        status=status,
        recorded_by=_ACTOR_ID,
        appointment_id=None,
        service_id=_SERVICE_ID,
        client_id=client_id,
        reference=None,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# Page vide / liste complète
# ---------------------------------------------------------------------------


class TestListTransactionsEmpty:
    def test_no_payments_returns_empty_page(self) -> None:
        repo = FakePaymentRepository()
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=50, offset=0
        )
        assert page == ()
        assert total == 0

    def test_single_payment_returned(self) -> None:
        p = _make_payment()
        repo = FakePaymentRepository(payments=[p])
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=50, offset=0
        )
        assert total == 1
        assert len(page) == 1
        assert page[0].payment.id == p.id


# ---------------------------------------------------------------------------
# Isolation par salon (§11.2)
# ---------------------------------------------------------------------------


class TestListTransactionsSalonIsolation:
    def test_payment_from_other_salon_excluded(self) -> None:
        """Paiement du salon B invisible depuis la requête du salon A."""
        p = _make_payment(salon_id=_OTHER_SALON_ID)
        repo = FakePaymentRepository(payments=[p])
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=50, offset=0
        )
        assert total == 0
        assert page == ()

    def test_only_own_salon_payments_returned(self) -> None:
        pa = _make_payment(salon_id=_SALON_ID, created_at=_AT_1)
        pb = _make_payment(salon_id=_OTHER_SALON_ID, created_at=_AT_1)
        repo = FakePaymentRepository(payments=[pa, pb])
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.id == pa.id


# ---------------------------------------------------------------------------
# Filtre par mode de paiement
# ---------------------------------------------------------------------------


class TestListTransactionsFilterPaymentMethod:
    def test_filter_matches_cash_only(self) -> None:
        cash = _make_payment(payment_method="CASH")
        mobile = _make_payment(payment_method="MOBILE_MONEY_MANUAL")
        repo = FakePaymentRepository(payments=[cash, mobile])
        f = validate_transaction_filter(payment_method="CASH")
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.payment_method == "CASH"

    def test_filter_no_match_returns_empty(self) -> None:
        cash = _make_payment(payment_method="CASH")
        repo = FakePaymentRepository(payments=[cash])
        f = validate_transaction_filter(payment_method="CARD_MANUAL")
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 0
        assert page == ()

    def test_filter_mobile_money_isolated(self) -> None:
        mobile = _make_payment(payment_method="MOBILE_MONEY_MANUAL")
        card = _make_payment(payment_method="CARD_MANUAL")
        other = _make_payment(payment_method="OTHER")
        repo = FakePaymentRepository(payments=[mobile, card, other])
        f = validate_transaction_filter(payment_method="MOBILE_MONEY_MANUAL")
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.payment_method == "MOBILE_MONEY_MANUAL"


# ---------------------------------------------------------------------------
# Filtre par montant
# ---------------------------------------------------------------------------


class TestListTransactionsFilterAmount:
    def test_amount_min_excludes_lower(self) -> None:
        low = _make_payment(amount=decimal.Decimal("1000.00"))
        high = _make_payment(amount=decimal.Decimal("10000.00"))
        repo = FakePaymentRepository(payments=[low, high])
        f = validate_transaction_filter(amount_min=decimal.Decimal("5000.00"))
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.amount == decimal.Decimal("10000.00")

    def test_amount_max_excludes_higher(self) -> None:
        low = _make_payment(amount=decimal.Decimal("1000.00"))
        high = _make_payment(amount=decimal.Decimal("10000.00"))
        repo = FakePaymentRepository(payments=[low, high])
        f = validate_transaction_filter(amount_max=decimal.Decimal("5000.00"))
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.amount == decimal.Decimal("1000.00")

    def test_amount_range_inclusive_both_bounds(self) -> None:
        p1 = _make_payment(amount=decimal.Decimal("1000.00"))
        p2 = _make_payment(amount=decimal.Decimal("5000.00"))
        p3 = _make_payment(amount=decimal.Decimal("10000.00"))
        repo = FakePaymentRepository(payments=[p1, p2, p3])
        f = validate_transaction_filter(
            amount_min=decimal.Decimal("5000.00"),
            amount_max=decimal.Decimal("5000.00"),
        )
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.amount == decimal.Decimal("5000.00")


# ---------------------------------------------------------------------------
# Filtre par client_id
# ---------------------------------------------------------------------------


class TestListTransactionsFilterClientId:
    def test_client_id_filter_matches_correct_client(self) -> None:
        pa = _make_payment(client_id=_CLIENT_A)
        pb = _make_payment(client_id=_CLIENT_B)
        repo = FakePaymentRepository(payments=[pa, pb])
        f = validate_transaction_filter(client_id=_CLIENT_A)
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.client_id == _CLIENT_A

    def test_client_id_foreign_to_salon_returns_empty(self) -> None:
        """Un `client_id` étranger → liste vide, jamais une erreur (aucun oracle §11.2)."""
        p = _make_payment(client_id=_CLIENT_A)
        repo = FakePaymentRepository(payments=[p])
        foreign_client = uuid.uuid4()
        f = validate_transaction_filter(client_id=foreign_client)
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 0
        assert page == ()

    def test_client_id_none_matches_payments_without_client(self) -> None:
        """Sans filtre client, les paiements sans client_id sont inclus."""
        p_no_client = _make_payment(client_id=None)
        p_with_client = _make_payment(client_id=_CLIENT_A)
        repo = FakePaymentRepository(payments=[p_no_client, p_with_client])
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=50, offset=0
        )
        assert total == 2


# ---------------------------------------------------------------------------
# Filtre par date (via created_at_from/created_at_to)
# ---------------------------------------------------------------------------


class TestListTransactionsFilterDate:
    def test_date_from_excludes_earlier(self) -> None:
        old = _make_payment(created_at=_AT_1)     # 2026-03-01
        recent = _make_payment(created_at=_AT_2)  # 2026-03-15
        repo = FakePaymentRepository(payments=[old, recent])
        # date_from = 2026-03-10 → exclut le 2026-03-01
        f = validate_transaction_filter(date_from=datetime.date(2026, 3, 10))
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.created_at == _AT_2

    def test_date_to_excludes_later(self) -> None:
        old = _make_payment(created_at=_AT_1)     # 2026-03-01
        recent = _make_payment(created_at=_AT_2)  # 2026-03-15
        repo = FakePaymentRepository(payments=[old, recent])
        # date_to = 2026-03-10 → exclut le 2026-03-15
        f = validate_transaction_filter(date_to=datetime.date(2026, 3, 10))
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.created_at == _AT_1

    def test_date_range_single_day_matches_that_day(self) -> None:
        p_match = _make_payment(
            created_at=datetime.datetime(2026, 3, 15, 10, 0, 0, tzinfo=datetime.timezone.utc)
        )
        p_miss = _make_payment(
            created_at=datetime.datetime(2026, 3, 1, 8, 0, 0, tzinfo=datetime.timezone.utc)
        )
        repo = FakePaymentRepository(payments=[p_match, p_miss])
        f = validate_transaction_filter(
            date_from=datetime.date(2026, 3, 15),
            date_to=datetime.date(2026, 3, 15),
        )
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.created_at == p_match.created_at


# ---------------------------------------------------------------------------
# Combinaison de filtres en ET
# ---------------------------------------------------------------------------


class TestListTransactionsCombinedFilters:
    def test_method_and_amount_combined(self) -> None:
        """Un paiement CASH 1000 et un MOBILE_MONEY 5000 → seul MOBILE_MONEY ≥ 2000."""
        cash_low = _make_payment(
            payment_method="CASH", amount=decimal.Decimal("1000.00")
        )
        mobile_high = _make_payment(
            payment_method="MOBILE_MONEY_MANUAL", amount=decimal.Decimal("5000.00")
        )
        repo = FakePaymentRepository(payments=[cash_low, mobile_high])
        f = validate_transaction_filter(
            payment_method="MOBILE_MONEY_MANUAL",
            amount_min=decimal.Decimal("2000.00"),
        )
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.payment_method == "MOBILE_MONEY_MANUAL"

    def test_client_and_method_combined(self) -> None:
        pa = _make_payment(client_id=_CLIENT_A, payment_method="CASH")
        pb = _make_payment(client_id=_CLIENT_B, payment_method="CASH")
        pc = _make_payment(client_id=_CLIENT_A, payment_method="MOBILE_MONEY_MANUAL")
        repo = FakePaymentRepository(payments=[pa, pb, pc])
        f = validate_transaction_filter(
            client_id=_CLIENT_A, payment_method="CASH"
        )
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 1
        assert page[0].payment.client_id == _CLIENT_A
        assert page[0].payment.payment_method == "CASH"

    def test_no_match_all_filters_combined(self) -> None:
        p = _make_payment(payment_method="CASH", amount=decimal.Decimal("1000.00"))
        repo = FakePaymentRepository(payments=[p])
        f = validate_transaction_filter(
            payment_method="CARD_MANUAL",
            amount_min=decimal.Decimal("5000.00"),
        )
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=f, limit=50, offset=0
        )
        assert total == 0
        assert page == ()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestListTransactionsPagination:
    def _seed_n(self, n: int) -> FakePaymentRepository:
        """Crée `n` paiements avec des `created_at` ordonnés."""
        payments = [
            _make_payment(
                created_at=datetime.datetime(
                    2026, 1, i + 1, 0, 0, 0, tzinfo=datetime.timezone.utc
                )
            )
            for i in range(n)
        ]
        return FakePaymentRepository(payments=payments)

    def test_limit_respected(self) -> None:
        repo = self._seed_n(10)
        page, _ = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=3, offset=0
        )
        assert len(page) == 3

    def test_offset_respected(self) -> None:
        repo = self._seed_n(5)
        page_0, _ = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=2, offset=0
        )
        page_2, _ = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=2, offset=2
        )
        ids_0 = {t.payment.id for t in page_0}
        ids_2 = {t.payment.id for t in page_2}
        assert ids_0.isdisjoint(ids_2), "offset ne doit pas chevaucher la première page"

    def test_total_under_filter_not_page_size(self) -> None:
        """Le `total` reflète la cardinalité du filtre, pas la taille de la page."""
        repo = self._seed_n(10)
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=3, offset=0
        )
        assert total == 10
        assert len(page) == 3

    def test_offset_beyond_total_returns_empty(self) -> None:
        repo = self._seed_n(3)
        page, total = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=100
        )
        assert total == 3
        assert page == ()


# ---------------------------------------------------------------------------
# Tri déterministe (plus récent d'abord)
# ---------------------------------------------------------------------------


class TestListTransactionsSortOrder:
    def test_most_recent_first(self) -> None:
        p1 = _make_payment(created_at=_AT_1)  # 2026-03-01 — plus ancien
        p2 = _make_payment(created_at=_AT_2)  # 2026-03-15 — plus récent
        repo = FakePaymentRepository(payments=[p1, p2])
        page, _ = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=0
        )
        assert page[0].payment.created_at == _AT_2
        assert page[1].payment.created_at == _AT_1

    def test_insertion_order_irrelevant(self) -> None:
        """Le tri doit être stable quel que soit l'ordre d'insertion."""
        p1 = _make_payment(created_at=_AT_2)  # récent inséré en premier
        p2 = _make_payment(created_at=_AT_1)  # ancien inséré en second
        repo = FakePaymentRepository(payments=[p1, p2])
        page, _ = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=0
        )
        assert page[0].payment.created_at >= page[1].payment.created_at


# ---------------------------------------------------------------------------
# Lecture pure — aucune écriture / aucun audit
# ---------------------------------------------------------------------------


class TestListTransactionsPurity:
    def test_no_payments_created(self) -> None:
        repo = FakePaymentRepository()
        ListTransactions(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=10, offset=0)
        assert repo.created == []

    def test_no_mark_adjusted_called(self) -> None:
        p = _make_payment()
        repo = FakePaymentRepository(payments=[p])
        ListTransactions(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=10, offset=0)
        assert repo.mark_adjusted_calls == []

    def test_does_not_need_audit_log(self) -> None:
        """Lecture pure : aucune dépendance AuditLog requise (contraire à RecordPayment)."""
        repo = FakePaymentRepository()
        audit = FakeAuditLog()
        ListTransactions(repo).execute(_SALON_ID, filter=_NO_FILTER, limit=10, offset=0)
        assert len(audit.recorded) == 0


# ---------------------------------------------------------------------------
# Résolution du nom de client
# ---------------------------------------------------------------------------


class TestListTransactionsClientName:
    def test_client_name_resolved_from_repo(self) -> None:
        p = _make_payment(client_id=_CLIENT_A)
        repo = FakePaymentRepository(
            payments=[p],
            client_names={_CLIENT_A: "Awa Koné"},
        )
        page, _ = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=0
        )
        assert page[0].client_name == "Awa Koné"

    def test_client_name_none_when_no_client(self) -> None:
        p = _make_payment(client_id=None)
        repo = FakePaymentRepository(payments=[p])
        page, _ = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=0
        )
        assert page[0].client_name is None

    def test_client_name_none_when_not_in_names_dict(self) -> None:
        """Un `client_id` inconnu du mapping → `client_name = None`."""
        p = _make_payment(client_id=_CLIENT_A)
        repo = FakePaymentRepository(payments=[p])  # pas de client_names
        page, _ = ListTransactions(repo).execute(
            _SALON_ID, filter=_NO_FILTER, limit=10, offset=0
        )
        assert page[0].client_name is None
