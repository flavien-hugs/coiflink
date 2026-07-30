"""Tests unitaires — projection domaine `Receipt`/`ReceiptLine` (US-5.5, #38).

Couvre :
- construction `Receipt`/`ReceiptLine` (valeurs attendues, immutabilité `frozen`) ;
- `format_receipt_number` : déterministe, pure, renvoie `str(payment_id)` ;
- montants portés en `Decimal` (jamais float) ;
- `Receipt` sans ligne (paiement simple sans prestation liée) ;
- `Receipt` multi-lignes (RDV avec plusieurs prestations) ;
- `receipt_number` stable : deux appels pour le même `payment_id` → même valeur ;
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
_APPT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
_PAID_AT = datetime.datetime(2026, 7, 30, 10, 15, 0, tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# DEFAULT_CURRENCY
# ---------------------------------------------------------------------------

def test_default_currency_is_xof() -> None:
    assert DEFAULT_CURRENCY == "XOF"


# ---------------------------------------------------------------------------
# format_receipt_number — pure, déterministe
# ---------------------------------------------------------------------------

def test_format_receipt_number_returns_string_of_uuid() -> None:
    pid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert format_receipt_number(pid) == str(pid)


def test_format_receipt_number_is_deterministic() -> None:
    pid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    assert format_receipt_number(pid) == format_receipt_number(pid)


def test_format_receipt_number_returns_str() -> None:
    result = format_receipt_number(_PAYMENT_ID)
    assert isinstance(result, str)


def test_format_receipt_number_different_ids_give_different_numbers() -> None:
    id1 = uuid.UUID("11111111-0000-0000-0000-000000000001")
    id2 = uuid.UUID("22222222-0000-0000-0000-000000000002")
    assert format_receipt_number(id1) != format_receipt_number(id2)


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
    appointment_id: uuid.UUID | None = None,
    reference: str | None = None,
) -> Receipt:
    return Receipt(
        receipt_number=format_receipt_number(_PAYMENT_ID),
        payment_id=_PAYMENT_ID,
        salon_id=_SALON_ID,
        salon_name="Salon Élégance",
        amount=decimal.Decimal("5000.00"),
        currency="XOF",
        payment_method="CASH",
        status="VALIDATED",
        reference=reference,
        paid_at=_PAID_AT,
        appointment_id=appointment_id,
        lines=lines,
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
    assert r.appointment_id is None
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
    assert r.receipt_number == format_receipt_number(_PAYMENT_ID)


# ---------------------------------------------------------------------------
# Receipt — multi-lignes (RDV)
# ---------------------------------------------------------------------------

def test_receipt_with_appointment_lines() -> None:
    lines = (
        ReceiptLine(service_name="Coupe homme", amount=decimal.Decimal("3000.00")),
        ReceiptLine(service_name="Barbe", amount=decimal.Decimal("2000.00")),
    )
    r = _make_receipt(lines=lines, appointment_id=_APPT_ID)
    assert r.appointment_id == _APPT_ID
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
    r = _make_receipt(lines=(line,), appointment_id=None)
    assert len(r.lines) == 1
    assert r.appointment_id is None


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
        receipt_number=format_receipt_number(_PAYMENT_ID),
        payment_id=_PAYMENT_ID,
        salon_id=_SALON_ID,
        salon_name="Salon Élégance",
        amount=decimal.Decimal("9999.00"),
        currency="XOF",
        payment_method="CASH",
        status="VALIDATED",
        reference=None,
        paid_at=_PAID_AT,
        appointment_id=None,
        lines=(),
    )
    assert r1 != r2
