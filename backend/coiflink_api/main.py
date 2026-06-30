"""Point d'entrée de l'API backend CoifLink.

Squelette d'initialisation du dépôt (#2). N'expose **qu'un** endpoint de santé
(`GET /health`) ; aucune logique métier MVP n'est implémentée ici (relève des
issues M1→). La configuration est lue depuis l'environnement, jamais codée en
dur (cf. PRD §11, ADR-0005/0006 « secrets hors dépôt »).
"""

from __future__ import annotations

import os

from fastapi import FastAPI

# Configuration lue depuis l'environnement (jamais de secret en dur).
APP_NAME = os.environ.get("APP_NAME", "CoifLink API")
APP_ENV = os.environ.get("APP_ENV", "development")

app = FastAPI(title=APP_NAME)


@app.get("/health")
def health() -> dict[str, str]:
    """Endpoint de santé du service (scaffolding).

    Ne traite ni ne journalise aucune donnée utilisateur ; sert de point
    d'ancrage au test gate `pytest` (#6) et aux sondes de la CI (#4).
    """
    return {"status": "ok"}
