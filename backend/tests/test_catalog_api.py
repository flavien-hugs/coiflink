"""Tests API — router `/catalog` (adapter entrant, #18).

Utilise FastAPI `TestClient` avec override de `get_salon_catalog_repository` :
aucune base ni réseau réel. La route `GET /catalog/salons` est publique
(`PUBLIC_ROUTE_PATHS`) : les appels sans jeton doivent retourner 200.

Couvre :
- route publique : réponse 200 sans jeton Bearer ;
- invariant §8.3 : INACTIVE/SUSPENDED n'apparaissent jamais dans la réponse ;
- salons ACTIVE visibles dans le catalogue ;
- filtres `?q=`, `?city=`, `?commune=` ;
- pagination : `?limit=`/`?offset=` valides → 200 ; hors bornes → 422 ;
- projection publique : owner_id, status, opening_hours, phone absents du JSON ;
- logo_url : URL signée si stockage configuré, null sinon (jamais la clé d'objet) ;
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
from coiflink_api.domain.salon import Salon
from coiflink_api.main import app

from .conftest import FakeMediaStorage, FakeSalonCatalogRepository

_CREATED_AT = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
_CATALOG_URL = "/catalog/salons"


def _make_salon(
    *,
    name: str = "Salon Test",
    status: str = SalonStatus.ACTIVE.value,
    city: str | None = "Abidjan",
    commune: str | None = "Cocody",
    logo_object_key: str | None = None,
    opening_hours: dict | None = None,
) -> Salon:
    return Salon(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name=name,
        description="Description de test.",
        phone=None,
        address="Rue des Jardins",
        city=city,
        commune=commune,
        latitude=decimal.Decimal("5.36"),
        longitude=decimal.Decimal("-3.99"),
        logo_object_key=logo_object_key,
        status=status,
        opening_hours=opening_hours,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


@pytest.fixture(autouse=True)
def _teardown_overrides() -> Generator[None, None, None]:
    """Retire les overrides après chaque test pour éviter les fuites de contexte."""
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


# ---------------------------------------------------------------------------
# Route publique — sans jeton Bearer
# ---------------------------------------------------------------------------


def test_catalog_route_accessible_without_token() -> None:
    client = _client(FakeSalonCatalogRepository([_make_salon()]))
    resp = client.get(_CATALOG_URL)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Invariant §8.3 — salons non-ACTIVE exclus
# ---------------------------------------------------------------------------


def test_inactive_salon_not_in_catalog() -> None:
    repo = FakeSalonCatalogRepository(
        [_make_salon(name="Salon Inactif", status=SalonStatus.INACTIVE.value)]
    )
    resp = _client(repo).get(_CATALOG_URL)

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_suspended_salon_not_in_catalog() -> None:
    repo = FakeSalonCatalogRepository(
        [_make_salon(name="Salon Suspendu", status=SalonStatus.SUSPENDED.value)]
    )
    resp = _client(repo).get(_CATALOG_URL)

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_active_salon_appears_in_catalog() -> None:
    repo = FakeSalonCatalogRepository([_make_salon(name="Salon Actif")])
    resp = _client(repo).get(_CATALOG_URL)

    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "Salon Actif"


def test_mixed_statuses_only_active_returned() -> None:
    repo = FakeSalonCatalogRepository([
        _make_salon(name="Salon Actif A"),
        _make_salon(name="Salon Inactif", status=SalonStatus.INACTIVE.value),
        _make_salon(name="Salon Actif B"),
        _make_salon(name="Salon Suspendu", status=SalonStatus.SUSPENDED.value),
    ])
    resp = _client(repo).get(_CATALOG_URL)

    data = resp.json()
    assert data["total"] == 2
    names = {item["name"] for item in data["items"]}
    assert names == {"Salon Actif A", "Salon Actif B"}


# ---------------------------------------------------------------------------
# Filtres de recherche
# ---------------------------------------------------------------------------


def test_search_by_name_filters_results() -> None:
    repo = FakeSalonCatalogRepository([
        _make_salon(name="Salon Élégance"),
        _make_salon(name="Coiffure Moderne"),
    ])
    resp = _client(repo).get(_CATALOG_URL, params={"q": "Élégan"})

    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Salon Élégance"


def test_city_filter_excludes_other_cities() -> None:
    repo = FakeSalonCatalogRepository([
        _make_salon(name="Salon Abidjan", city="Abidjan"),
        _make_salon(name="Salon Bouaké", city="Bouaké"),
    ])
    resp = _client(repo).get(_CATALOG_URL, params={"city": "Abidjan"})

    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Salon Abidjan"


def test_commune_filter_excludes_other_communes() -> None:
    repo = FakeSalonCatalogRepository([
        _make_salon(name="Salon Cocody", commune="Cocody"),
        _make_salon(name="Salon Plateau", commune="Plateau"),
    ])
    resp = _client(repo).get(_CATALOG_URL, params={"commune": "Plateau"})

    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Salon Plateau"


def test_whitespace_only_query_ignored() -> None:
    repo = FakeSalonCatalogRepository([_make_salon(name="Salon Alpha")])
    resp = _client(repo).get(_CATALOG_URL, params={"q": "   "})

    data = resp.json()
    assert data["total"] == 1


# ---------------------------------------------------------------------------
# Pagination et bornes
# ---------------------------------------------------------------------------


def test_default_limit_is_20() -> None:
    repo = FakeSalonCatalogRepository([_make_salon()])
    data = _client(repo).get(_CATALOG_URL).json()
    assert data["limit"] == 20


def test_limit_zero_returns_422() -> None:
    resp = _client(FakeSalonCatalogRepository()).get(_CATALOG_URL, params={"limit": 0})
    assert resp.status_code == 422


def test_limit_51_returns_422() -> None:
    resp = _client(FakeSalonCatalogRepository()).get(_CATALOG_URL, params={"limit": 51})
    assert resp.status_code == 422


def test_negative_offset_returns_422() -> None:
    resp = _client(FakeSalonCatalogRepository()).get(_CATALOG_URL, params={"offset": -1})
    assert resp.status_code == 422


def test_pagination_offset_and_total_coherent() -> None:
    salons = [_make_salon(name=f"Salon {i:02d}") for i in range(10)]
    repo = FakeSalonCatalogRepository(salons)
    resp = _client(repo).get(_CATALOG_URL, params={"limit": 3, "offset": 4})

    data = resp.json()
    assert data["total"] == 10
    assert len(data["items"]) == 3
    assert data["offset"] == 4
    assert data["limit"] == 3


# ---------------------------------------------------------------------------
# Projection publique — champs de gestion absents de la réponse JSON
# ---------------------------------------------------------------------------


def test_response_item_has_no_owner_id() -> None:
    resp = _client(FakeSalonCatalogRepository([_make_salon()])).get(_CATALOG_URL)
    item = resp.json()["items"][0]
    assert "owner_id" not in item


def test_response_item_has_no_status_field() -> None:
    resp = _client(FakeSalonCatalogRepository([_make_salon()])).get(_CATALOG_URL)
    item = resp.json()["items"][0]
    assert "status" not in item


def test_response_item_has_no_opening_hours_field() -> None:
    resp = _client(FakeSalonCatalogRepository([_make_salon()])).get(_CATALOG_URL)
    item = resp.json()["items"][0]
    assert "opening_hours" not in item


def test_response_item_has_no_phone_field() -> None:
    resp = _client(FakeSalonCatalogRepository([_make_salon()])).get(_CATALOG_URL)
    item = resp.json()["items"][0]
    assert "phone" not in item


def test_logo_url_null_when_no_storage() -> None:
    salon = _make_salon(logo_object_key="salons/logo.jpg")
    resp = _client(FakeSalonCatalogRepository([salon]), storage=None).get(_CATALOG_URL)
    item = resp.json()["items"][0]
    assert item["logo_url"] is None


def test_logo_url_is_signed_url_not_raw_key() -> None:
    salon = _make_salon(logo_object_key="salons/logo.jpg")
    storage = FakeMediaStorage()
    resp = _client(FakeSalonCatalogRepository([salon]), storage=storage).get(_CATALOG_URL)
    item = resp.json()["items"][0]
    assert item["logo_url"] is not None
    # URL signée comporte des paramètres, jamais la clé brute seule
    assert "?" in item["logo_url"]
    assert item["logo_url"] != "salons/logo.jpg"


# ---------------------------------------------------------------------------
# Invariant deny-by-default (ADR-0015)
# ---------------------------------------------------------------------------


def test_no_unprotected_routes_after_catalog_router() -> None:
    """`/catalog/salons` est publique-listée : `unprotected_routes` reste vide."""
    bad = unprotected_routes(app)
    assert bad == [], f"Routes non protégées détectées : {bad}"
