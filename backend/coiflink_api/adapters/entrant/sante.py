"""Adapter entrant (driving) : sonde de santé HTTP.

Expose `GET /health` sans logique métier ni donnée utilisateur ; sert de point
d'ancrage au test gate `pytest` (#6) et aux sondes de la CI (#4). En hexagonal,
un adapter entrant traduit une requête externe (ici HTTP) vers l'application ;
`/health` est purement technique et n'invoque donc aucun cas d'usage.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
