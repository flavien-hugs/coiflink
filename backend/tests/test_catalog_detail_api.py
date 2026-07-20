"""Tests API — fiche salon publique `GET /catalog/salons/{salon_id}` (#19).

Utilise FastAPI `TestClient` avec override de `get_salon_catalog_repository` :
aucune base ni réseau réel. La route est publique (`PUBLIC_ROUTE_PATHS`) : les
appels sans jeton doivent répondre `200`/`404`.

Couvre (spec §Testing) :
- critère §8.3 : `INACTIVE`/`SUSPENDED`/inconnu → 404 ; `salon_id` mal formé → 422 ;
- salon `ACTIVE` → 200 avec `services` (actives seulement), `opening_hours`, `price`,
  `is_bookable` ; une prestation désactivée n'apparaît pas ;
- projection : ni `owner_id`, ni `status`, ni clé d'objet brute, ni prestation
  `is_active`/`salon_id` ;
- logo/photos : URLs signées si stockage configuré, `null`/`[]` sinon ;
- invariant deny-by-default (ADR-0015) : aucune route orpheline.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from coiflink_api.adapters.inbound.catalog import get_salon_catalog_repository
from coiflink_api.adapters.inbound.salons import get_optional_media_storage
from coiflink_api.adapters.inbound.security import unprotected_routes
from coiflink_api.domain.enums import SalonStatus
from coiflink_api.domain.salon import Salon, SalonPhoto
from coiflink_api.domain.service import Service
from coiflink_api.main import app

from .conftest import FakeMediaStorage, FakeSalonCatalogRepository

_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

_OPENING_HOURS = {
    "version": 1,
    "timezone": "Africa/Abidjan",
    "weekly": {"mon": [{"start": "08:00", "end": "18:00"}]},
    "exceptions": [],
}


def _make_salon(
    *,
    salon_id: uuid.UUID | None = None,
    status: str = SalonStatus.ACTIVE.value,
    opening_hours: dict | None = None,
    logo_object_key: str | None = None,
) -> Salon:
    return Salon(
        id=salon_id or uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="Salon Élégance",
        description="Coiffure afro et tresses.",
        phone="+2250700000000",
        address="Rue des Jardins, Cocody",
        city="Abidjan",
        commune="Cocody",
        latitude=decimal.Decimal("5.359952"),
        longitude=decimal.Decimal("-3.996643"),
        logo_object_key=logo_object_key,
        status=status,
        opening_hours=opening_hours,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def _make_service(
    salon_id: uuid.UUID, *, name: str = "Coupe homme", is_active: bool = True
) -> Service:
    return Service(
        id=uuid.uuid4(),
        salon_id=salon_id,
        name=name,
        description="Coupe aux ciseaux.",
        price=decimal.Decimal("5000.00"),
        duration_minutes=30,
        category="Coupe",
        is_active=is_active,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def _make_photo(salon_id: uuid.UUID, *, position: int = 0) -> SalonPhoto:
    return SalonPhoto(
        id=uuid.uuid4(),
        salon_id=salon_id,
        object_key=f"salons/{salon_id}/photos/{uuid.uuid4()}.jpg",
        position=position,
        created_at=_CREATED_AT,
    )


@pytest.fixture(autouse=True)
def _teardown_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.pop(get_salon_catalog_repository, None)
    app.dependency_overrides.pop(get_optional_media_storage, None)


def _client(
    repo: FakeSalonCatalogRepository,
    storage: FakeMediaStorage | None = None,
) -> TestClient:
    app.dependency_overrides[get_salon_catalog_repository] = lambda: repo
    app.dependency_overrides[get_optional_media_storage] = lambda: storage
    return TestClient(app)


def _url(salon_id: uuid.UUID | str) -> str:
    return f"/catalog/salons/{salon_id}"


# ---------------------------------------------------------------------------
# Route publique — sans jeton
# ---------------------------------------------------------------------------


def test_detail_route_accessible_without_token() -> None:
    salon = _make_salon()
    resp = _client(FakeSalonCatalogRepository([salon])).get(_url(salon.id))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Critère §8.3 — 404 pour salon non ACTIVE / inconnu ; 422 UUID mal formé
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [SalonStatus.INACTIVE.value, SalonStatus.SUSPENDED.value],
)
def test_non_active_salon_returns_404(status: str) -> None:
    salon = _make_salon(status=status)
    resp = _client(FakeSalonCatalogRepository([salon])).get(_url(salon.id))
    assert resp.status_code == 404


def test_unknown_salon_returns_404() -> None:
    resp = _client(FakeSalonCatalogRepository([])).get(_url(uuid.uuid4()))
    assert resp.status_code == 404


def test_malformed_salon_id_returns_422() -> None:
    resp = _client(FakeSalonCatalogRepository([])).get(_url("not-a-uuid"))
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Salon ACTIVE — fiche complète
# ---------------------------------------------------------------------------


def test_active_salon_returns_full_detail() -> None:
    salon = _make_salon(opening_hours=_OPENING_HOURS)
    repo = FakeSalonCatalogRepository(
        [salon], services={salon.id: [_make_service(salon.id)]}
    )
    resp = _client(repo).get(_url(salon.id))

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Salon Élégance"
    assert data["phone"] == "+2250700000000"
    assert data["opening_hours"] == _OPENING_HOURS
    assert data["is_bookable"] is True
    assert len(data["services"]) == 1
    assert data["services"][0]["price"] == "5000.00"
    assert data["services"][0]["duration_minutes"] == 30


def test_services_exclude_deactivated() -> None:
    salon = _make_salon()
    services = {
        salon.id: [
            _make_service(salon.id, name="Coupe homme", is_active=True),
            _make_service(salon.id, name="Tresses", is_active=False),
        ]
    }
    resp = _client(FakeSalonCatalogRepository([salon], services=services)).get(
        _url(salon.id)
    )

    data = resp.json()
    names = {s["name"] for s in data["services"]}
    assert names == {"Coupe homme"}


def test_opening_hours_null_when_not_configured() -> None:
    salon = _make_salon(opening_hours=None)
    resp = _client(FakeSalonCatalogRepository([salon])).get(_url(salon.id))

    data = resp.json()
    assert data["opening_hours"] is None
    assert data["is_bookable"] is False


# ---------------------------------------------------------------------------
# Projection publique — pas de fuite
# ---------------------------------------------------------------------------


def test_detail_has_no_owner_id_or_status() -> None:
    salon = _make_salon()
    resp = _client(FakeSalonCatalogRepository([salon])).get(_url(salon.id))
    data = resp.json()
    assert "owner_id" not in data
    assert "status" not in data
    assert "created_at" not in data
    assert "updated_at" not in data


def test_service_item_has_no_management_fields() -> None:
    salon = _make_salon()
    repo = FakeSalonCatalogRepository(
        [salon], services={salon.id: [_make_service(salon.id)]}
    )
    resp = _client(repo).get(_url(salon.id))
    service = resp.json()["services"][0]
    assert "is_active" not in service
    assert "salon_id" not in service
    assert "created_at" not in service


def test_logo_url_is_signed_not_raw_key() -> None:
    salon = _make_salon(logo_object_key="salons/logo.jpg")
    resp = _client(
        FakeSalonCatalogRepository([salon]), storage=FakeMediaStorage()
    ).get(_url(salon.id))
    data = resp.json()
    assert data["logo_url"] is not None
    assert "?" in data["logo_url"]
    assert data["logo_url"] != "salons/logo.jpg"


def test_photos_signed_and_no_raw_key_leaks() -> None:
    salon = _make_salon()
    photos = {salon.id: [_make_photo(salon.id, position=0)]}
    resp = _client(
        FakeSalonCatalogRepository([salon], photos=photos),
        storage=FakeMediaStorage(),
    ).get(_url(salon.id))
    data = resp.json()
    assert len(data["photos"]) == 1
    assert "?" in data["photos"][0]["url"]
    # La clé d'objet brute (préfixe `salons/{id}/photos/`) ne fuit pas telle quelle.
    assert not data["photos"][0]["url"].startswith("salons/")


def test_logo_and_photos_null_without_storage() -> None:
    salon = _make_salon(logo_object_key="salons/logo.jpg")
    photos = {salon.id: [_make_photo(salon.id)]}
    resp = _client(
        FakeSalonCatalogRepository([salon], photos=photos), storage=None
    ).get(_url(salon.id))
    data = resp.json()
    assert data["logo_url"] is None
    assert data["photos"][0]["url"] is None


def test_photos_empty_list_always_in_response() -> None:
    """`photos` est toujours présent dans la réponse, même vide (contrat API stable)."""
    salon = _make_salon()
    resp = _client(FakeSalonCatalogRepository([salon])).get(_url(salon.id))
    data = resp.json()
    assert "photos" in data
    assert data["photos"] == []


def test_latitude_longitude_serialized_as_float() -> None:
    """Les coordonnées (Decimal en domaine) sont sérialisées en nombres flottants JSON."""
    salon = _make_salon()
    resp = _client(FakeSalonCatalogRepository([salon])).get(_url(salon.id))
    data = resp.json()
    assert isinstance(data["latitude"], float)
    assert isinstance(data["longitude"], float)
    assert abs(data["latitude"] - 5.359952) < 0.001
    assert abs(data["longitude"] - (-3.996643)) < 0.001


def test_public_route_not_blocked_by_bearer_token() -> None:
    """La route publique répond 200 même avec un en-tête Authorization présent."""
    salon = _make_salon()
    resp = (
        _client(FakeSalonCatalogRepository([salon]))
        .get(_url(salon.id), headers={"Authorization": "Bearer totally-fake-token"})
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Invariant deny-by-default (ADR-0015)
# ---------------------------------------------------------------------------


def test_no_unprotected_routes_after_detail_route() -> None:
    """`/catalog/salons/{salon_id}` est publique-listée : `unprotected_routes` vide."""
    bad = unprotected_routes(app)
    assert bad == [], f"Routes non protégées détectées : {bad}"
