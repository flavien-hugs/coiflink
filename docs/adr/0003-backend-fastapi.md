# ADR-0003 : Backend — FastAPI (API REST + JWT)

- **Statut** : Accepté
- **Date** : 2026-06-29
- **Décideurs** : équipe CoifLink
- **Issue** : #1
- **Référence PRD** : §10.2 (Backend), §10.4 (services backend), §11.1 (authentification), §12.1 (API < 3 s)

## Contexte et problème

Toutes les interfaces (mobile, web gérant, web admin) communiquent avec une **API backend
centralisée** (§10.1). Le PRD §10.2 recommande « Python FastAPI **ou** Django REST Framework »,
une **API REST**, une **authentification JWT**, la gestion des rôles, et des **jobs asynchrones**
pour les notifications. Le budget de réponse API est **< 3 s** (§12.1). Le §10.4 découpe le domaine
en services logiques (Auth, Salon, Appointment, Customer, Payment, Notification, Analytics, Admin).
Il faut trancher le framework backend avant le modèle de données (#3) et la CI (#4).

## Options envisagées

- **Option A — FastAPI (Python).** Framework asynchrone natif, léger, validation Pydantic,
  documentation OpenAPI auto-générée.
- **Option B — Django REST Framework (Python).** « Batteries incluses » : ORM, migrations, admin,
  auth intégrés ; modèle de requête majoritairement synchrone.

## Décision

Le backend est développé avec **FastAPI** (Python), exposant une **API REST** authentifiée par
**JWT** (+ refresh token).

## Justification (compromis)

- **Asynchrone natif** : FastAPI (ASGI) gère nativement l'I/O asynchrone, utile pour déléguer les
  **jobs de notification** (push/SMS) sans bloquer les requêtes (§10.2).
- **Performance** (§12.1) : framework léger, peu d'overhead, adapté au budget « API < 3 s ».
- **OpenAPI auto-générée** : la spec OpenAPI/Swagger est produite à partir du code et des modèles
  Pydantic, ce qui sert directement l'exigence de **documenter les API publiques** et facilite
  l'intégration des clients mobile/web.
- **Validation Pydantic** : contrôle d'entrée/sortie typé, fiabilisant les échanges.
- **Découplage** : se prête au découpage en services logiques du §10.4 sans imposer une structure
  monolithique.
- **Compromis accepté** : contrairement à Django REST « batteries incluses », FastAPI impose
  d'**assembler explicitement** l'ORM, les migrations et la couche d'authentification. Ce coût de
  câblage initial est **accepté** au profit de la légèreté, de la performance et de la souplesse
  d'architecture.

## Conséquences

- **Positives** : API performante, documentée automatiquement, asynchrone ; base claire pour les
  services du §10.4.
- **Négatives / risques** : davantage de composants à choisir et intégrer soi-même (voir suivi) ;
  pas d'admin auto-générée façon Django.
- **Exigences de sécurité ancrées ici** (§11.1, à implémenter en M1 — #10/#11/#12) :
  - mot de passe haché par algorithme robuste (p. ex. argon2 ou bcrypt) — **jamais en clair** ;
  - **JWT + refresh token** sécurisés ;
  - **OTP** de réinitialisation à usage unique et expirant ;
  - **protection anti-bruteforce** sur les connexions ;
  - **RBAC strict** avec isolation par salon (§11.2), routes en deny-by-default.
- **Suivi / à confirmer (non bloquant)** :
  - **ORM + outil de migrations** (p. ex. SQLAlchemy + Alembic, ou SQLModel) → précisé en #3 ;
  - **runner de tâches asynchrones** (Celery / arq / RQ, sur Redis — voir ADR-0004) → #5/#6 ;
  - **bibliothèques JWT / hachage** (p. ex. passlib + argon2/bcrypt, python-jose) → M1 ;
  - oriente le **test gate backend** `pytest` (issue #6) et la CI backend (issue #4) ;
  - **version** de Python à arrêter en #2.
