"""Tests API — router `/salons/{id}/payments` & `/salons/{id}/cash-journal` (US-5.1/5.3, #33/#34).

Utilise FastAPI `TestClient` avec override de dépendances :
- `get_payment_repository` → `FakePaymentRepository` ;
- `get_cash_journal_repository` → `FakeCashJournalRepository` ;
- `get_audit_log` (payments) → `FakeAuditLog` ;
- `get_user_repository` → `FakeAuthUserRepository` ;
- `get_access_policy` → `AccessPolicy(FakeSalonScopeRepository(...))`.

Couvre :
- POST `/salons/{id}/payments` : 201 (paiement `VALIDATED`, `recorded_by` du principal) ;
  422 (montant négatif, mode inconnu, prestation/RDV absents, montant incohérent,
  prestation inconnue) ; 401 sans jeton ;
  403 CLIENT/HAIRDRESSER/hors-portée ; champs privilégiés dans le corps → ignorés.
- GET `/salons/{id}/cash-journal` : 200 (page paginée `items`/`total`/`limit`/`offset`) ;
  401 sans jeton ; 403 CLIENT/hors-portée ; message 403 générique et constant.
- POST `/salons/{id}/payments/{payment_id}/adjustments` : 201 (`ADJUSTMENT` + `ADJUSTED`) ;
  422 (delta nul) ; 409 (paiement non corrigible) ; 404 (paiement hors salon/inconnu) ;
  401 sans jeton ; 403 hors-portée ; `performed_by` dans le corps → ignoré.
- Aucune route caisse/paiement dans `PUBLIC_ROUTE_PATHS`.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.payments import (
    get_appointment_repository,
    get_audit_log,
    get_cash_journal_repository,
    get_payment_repository,
    get_service_repository,
)
from coiflink_api.adapters.inbound.security import (
    PUBLIC_ROUTE_PATHS,
    get_access_policy,
    get_user_repository,
)
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.application.authorization import AccessPolicy
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import PaymentStatus, Role, UserStatus
from coiflink_api.domain.payment import Payment
from coiflink_api.domain.service import Service
from coiflink_api.main import app

from .conftest import (
    FAKE_ACCESS_CLAIMS,
    TEST_JWT_SECRET,
    FakeAppointmentRepository,
    FakeAuditLog,
    FakeAuthUserRepository,
    FakeCashJournalRepository,
    FakePaymentRepository,
    FakeSalonScopeRepository,
    FakeServiceRepository,
    make_access_token,
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MANAGER_ID = uuid.UUID(FAKE_ACCESS_CLAIMS.sub)
_CLIENT_ID = uuid.UUID("11111111-0000-0000-0000-000000000011")
_HAIRDRESSER_ID = uuid.UUID("22222222-0000-0000-0000-000000000022")
_OTHER_MANAGER_ID = uuid.UUID("33333333-0000-0000-0000-000000000033")

_SALON_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_OTHER_SALON_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_SERVICE_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
_PAYMENT_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")

_CREATED_AT = datetime.datetime(2026, 7, 28, 10, 0, 0, tzinfo=datetime.timezone.utc)

_MANAGER_TOKEN = make_access_token(_MANAGER_ID, Role.MANAGER.value)
_CLIENT_TOKEN = make_access_token(_CLIENT_ID, Role.CLIENT.value)
_HAIRDRESSER_TOKEN = make_access_token(_HAIRDRESSER_ID, Role.HAIRDRESSER.value)

_VALID_PAYMENT_BODY: dict = {
    "amount": "5000.00",
    "payment_method": "CASH",
    "service_id": str(_SERVICE_ID),
}

_VALID_ADJUSTMENT_BODY: dict = {
    "amount": "-500.00",
    "description": "Erreur de saisie du montant",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _creds(user_id: uuid.UUID, role: str) -> UserCredentials:
    return UserCredentials(
        id=user_id,
        role=role,
        status=UserStatus.ACTIVE.value,
        password_hash="x",
    )


def _payments_url(salon_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/payments"


def _cash_journal_url(salon_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/cash-journal"


def _adjustments_url(salon_id: uuid.UUID, payment_id: uuid.UUID) -> str:
    return f"/salons/{salon_id}/payments/{payment_id}/adjustments"


def _make_validated_payment(
    payment_id: uuid.UUID = _PAYMENT_ID,
    salon_id: uuid.UUID = _SALON_ID,
) -> Payment:
    return Payment(
        id=payment_id,
        salon_id=salon_id,
        amount=decimal.Decimal("5000.00"),
        currency="XOF",
        payment_method="CASH",
        status=PaymentStatus.VALIDATED.value,
        recorded_by=_MANAGER_ID,
        appointment_id=None,
        service_id=_SERVICE_ID,
        client_id=None,
        reference=None,
        created_at=_CREATED_AT,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _install_token_service() -> Generator[None, None, None]:
    original = getattr(app.state, "token_service", None)
    app.state.token_service = JwtTokenService(TEST_JWT_SECRET)
    yield
    app.state.token_service = original


@pytest.fixture()
def payment_repo() -> FakePaymentRepository:
    return FakePaymentRepository()


@pytest.fixture()
def journal_repo() -> FakeCashJournalRepository:
    return FakeCashJournalRepository()


@pytest.fixture()
def audit_log() -> FakeAuditLog:
    return FakeAuditLog()


def _service_repo_with_valid_service() -> FakeServiceRepository:
    """Dépôt seedé avec `_SERVICE_ID` **active** au prix du corps valide (5000.00).

    La cohérence du montant (#33) résout le prix attendu depuis la prestation liée :
    le corps `_VALID_PAYMENT_BODY` (5000.00) doit donc correspondre à une prestation
    de ce prix pour produire un `201`.
    """

    repo = FakeServiceRepository()
    repo._services[_SERVICE_ID] = Service(
        id=_SERVICE_ID,
        salon_id=_SALON_ID,
        name="Coupe",
        description=None,
        price=decimal.Decimal("5000.00"),
        duration_minutes=30,
        category=None,
        is_active=True,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )
    return repo


@pytest.fixture()
def service_repo() -> FakeServiceRepository:
    return _service_repo_with_valid_service()


@pytest.fixture()
def appointment_repo() -> FakeAppointmentRepository:
    return FakeAppointmentRepository()


@pytest.fixture()
def manager_client(
    payment_repo: FakePaymentRepository,
    journal_repo: FakeCashJournalRepository,
    audit_log: FakeAuditLog,
    service_repo: FakeServiceRepository,
    appointment_repo: FakeAppointmentRepository,
) -> Generator[TestClient, None, None]:
    """TestClient avec MANAGER authentifié et salon dans sa portée."""
    creds = _creds(_MANAGER_ID, Role.MANAGER.value)
    user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
    scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

    app.dependency_overrides[get_payment_repository] = lambda: payment_repo
    app.dependency_overrides[get_cash_journal_repository] = lambda: journal_repo
    app.dependency_overrides[get_audit_log] = lambda: audit_log
    app.dependency_overrides[get_appointment_repository] = lambda: appointment_repo
    app.dependency_overrides[get_service_repository] = lambda: service_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_payment_repository, None)
        app.dependency_overrides.pop(get_cash_journal_repository, None)
        app.dependency_overrides.pop(get_audit_log, None)
        app.dependency_overrides.pop(get_appointment_repository, None)
        app.dependency_overrides.pop(get_service_repository, None)
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_access_policy, None)


# ---------------------------------------------------------------------------
# POST /salons/{id}/payments — 201
# ---------------------------------------------------------------------------


class TestRecordPayment201:
    def test_returns_201(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=_VALID_PAYMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201

    def test_response_status_is_validated(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=_VALID_PAYMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["status"] == PaymentStatus.VALIDATED.value

    def test_response_salon_id_matches_path(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=_VALID_PAYMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["salon_id"] == str(_SALON_ID)

    def test_recorded_by_is_from_principal_not_body(self, manager_client: TestClient) -> None:
        """Non-répudiation §8.2 : `recorded_by` vient du principal, jamais du corps."""
        body = {**_VALID_PAYMENT_BODY, "recorded_by": str(uuid.uuid4())}
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201
        assert r.json()["recorded_by"] == str(_MANAGER_ID)

    def test_privileged_fields_in_body_ignored(self, manager_client: TestClient) -> None:
        """Champs privilégiés présents dans le corps sont ignorés (`extra=ignore`)."""
        body = {
            **_VALID_PAYMENT_BODY,
            "status": "CANCELLED",
            "id": str(uuid.uuid4()),
        }
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201
        assert r.json()["status"] == PaymentStatus.VALIDATED.value

    def test_id_in_response(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=_VALID_PAYMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "id" in r.json()

    def test_currency_defaults_to_xof(self, manager_client: TestClient) -> None:
        body = {k: v for k, v in _VALID_PAYMENT_BODY.items() if k != "currency"}
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["currency"] == "XOF"


# ---------------------------------------------------------------------------
# POST /salons/{id}/payments — 422
# ---------------------------------------------------------------------------


class TestRecordPayment422:
    def test_negative_amount_returns_422(self, manager_client: TestClient) -> None:
        body = {**_VALID_PAYMENT_BODY, "amount": "-100.00"}
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_unknown_payment_method_returns_422(self, manager_client: TestClient) -> None:
        body = {**_VALID_PAYMENT_BODY, "payment_method": "BITCOIN"}
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_no_service_or_appointment_returns_422(self, manager_client: TestClient) -> None:
        """Un paiement doit référencer une prestation OU un RDV (§8.2)."""
        body = {"amount": "1000.00", "payment_method": "CASH"}
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_unsupported_currency_returns_422(self, manager_client: TestClient) -> None:
        """MVP mono-devise (§9.6) : une devise ≠ XOF est refusée avant écriture."""
        body = {**_VALID_PAYMENT_BODY, "currency": "USD"}
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_oversized_currency_returns_422_not_500(self, manager_client: TestClient) -> None:
        """Refusé en amont plutôt que de violer la colonne `payments.currency` (String(3))."""
        body = {**_VALID_PAYMENT_BODY, "currency": "EURO"}
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /salons/{id}/payments — 422 cohérence (#33)
# ---------------------------------------------------------------------------


class TestRecordPaymentCoherence422:
    """Cohérence du montant et résolution de référence → 422 (§5.3/§8.2, #33).

    Ces erreurs sont distinctes des erreurs de format : elles impliquent une
    résolution salon-scopée (prestation connue ou non, prix cohérent ou non).
    """

    def test_amount_mismatch_returns_422(self, manager_client: TestClient) -> None:
        """Montant saisi ≠ prix de la prestation (service_repo seedé à 5000.00) → 422."""
        body = {**_VALID_PAYMENT_BODY, "amount": "3000.00"}
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422

    def test_unknown_service_id_returns_422(self, manager_client: TestClient) -> None:
        """Prestation inconnue dans le salon → PaymentReferenceNotFound → 422."""
        body = {**_VALID_PAYMENT_BODY, "service_id": str(uuid.uuid4())}
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /salons/{id}/payments — 401/403
# ---------------------------------------------------------------------------


class TestRecordPaymentAuth:
    def test_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _payments_url(_SALON_ID),
            json=_VALID_PAYMENT_BODY,
        )
        assert r.status_code == 401

    def test_client_role_returns_403(
        self,
        journal_repo: FakeCashJournalRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        payment_repo = FakePaymentRepository()
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_CLIENT_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_payment_repository] = lambda: payment_repo
        app.dependency_overrides[get_cash_journal_repository] = lambda: journal_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_appointment_repository] = (
            lambda: FakeAppointmentRepository()
        )
        app.dependency_overrides[get_service_repository] = (
            lambda: _service_repo_with_valid_service()
        )
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _payments_url(_SALON_ID),
                    json=_VALID_PAYMENT_BODY,
                    headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_payment_repository, None)
            app.dependency_overrides.pop(get_cash_journal_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_appointment_repository, None)
            app.dependency_overrides.pop(get_service_repository, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 403
        assert r.json()["detail"] == "Accès refusé."

    def test_out_of_scope_salon_returns_403(self, manager_client: TestClient) -> None:
        """Gérant hors portée → 403 générique (isolation §11.2)."""
        r = manager_client.post(
            _payments_url(_OTHER_SALON_ID),
            json=_VALID_PAYMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "Accès refusé."


# ---------------------------------------------------------------------------
# GET /salons/{id}/cash-journal — 200
# ---------------------------------------------------------------------------


class TestListCashJournal200:
    def test_returns_200(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _cash_journal_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 200

    def test_response_has_items_field(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _cash_journal_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "items" in r.json()

    def test_response_has_total_field(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _cash_journal_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert "total" in r.json()

    def test_response_has_limit_and_offset(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _cash_journal_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        body = r.json()
        assert "limit" in body
        assert "offset" in body

    def test_empty_journal_returns_zero_total(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _cash_journal_url(_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["total"] == 0

    def test_limit_query_param_reflected(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _cash_journal_url(_SALON_ID),
            params={"limit": 10, "offset": 0},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["limit"] == 10

    def test_offset_query_param_reflected(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _cash_journal_url(_SALON_ID),
            params={"limit": 50, "offset": 5},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["offset"] == 5


# ---------------------------------------------------------------------------
# GET /salons/{id}/cash-journal — 401/403
# ---------------------------------------------------------------------------


class TestListCashJournalAuth:
    def test_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.get(_cash_journal_url(_SALON_ID))
        assert r.status_code == 401

    def test_out_of_scope_salon_returns_403(self, manager_client: TestClient) -> None:
        r = manager_client.get(
            _cash_journal_url(_OTHER_SALON_ID),
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "Accès refusé."

    def test_client_role_returns_403(
        self,
        journal_repo: FakeCashJournalRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        payment_repo = FakePaymentRepository()
        creds = _creds(_CLIENT_ID, Role.CLIENT.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_CLIENT_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_payment_repository] = lambda: payment_repo
        app.dependency_overrides[get_cash_journal_repository] = lambda: journal_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.get(
                    _cash_journal_url(_SALON_ID),
                    headers={"Authorization": f"Bearer {_CLIENT_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_payment_repository, None)
            app.dependency_overrides.pop(get_cash_journal_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 403
        assert r.json()["detail"] == "Accès refusé."


# ---------------------------------------------------------------------------
# POST /salons/{id}/payments/{payment_id}/adjustments — 201
# ---------------------------------------------------------------------------


class TestAdjustPayment201:
    @pytest.fixture()
    def client_with_payment(
        self,
        journal_repo: FakeCashJournalRepository,
        audit_log: FakeAuditLog,
    ) -> Generator[tuple[TestClient, uuid.UUID], None, None]:
        """TestClient MANAGER avec un paiement VALIDATED pré-chargé dans le dépôt."""
        payment = _make_validated_payment()
        payment_repo = FakePaymentRepository(payments=[payment])

        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_payment_repository] = lambda: payment_repo
        app.dependency_overrides[get_cash_journal_repository] = lambda: journal_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            yield TestClient(app), payment.id
        finally:
            app.dependency_overrides.pop(get_payment_repository, None)
            app.dependency_overrides.pop(get_cash_journal_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_returns_201(
        self, client_with_payment: tuple[TestClient, uuid.UUID]
    ) -> None:
        client, payment_id = client_with_payment
        r = client.post(
            _adjustments_url(_SALON_ID, payment_id),
            json=_VALID_ADJUSTMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201

    def test_response_contains_entry_and_payment(
        self, client_with_payment: tuple[TestClient, uuid.UUID]
    ) -> None:
        client, payment_id = client_with_payment
        r = client.post(
            _adjustments_url(_SALON_ID, payment_id),
            json=_VALID_ADJUSTMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        body = r.json()
        assert "entry" in body
        assert "payment" in body

    def test_entry_operation_type_is_adjustment(
        self, client_with_payment: tuple[TestClient, uuid.UUID]
    ) -> None:
        client, payment_id = client_with_payment
        r = client.post(
            _adjustments_url(_SALON_ID, payment_id),
            json=_VALID_ADJUSTMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["entry"]["operation_type"] == "ADJUSTMENT"

    def test_payment_status_becomes_adjusted(
        self, client_with_payment: tuple[TestClient, uuid.UUID]
    ) -> None:
        client, payment_id = client_with_payment
        r = client.post(
            _adjustments_url(_SALON_ID, payment_id),
            json=_VALID_ADJUSTMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.json()["payment"]["status"] == PaymentStatus.ADJUSTED.value

    def test_performed_by_in_body_ignored(
        self, client_with_payment: tuple[TestClient, uuid.UUID]
    ) -> None:
        """Non-répudiation §8.2 : `performed_by` dans le corps est ignoré."""
        client, payment_id = client_with_payment
        body = {**_VALID_ADJUSTMENT_BODY, "performed_by": str(uuid.uuid4())}
        r = client.post(
            _adjustments_url(_SALON_ID, payment_id),
            json=body,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 201
        assert r.json()["entry"]["performed_by"] == str(_MANAGER_ID)


# ---------------------------------------------------------------------------
# POST .../adjustments — 422
# ---------------------------------------------------------------------------


class TestAdjustPayment422:
    @pytest.fixture()
    def client_with_validated_payment(
        self,
        journal_repo: FakeCashJournalRepository,
        audit_log: FakeAuditLog,
    ) -> Generator[tuple[TestClient, uuid.UUID], None, None]:
        payment = _make_validated_payment()
        payment_repo = FakePaymentRepository(payments=[payment])

        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_payment_repository] = lambda: payment_repo
        app.dependency_overrides[get_cash_journal_repository] = lambda: journal_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            yield TestClient(app), payment.id
        finally:
            app.dependency_overrides.pop(get_payment_repository, None)
            app.dependency_overrides.pop(get_cash_journal_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_zero_delta_returns_422(
        self, client_with_validated_payment: tuple[TestClient, uuid.UUID]
    ) -> None:
        client, payment_id = client_with_validated_payment
        r = client.post(
            _adjustments_url(_SALON_ID, payment_id),
            json={"amount": "0.00"},
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST .../adjustments — 409
# ---------------------------------------------------------------------------


class TestAdjustPayment409:
    @pytest.fixture()
    def client_with_adjusted_payment(
        self,
        journal_repo: FakeCashJournalRepository,
        audit_log: FakeAuditLog,
    ) -> Generator[tuple[TestClient, uuid.UUID], None, None]:
        """Paiement déjà ADJUSTED → 409."""
        payment = Payment(
            id=_PAYMENT_ID,
            salon_id=_SALON_ID,
            amount=decimal.Decimal("5000.00"),
            currency="XOF",
            payment_method="CASH",
            status=PaymentStatus.ADJUSTED.value,
            recorded_by=_MANAGER_ID,
            appointment_id=None,
            service_id=_SERVICE_ID,
            client_id=None,
            reference=None,
            created_at=_CREATED_AT,
        )
        payment_repo = FakePaymentRepository(payments=[payment])

        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_payment_repository] = lambda: payment_repo
        app.dependency_overrides[get_cash_journal_repository] = lambda: journal_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            yield TestClient(app), payment.id
        finally:
            app.dependency_overrides.pop(get_payment_repository, None)
            app.dependency_overrides.pop(get_cash_journal_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

    def test_already_adjusted_returns_409(
        self, client_with_adjusted_payment: tuple[TestClient, uuid.UUID]
    ) -> None:
        client, payment_id = client_with_adjusted_payment
        r = client.post(
            _adjustments_url(_SALON_ID, payment_id),
            json=_VALID_ADJUSTMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# POST .../adjustments — 404
# ---------------------------------------------------------------------------


class TestAdjustPayment404:
    def test_unknown_payment_returns_404(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _adjustments_url(_SALON_ID, uuid.uuid4()),
            json=_VALID_ADJUSTMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 404

    def test_payment_from_other_salon_returns_404_after_scope(
        self,
        journal_repo: FakeCashJournalRepository,
        audit_log: FakeAuditLog,
    ) -> None:
        """Paiement d'un autre salon = indiscernable de l'inexistant (§11.2)."""
        payment = _make_validated_payment(salon_id=_OTHER_SALON_ID)
        payment_repo = FakePaymentRepository(payments=[payment])

        creds = _creds(_MANAGER_ID, Role.MANAGER.value)
        user_repo = FakeAuthUserRepository(credentials_by_id={str(creds.id): creds})
        scope_repo = FakeSalonScopeRepository(scopes={_MANAGER_ID: frozenset({_SALON_ID})})

        app.dependency_overrides[get_payment_repository] = lambda: payment_repo
        app.dependency_overrides[get_cash_journal_repository] = lambda: journal_repo
        app.dependency_overrides[get_audit_log] = lambda: audit_log
        app.dependency_overrides[get_user_repository] = lambda: user_repo
        app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(scope_repo)
        try:
            with TestClient(app) as c:
                r = c.post(
                    _adjustments_url(_SALON_ID, payment.id),
                    json=_VALID_ADJUSTMENT_BODY,
                    headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
                )
        finally:
            app.dependency_overrides.pop(get_payment_repository, None)
            app.dependency_overrides.pop(get_cash_journal_repository, None)
            app.dependency_overrides.pop(get_audit_log, None)
            app.dependency_overrides.pop(get_user_repository, None)
            app.dependency_overrides.pop(get_access_policy, None)

        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST .../adjustments — 401/403
# ---------------------------------------------------------------------------


class TestAdjustPaymentAuth:
    def test_no_token_returns_401(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _adjustments_url(_SALON_ID, uuid.uuid4()),
            json=_VALID_ADJUSTMENT_BODY,
        )
        assert r.status_code == 401

    def test_out_of_scope_salon_returns_403(self, manager_client: TestClient) -> None:
        r = manager_client.post(
            _adjustments_url(_OTHER_SALON_ID, uuid.uuid4()),
            json=_VALID_ADJUSTMENT_BODY,
            headers={"Authorization": f"Bearer {_MANAGER_TOKEN}"},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "Accès refusé."


# ---------------------------------------------------------------------------
# PUBLIC_ROUTE_PATHS — aucune route caisse/paiement n'est publique
# ---------------------------------------------------------------------------


class TestNoPublicPaymentOrCashJournalRoute:
    def test_no_payment_path_in_public_routes(self) -> None:
        for path in PUBLIC_ROUTE_PATHS:
            assert "/payments" not in path, (
                f"Route paiement trouvée dans PUBLIC_ROUTE_PATHS : {path}"
            )

    def test_no_cash_journal_path_in_public_routes(self) -> None:
        for path in PUBLIC_ROUTE_PATHS:
            assert "/cash-journal" not in path, (
                f"Route journal de caisse trouvée dans PUBLIC_ROUTE_PATHS : {path}"
            )
