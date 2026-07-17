"""Adapter entrant (driving) : router HTTP du **catalogue client** de salons (#18).

Expose la **recherche/liste publique des salons `ACTIVE`** (`GET /catalog/salons`,
§8.3). C'est une **ressource distincte** de `/salons` (« mes salons », portée
gérant) et de `/salons/{salon_id}` (portée salon) : le catalogue client ne
réutilise **jamais** une route de gestion. Le prefix `/catalog` évite en outre
toute collision de routage avec `/salons/{salon_id}` (typé `uuid.UUID`).

Décision d'autorisation (spec §A.2, ADR-0015) — **option publique retenue** :
`GET /catalog/salons` est ajouté à `PUBLIC_ROUTE_PATHS`
(`adapters/inbound/security.py`), addition **consciente et revue**. Justification :
la route est **lecture seule**, ne renvoie que des **données de vitrine publiques**
de salons **`ACTIVE`** (nom, ville, logo signé, `is_bookable`), **sans** `owner_id`
ni PII de gestion, et débloque le parcours client §7.1/§5.1 (recherche possible
avant connexion) alors que l'auth cliente n'existe pas encore côté mobile. Le test
`unprotected_routes(app)` reste l'arbitre : la route est publique-listée, jamais
orpheline.

La projection publique (`PublicSalonResponse`) et le filtre `ACTIVE` (au niveau du
dépôt) sont indépendants de cette décision : passer à l'option authentifiée ne
changerait que la garde du router et l'ajout à `PUBLIC_ROUTE_PATHS`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from coiflink_api.adapters.inbound.salons import get_optional_media_storage
from coiflink_api.adapters.outbound.persistence.salon_catalog_repository import (
    SqlSalonCatalogRepository,
)
from coiflink_api.adapters.outbound.persistence.session import get_session
from coiflink_api.application.catalog import PublicSalonView, SearchSalons
from coiflink_api.application.ports.media_storage import MediaStorage
from coiflink_api.application.ports.salon_catalog_repository import (
    CATALOG_LIMIT_DEFAULT,
    CATALOG_LIMIT_MAX,
    CATALOG_LIMIT_MIN,
    SalonCatalogRepository,
    SalonSearchQuery,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


# --------------------------------------------------------------------------- #
# Schémas Pydantic (documentation OpenAPI incluse — patron `salons.py`).
# --------------------------------------------------------------------------- #
class PublicSalonResponse(BaseModel):
    """Salon **de vitrine** exposé au client. `logo_url` : URL **signée** ou `null`.

    Projection minimale (spec §A.4) : **aucun** `owner_id`, `status`,
    `opening_hours`, `phone` ni timestamp. `is_bookable` (§8.3) porte le badge
    « réservable » / « bientôt disponible ».
    """

    id: object
    name: str
    description: str | None
    address: str | None
    city: str | None
    commune: str | None
    latitude: float | None
    longitude: float | None
    logo_url: str | None
    is_bookable: bool


class PublicSalonPageResponse(BaseModel):
    """Réponse paginée de `GET /catalog/salons` : items + total + bornes de page."""

    items: list[PublicSalonResponse]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Injection de dépendances (surchargeable en test via `app.dependency_overrides`).
# --------------------------------------------------------------------------- #
def get_salon_catalog_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SalonCatalogRepository:
    """Dépôt de **lecture publique** du catalogue adossé à la session de requête."""

    return SqlSalonCatalogRepository(session)


def _public_salon_response(view: PublicSalonView) -> PublicSalonResponse:
    """Mappe une `PublicSalonView` (logo signé résolu) vers la réponse HTTP."""

    return PublicSalonResponse(
        id=view.id,
        name=view.name,
        description=view.description,
        address=view.address,
        city=view.city,
        commune=view.commune,
        latitude=float(view.latitude) if view.latitude is not None else None,
        longitude=float(view.longitude) if view.longitude is not None else None,
        logo_url=view.logo_url,
        is_bookable=view.is_bookable,
    )


# --------------------------------------------------------------------------- #
# Routes.
# --------------------------------------------------------------------------- #
@router.get(
    "/salons",
    response_model=PublicSalonPageResponse,
    summary="Rechercher/lister les salons actifs (catalogue client, §8.3)",
    responses={
        200: {"description": "Page de salons actifs correspondant au filtre"},
        422: {"description": "Paramètres de pagination hors bornes"},
    },
)
def search_salons(
    request: Request,
    repository: Annotated[
        SalonCatalogRepository, Depends(get_salon_catalog_repository)
    ],
    storage: Annotated[MediaStorage | None, Depends(get_optional_media_storage)],
    q: Annotated[
        str | None,
        Query(description="Recherche par nom (sous-chaîne, insensible à la casse)"),
    ] = None,
    city: Annotated[
        str | None, Query(description="Filtre par ville")
    ] = None,
    commune: Annotated[
        str | None, Query(description="Filtre par commune")
    ] = None,
    limit: Annotated[
        int,
        Query(
            ge=CATALOG_LIMIT_MIN,
            le=CATALOG_LIMIT_MAX,
            description="Taille de page (bornée)",
        ),
    ] = CATALOG_LIMIT_DEFAULT,
    offset: Annotated[
        int, Query(ge=0, description="Décalage de page")
    ] = 0,
) -> PublicSalonPageResponse:
    """Liste/recherche les salons **`ACTIVE` uniquement** (§8.3).

    Seuls les salons actifs sont visibles : un salon `INACTIVE`/`SUSPENDED`
    n'apparaît **jamais** (filtre appliqué au niveau SQL par le dépôt, jamais en
    post-filtrage). La réponse n'expose que des données de vitrine publiques, sans
    `owner_id` ni clé d'objet brute. Les bornes de pagination invalides (`limit`
    hors `[1, 50]`, `offset < 0`) sont rejetées en `422` par FastAPI.
    """

    query = SalonSearchQuery(
        text=q.strip() if q and q.strip() else None,
        city=city.strip() if city and city.strip() else None,
        commune=commune.strip() if commune and commune.strip() else None,
        limit=limit,
        offset=offset,
    )
    page = SearchSalons(repository, storage).execute(query)
    return PublicSalonPageResponse(
        items=[_public_salon_response(view) for view in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


__all__ = ["router"]
