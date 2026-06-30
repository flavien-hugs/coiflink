"""Ports : interfaces (typing.Protocol) du bord de l'application.

Les adapters sortants (`adapters/sortant/`) implémentent ces contrats —
persistance PostgreSQL, cache/queue Redis, stockage objet S3, notifications
FCM/SMS (cf. ADR-0004/0005/0006). L'application dépend du port, jamais de
l'implémentation (inversion de dépendances).
"""
