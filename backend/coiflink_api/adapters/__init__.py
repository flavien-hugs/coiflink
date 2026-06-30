"""Adapters : seule couche qui connaît les frameworks et l'I/O.

- `entrant/` (driving) — points d'entrée : API HTTP FastAPI, tâches, CLI...
- `sortant/` (driven) — implémentations des ports : Postgres, Redis, S3, FCM/SMS.
"""
