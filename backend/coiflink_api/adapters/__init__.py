"""Adapters : seule couche qui connaît les frameworks et l'I/O.

- `inbound/` (driving) — points d'entrée : API HTTP FastAPI, tâches, CLI...
- `outbound/` (driven) — implémentations des ports : Postgres, Redis, S3, FCM/SMS.
"""
