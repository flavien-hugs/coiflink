"""Tests unitaires — projection domaine `Receipt`/`ReceiptLine` (US-5.5, #38 · ADR-0040).

Couvre :
- construction `Receipt`/`ReceiptLine` (valeurs attendues, immutabilité `frozen`) ;
- `format_receipt_number` : pure, déterministe, formate un compteur séquentiel
  (`int`) en libellé `REC-000042` (impression gérant, ADR-0040 — remplace l'ancien
  format dérivé de l'UUID du paiement) ;
- montants portés en `Decimal` (jamais float) ;
- `Receipt` sans ligne (paiement simple sans prestation liée) ;
- `Receipt` multi-lignes (ticket walk-in avec plusieurs prestations) ;
- `client_name`/`client_phone` : `None` par défaut (lecture client), renseignables
  (lecture gérante) ;
- `DEFAULT_CURRENCY` est XOF.
"""

from __future__ import annotations

import decimal
import datetime
import uuid

import pytest

from coiflink_api.domain.receipt import (
    DEFAULT_CURRENCY,
    Receipt,
    ReceiptLine,
    format_receipt_number,
)

_PAYMENT_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_SALON_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_PAID_AT = datetime.datetime(2026, 7, 30, 10, 15, 0, tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# DEFAULT_CURRENCY
# ---------------------------------------------------------------------------

def test_default_currency_is_xof() -> None:
    assert DEFAULT_CURRENCY == "XOF"


# ---------------------------------------------------------------------------
# format_receipt_number — pure, déterministe (ADR-0040)
# ---------------------------------------------------------------------------

def test_format_receipt_number_formats_zero_padded_label() -> None:
    assert format_receipt_number(42) == "REC-000042"


def test_format_receipt_number_is_deterministic() -> None:
    assert format_receipt_number(7) == format_receipt_number(7)


def test_format_receipt_number_returns_str() -> None:
    assert isinstance(format_receipt_number(1), str)


def test_format_receipt_number_different_numbers_give_different_labels() -> None:
    assert format_receipt_number(1) != format_receipt_number(2)


def test_format_receipt_number_pads_small_numbers() -> None:
    assert format_receipt_number(1) == "REC-000001"


# ---------------------------------------------------------------------------
# ReceiptLine
# ---------------------------------------------------------------------------

def test_receipt_line_construction() -> None:
    line = ReceiptLine(service_name="Coupe homme", amount=decimal.Decimal("3000.00"))
    assert line.service_name == "Coupe homme"
    assert line.amount == decimal.Decimal("3000.00")


def test_receipt_line_amount_is_decimal() -> None:
    line = ReceiptLine(service_name="Barbe", amount=decimal.Decimal("2000.00"))
    assert isinstance(line.amount, decimal.Decimal)


def test_receipt_line_is_frozen() -> None:
    line = ReceiptLine(service_name="Coupe", amount=decimal.Decimal("3000.00"))
    with pytest.raises((TypeError, AttributeError)):
        line.service_name = "Autre"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Receipt — sans lignes
# ---------------------------------------------------------------------------

def _make_receipt(
    *,
    lines: tuple[ReceiptLine, ...] = (),
    reference: str | None = None,
    ticket_number: int | None = None,
    client_name: str | None = None,
    client_phone: str | None = None,
) -> Receipt:
    return Receipt(
        receipt_number=format_receipt_number(1),
        payment_id=_PAYMENT_ID,
        salon_id=_SALON_ID,
        salon_name="Salon Élégance",
        amount=decimal.Decimal("5000.00"),
        currency="XOF",
        payment_method="CASH",
        status="VALIDATED",
        reference=reference,
        paid_at=_PAID_AT,
        lines=lines,
        ticket_number=ticket_number,
        client_name=client_name,
        client_phone=client_phone,
    )


def test_receipt_construction_no_lines() -> None:
    r = _make_receipt()
    assert r.payment_id == _PAYMENT_ID
    assert r.salon_id == _SALON_ID
    assert r.salon_name == "Salon Élégance"
    assert r.amount == decimal.Decimal("5000.00")
    assert r.currency == "XOF"
    assert r.payment_method == "CASH"
    assert r.status == "VALIDATED"
    assert r.reference is None
    assert r.paid_at == _PAID_AT
    assert r.lines == ()


def test_receipt_amount_is_decimal() -> None:
    r = _make_receipt()
    assert isinstance(r.amount, decimal.Decimal)


def test_receipt_is_frozen() -> None:
    r = _make_receipt()
    with pytest.raises((TypeError, AttributeError)):
        r.amount = decimal.Decimal("9999.00")  # type: ignore[misc]


def test_receipt_receipt_number_equals_format_result() -> None:
    r = _make_receipt()
    assert r.receipt_number == format_receipt_number(1)


# ---------------------------------------------------------------------------
# Receipt — client_name / client_phone (impression gérant, ADR-0040)
# ---------------------------------------------------------------------------

def test_receipt_client_identity_defaults_to_none() -> None:
    """Lecture client (`get_receipt_for_client`) : jamais renseignés."""
    r = _make_receipt()
    assert r.client_name is None
    assert r.client_phone is None


def test_receipt_client_identity_settable_for_manager_view() -> None:
    """Lecture gérante (`get_receipt_for_salon`) : nom/téléphone de la cliente."""
    r = _make_receipt(client_name="Awa Koné", client_phone="+2250700000001")
    assert r.client_name == "Awa Koné"
    assert r.client_phone == "+2250700000001"


# ---------------------------------------------------------------------------
# Receipt — ticket_number (paiement lié à un ticket walk-in, #38)
# ---------------------------------------------------------------------------

def test_receipt_ticket_number_defaults_to_none() -> None:
    """Un paiement lié à une prestation seule n'a pas de ticket."""
    r = _make_receipt()
    assert r.ticket_number is None


def test_receipt_ticket_number_settable_for_ticket_linked_payment() -> None:
    r = _make_receipt(ticket_number=42)
    assert r.ticket_number == 42


# ---------------------------------------------------------------------------
# Receipt — multi-lignes (ticket walk-in)
# ---------------------------------------------------------------------------

def test_receipt_with_multiple_lines() -> None:
    lines = (
        ReceiptLine(service_name="Coupe homme", amount=decimal.Decimal("3000.00")),
        ReceiptLine(service_name="Barbe", amount=decimal.Decimal("2000.00")),
    )
    r = _make_receipt(lines=lines)
    assert len(r.lines) == 2
    assert r.lines[0].service_name == "Coupe homme"
    assert r.lines[1].service_name == "Barbe"


def test_receipt_lines_are_tuple() -> None:
    lines = (ReceiptLine(service_name="Coupe", amount=decimal.Decimal("3000.00")),)
    r = _make_receipt(lines=lines)
    assert isinstance(r.lines, tuple)


def test_receipt_total_is_payment_amount_not_sum_of_lines() -> None:
    """Le total de référence est `payment.amount` ; la somme des lignes est informative."""
    lines = (
        ReceiptLine(service_name="Coupe", amount=decimal.Decimal("3000.00")),
        ReceiptLine(service_name="Barbe", amount=decimal.Decimal("2000.00")),
    )
    r = _make_receipt(lines=lines)
    assert r.amount == decimal.Decimal("5000.00")
    line_sum = sum(line.amount for line in r.lines)
    assert line_sum == decimal.Decimal("5000.00")


def test_receipt_single_service_line() -> None:
    """Paiement lié à une prestation seule : une seule ligne."""
    line = ReceiptLine(service_name="Soin", amount=decimal.Decimal("4500.00"))
    r = _make_receipt(lines=(line,))
    assert len(r.lines) == 1


# ---------------------------------------------------------------------------
# Receipt — champs optionnels
# ---------------------------------------------------------------------------

def test_receipt_with_reference() -> None:
    r = _make_receipt(reference="REC-2026-0001")
    assert r.reference == "REC-2026-0001"


def test_receipt_without_reference() -> None:
    r = _make_receipt(reference=None)
    assert r.reference is None


def test_receipt_paid_at_is_timezone_aware() -> None:
    r = _make_receipt()
    assert r.paid_at.tzinfo is not None


# ---------------------------------------------------------------------------
# Égalité structurelle (frozen dataclass)
# ---------------------------------------------------------------------------

def test_two_receipts_with_same_data_are_equal() -> None:
    r1 = _make_receipt()
    r2 = _make_receipt()
    assert r1 == r2


def test_two_receipts_with_different_amounts_are_not_equal() -> None:
    r1 = _make_receipt()
    r2 = Receipt(
        receipt_number=format_receipt_number(1),
        payment_id=_PAYMENT_ID,
        salon_id=_SALON_ID,
        salon_name="Salon Élégance",
        amount=decimal.Decimal("9999.00"),
        currency="XOF",
        payment_method="CASH",
        status="VALIDATED",
        reference=None,
        paid_at=_PAID_AT,
        lines=(),
    )
    assert r1 != r2
