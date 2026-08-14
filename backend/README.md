# backend/ — API CoifLink (FastAPI)

API REST du backend CoifLink, conformément à **[ADR-0003](../docs/adr/0003-backend-fastapi.md)**
(FastAPI · Python · REST + JWT). Le socle (issues #2–#6) installe l'architecture hexagonale,
la CI, le schéma PostgreSQL et la politique de secrets. L'**inscription client** (US-1.1, #8),
l'**inscription gérant** (#9, compte propriétaire de salon) et la **connexion JWT** (US-1.2, #10 —
émission d'un jeton d'accès + refresh, anti-bruteforce) sont les premières fonctionnalités M1 livrées
(salons, RDV, caisse… continuent en M1→).

## Architecture (hexagonale — [ADR-0008](../docs/adr/0008-architecture-hexagonale.md))

```
coiflink_api/
  domain/         # entités & règles métier (zéro dépendance framework/I/O)
  application/    # cas d'usage
    ports/        # interfaces (typing.Protocol)
  adapters/
    inbound/      # driving : routers HTTP FastAPI (ex. health.py → /health)
    outbound/     # driven : Postgres, Redis, S3, FCM/SMS (implémentent les ports)
  main.py         # composition root : assemble l'app + monte les routers
```

La dépendance va toujours **vers l'intérieur** ; toute brique externe passe par un
**port** + un adapter sortant (jamais d'import direct d'un client d'infra depuis le domaine).

## Prérequis

- **Python ≥ 3.12** (version de référence figée par #2 — cf. [ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md)).

## Installation (environnement isolé)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -e ".[dev]"            # installe l'API + les outils de test
```

## Lancement (dev)

```bash
cp .env.example .env               # ignoré par git ; renseigner localement (aucun secret committé)
uvicorn coiflink_api.main:app --reload
```

L'API écoute alors sur `http://127.0.0.1:8000`. Endpoint de santé :

```bash
curl http://127.0.0.1:8000/health   # -> {"status":"ok"}
```

### Jeu de données de démo (`scripts/seed_dev_data.py`)

Peuple une instance locale (API démarrée + base migrée) avec des comptes et un
salon prêts à l'emploi, pour tester le design et les parcours d'authentification
du dashboard gérant sans tout créer à la main :

```bash
DATABASE_URL=postgresql://... python scripts/seed_dev_data.py
```

Passe par le contrat HTTP réel (mots de passe hachés normalement) ; seules la
suspension d'un compte et la fixation d'horaires d'ouverture passent par SQL
direct, faute d'endpoint dédié à ce stade. Idempotent (relançable sans erreur).
Comptes créés (mot de passe commun `CoifLink#2026`) :

| Compte | Téléphone | Rôle | Statut | Utilité |
| --- | --- | --- | --- | --- |
| Aïcha Koné | `0701020304` | MANAGER | ACTIVE | salon déjà créé, réservable |
| Fatou Diabaté | `0705060708` | MANAGER | ACTIVE | aucun salon → formulaire de création |
| Ibrahim Touré | `0709101112` | MANAGER | SUSPENDED | connexion refusée (401 générique) |
| Awa Bamba | `0701121314` | HAIRDRESSER | ACTIVE | refus de rôle sur `/gerant` |
| Mariam Sanogo | `0705161718` | CLIENT | ACTIVE | refus de rôle sur `/gerant` |

Provisionne et **active** aussi une borne terminal pour le salon d'Aïcha (jalon
M7, #155/#156/#157) via le contrat réel (`POST .../terminal-devices` →
`POST /auth/terminal/activate` → `POST /auth/terminal/login`), puis crée deux
fiches walk-in et deux tickets de file d'attente à travers elle. Le
`device_id`/`secret` de la borne ne sont **jamais relisibles** après coup
(§11.3) : ils ne s'affichent qu'à la première exécution (recherchez « Borne
(terminal) » dans la sortie du script) — à réinjecter côté `app-mobile` via
l'écran d'activation.

## Build & test

| Action | Commande |
| --- | --- |
| **Build** (installation du paquet) | `pip install -e .` |
| **Test** (test gate, cf. #6) | `pytest` |
| **Lint** (CI #4, cf. [ADR-0010](../docs/adr/0010-ci-cd-docker-packaging.md)) | `ruff check .` (installé via l'extra `dev`) |
| **Charge / perf** (§12.1, #52 — opt-in, hors gate) | `pip install -e ".[perf]"` puis `DATABASE_URL=… python -m perf.run` |
| **Image Docker** (build-seul en CI ; config par env, non-root) | `docker build -t coiflink-backend ./backend` |

Le répertoire [`perf/`](./perf/README.md) porte le **harnais de test de charge** des endpoints critiques
(#52, budgets §12.1) : il vit **hors** du package `coiflink_api` et **hors** de `tests/` (non collecté par
`pytest`, hors test gate ADW, hors image Docker), derrière l'extra **`perf`** (`httpx` + `locust`). Il
mesure la latence p50/p95/p99 contre un **serveur réel** et la confronte aux budgets §12.1 ; job CI dédié
**opt-in** ([`perf.yml`](../.github/workflows/perf.yml)), jamais requis. Voir [`perf/README.md`](./perf/README.md).

## Endpoints

| Méthode | Chemin | Réponse | Rôle |
| --- | --- | --- | --- |
| `GET` | `/health` | `{"status":"ok"}` | Sonde de santé (adapter entrant `adapters/inbound/health.py`) — aucune logique métier |
| `POST` | `/auth/register` | `201` + utilisateur (sans secret) | Inscription client (US-1.1, #8) — voir ci-dessous |
| `POST` | `/auth/register/manager` | `201` + utilisateur (sans secret) | Inscription gérant (compte propriétaire de salon, #9) — voir ci-dessous |
| `POST` | `/auth/login` | `200` + paire de jetons | Connexion (téléphone **ou** e-mail + mot de passe, US-1.2, #10) — voir ci-dessous |
| `POST` | `/auth/refresh` | `200` + paire de jetons | Rafraîchit le jeton d'accès depuis un refresh valide (#10) — voir ci-dessous |
| `POST` | `/auth/password/reset/request` | `202` + message générique | Demande un code de réinitialisation (SMS **ou** e-mail, US-1.3, #11) — voir ci-dessous |
| `POST` | `/auth/password/reset/confirm` | `200` + message générique | Confirme la réinitialisation (code + nouveau mot de passe, #11) — voir ci-dessous |
| `GET` | `/auth/me` | `200` + utilisateur (sans secret) | **Route protégée** — compte du porteur du jeton (#12) ; `Authorization: Bearer <access_token>` requis |
| `POST` | `/salons/{salon_id}/employees` | `201` + utilisateur (sans secret) | **Route protégée** — création d'un compte coiffeur rattaché au salon (US-1.4, #13) ; gérant du salon requis — voir ci-dessous |

> Toutes les routes ci-dessus **sauf `/auth/me` et `/salons/{salon_id}/employees`** sont
> **publiques** : elles constituent la liste d'exemption explicite du deny-by-default
> (`security.PUBLIC_ROUTE_PATHS`). **Toute route ajoutée est protégée par défaut** — voir
> « Autorisation & RBAC » ci-dessous.

## Authentification — inscription client (US-1.1, #8)

`POST /auth/register` crée un **compte client** (`role=CLIENT`, `status=ACTIVE`) à partir d'un
**nom**, d'un **numéro de téléphone** et d'un **mot de passe** (e-mail optionnel). Adapter entrant :
`adapters/inbound/auth.py` ; cas d'usage : `application/registration.py` (architecture hexagonale,
[ADR-0008](../docs/adr/0008-architecture-hexagonale.md)). Décisions de sécurité actées par
**[ADR-0012](../docs/adr/0012-hachage-argon2-strategie-otp.md)**.

- **Requête** (JSON) : `full_name` (requis), `phone` (requis), `password` (requis, ≥ 8 caractères),
  `email` (optionnel).
- **`201 Created`** : `{ id, full_name, phone, email, role, status, created_at }`. La réponse
  n'expose **jamais** `password` ni `password_hash`.
- **`409 Conflict`** : le numéro de téléphone (ou l'e-mail) est **déjà inscrit** (doublon refusé).
- **`422 Unprocessable Entity`** : validation (téléphone/mot de passe/e-mail invalides, champ manquant).

L'inscription **n'émet aucun JWT** (la connexion est l'issue #10).

**Sécurité & vie privée :**
- **Mot de passe jamais en clair** : haché par **argon2id** (`argon2-cffi`, pas de troncature 72 octets)
  derrière le port `PasswordHasher`. Le clair n'est **ni journalisé ni renvoyé**.
- **Normalisation du téléphone** en **E.164** (indicatif Côte d'Ivoire `+225` par défaut) : garantit
  l'unicité (`uq_users_phone`) — sans forme canonique, le refus de doublon serait contournable.
- **Refus de doublon** garanti à deux niveaux : pré-vérification applicative **et** contrainte base
  (course concurrente retraduite en `409`).
- **OTP** : logique de génération/vérification **pure et testable** (RNG + horloge injectés, usage
  unique, expiration, limite d'essais). **Désactivé par défaut** (`OTP_ENABLED=false`) ; l'envoi SMS
  réel est **différé** à M5 ([ADR-0006](../docs/adr/0006-notifications-fcm-sms.md)) — l'adapter de #8
  est un **stub** qui ne journalise rien. Le code OTP n'est **jamais** renvoyé ni journalisé.
- **PII** (`full_name`, `phone`, `email`) et secrets ne sont **jamais** journalisés (PRD §11.1/§11.3).

## Authentification — inscription gérant (#9)

`POST /auth/register/manager` crée un **compte propriétaire de salon** (`role=MANAGER`,
`status=ACTIVE`) à partir des **mêmes champs** que l'inscription client (**nom**, **téléphone**,
**mot de passe** ; e-mail optionnel). C'est le **prérequis** de la création d'un salon (US-2.1, #15) :
une fois inscrit, le gérant est **prêt à créer son salon** (rattachement `salons.owner_id` traité
par #15). L'inscription est **self-service** et **n'émet aucun JWT** (la connexion est l'issue #10).

Le cas d'usage `application/registration.py` est **généralisé** en `RegisterUser` paramétré par le
rôle ; l'inscription client reste la spécialisation `RegisterClient` (`role=CLIENT`). L'adapter
entrant réutilise les schémas `RegisterRequest`/`UserResponse` de #8.

- **Requête** (JSON) : `full_name` (requis), `phone` (requis), `password` (requis, ≥ 8 caractères),
  `email` (optionnel). **Aucun champ `role`.**
- **`201 Created`** : `{ id, full_name, phone, email, role: "MANAGER", status, created_at }`. La
  réponse n'expose **jamais** `password` ni `password_hash`.
- **`409 Conflict`** : le numéro de téléphone (ou l'e-mail) est **déjà inscrit** — quel que soit le
  rôle du compte existant (doublon refusé, `uq_users_phone`).
- **`422 Unprocessable Entity`** : validation (téléphone/mot de passe/e-mail invalides, champ manquant).

**Sécurité :** le **rôle `MANAGER` est attribué côté serveur**, jamais lu depuis la requête — aucun
champ `role` public n'est déclaré, donc **pas d'élévation de privilège** possible via l'inscription
(un `role` envoyé dans le corps est ignoré). Le rôle `MANAGER` seul ne confère **aucun** accès à des
données d'un autre salon : le RBAC et l'isolation par salon arrivent avec #12. Toutes les autres
garanties de l'inscription client s'appliquent à l'identique (hachage argon2id, normalisation E.164
du téléphone, refus de doublon à deux niveaux, non-journalisation des secrets/PII).

## Authentification — connexion (US-1.2, #10)

`POST /auth/login` authentifie un compte par **identifiant + mot de passe** et émet, en cas de
succès, une **paire de jetons JWT** : un **jeton d'accès** court et un **refresh token** long.
`POST /auth/refresh` échange un refresh valide contre une **nouvelle** paire (rotation). Adapter
entrant : `adapters/inbound/auth.py` ; cas d'usage : `application/authentication.py` (architecture
hexagonale). Décisions actées par **[ADR-0013](../docs/adr/0013-connexion-jwt-refresh-anti-bruteforce.md)**
(PyJWT · HS256 · refresh rotaté · anti-bruteforce en mémoire).

- **`POST /auth/login`** — corps (JSON) : `identifier` (requis — **téléphone ou e-mail**,
  auto-détecté) et `password` (requis). Réponses :
  - **`200 OK`** : `{ access_token, refresh_token, token_type: "bearer", expires_in }`
    (`expires_in` = durée du **jeton d'accès** en secondes). Le `JWT_SECRET` n'apparaît **jamais**.
  - **`401 Unauthorized`** : identifiants invalides — **message générique unique**
    (« Identifiants invalides »), **identique** que le compte soit inconnu, le mot de passe faux ou
    le compte non `ACTIVE` (anti-énumération).
  - **`429 Too Many Requests`** : trop d'échecs (anti-bruteforce), avec l'en-tête **`Retry-After`**.
  - **`422 Unprocessable Entity`** : corps malformé (champ manquant/type invalide).
  - **`503 Service Unavailable`** : `JWT_SECRET` non configuré (émission de jetons impossible) —
    `GET /health` et l'inscription restent disponibles.
- **`POST /auth/refresh`** — corps (JSON) : `refresh_token` (requis). Réponses :
  - **`200 OK`** : nouvelle paire (même schéma que `login`).
  - **`401 Unauthorized`** : refresh invalide / expiré / altéré / de mauvais `type` — message générique.

**Jeton d'accès (contrat pour le RBAC #12)** : JWT **HS256** ; claims `sub` (id utilisateur), `role`,
`type=access`, `iat`, `exp`, `jti` — **aucune PII**. Schéma d'auth **Bearer**
(`Authorization: Bearer <access_token>`). #10 **émet** les jetons et fournit la capacité de décodage
(`TokenService.decode`) ; la **protection** des routes métier (deny-by-default, isolation par salon)
relève de #12.

**Sécurité & vie privée :**
- **Mot de passe** vérifié via argon2id (`PasswordHasher.verify`) ; le clair ne vit que le temps de la
  vérification — **jamais journalisé ni renvoyé**. Le **secret**, le **condensat** et les **jetons**
  ne sont **jamais** journalisés.
- **Anti-énumération** : `401` **générique et uniforme** ; quand aucun compte ne correspond, une
  vérification argon2 **factice** est exécutée pour atténuer l'oracle temporel.
- **Anti-bruteforce (§11.1)** : rate-limit sur les **échecs** (fenêtre glissante par **identifiant +
  IP**), verrou temporisé (`429` + `Retry-After`), **réinitialisé au succès**. Store **en mémoire**
  (non partagé entre instances ; adapter Redis différé, ADR-0013).
- **Refresh** : **rotaté** à chaque rafraîchissement, avec re-lecture du `role`/`status` courant
  (compte devenu non `ACTIVE` refusé). Pas de révocation serveur / `/auth/logout` en #10 (différé).
- **Normalisation de l'identifiant** : téléphone en **E.164** (comme à l'inscription) ; e-mail
  `strip`é (casse conservée, cohérente avec le stockage de #8). Transport **Bearer** supposant HTTPS.

## Authentification — réinitialisation du mot de passe par OTP (US-1.3, #11)

Parcours de **récupération de compte en deux étapes** : demander un code à usage unique (par SMS
**ou** e-mail selon l'identifiant), puis fixer un nouveau mot de passe qui **invalide l'ancien**.
Adapter entrant : `adapters/inbound/auth.py` ; cas d'usage : `application/password_reset.py`
(architecture hexagonale). Décisions actées par
**[ADR-0014](../docs/adr/0014-reinitialisation-mot-de-passe-otp.md)** (réutilisation du domaine OTP,
anti-énumération, dépôt OTP dédié, canal e-mail *stub*, pas de migration).

- **`POST /auth/password/reset/request`** — corps (JSON) : `identifier` (requis — **téléphone ou
  e-mail**, auto-détecté). Réponses :
  - **`202 Accepted`** (**toujours**, y compris identifiant inconnu) : message **générique**
    (`{ "detail": "Si un compte correspond à cet identifiant, un code de réinitialisation a été
    envoyé." }`). Ne confirme **jamais** l'existence d'un compte (anti-énumération).
  - **`429 Too Many Requests`** (+ en-tête **`Retry-After`**) : demande rate-limitée (anti-flood /
    « SMS bombing »), message générique.
  - **`422 Unprocessable Entity`** : corps structurellement invalide (champ manquant).
- **`POST /auth/password/reset/confirm`** — corps (JSON) : `identifier`, `code`, `new_password`
  (requis). Réponses :
  - **`200 OK`** : `{ "detail": "Mot de passe réinitialisé." }`. L'ancien mot de passe ne
    s'authentifie **plus** via `POST /auth/login` ; l'utilisateur se reconnecte avec le nouveau.
  - **`400 Bad Request`** — message **générique unique** (`{ "detail": "Code de réinitialisation
    invalide ou expiré." }`) pour **tout** échec d'OTP (invalide, expiré, trop d'essais, déjà
    consommé) **et** identifiant sans défi (cause exacte jamais divulguée).
  - **`422 Unprocessable Entity`** : le **nouveau mot de passe** viole la politique (longueur 8–128).

**Sécurité & vie privée :**
- **OTP à usage unique et expirant** : logique de domaine réutilisée (ADR-0012) — consommation +
  expiration + limite d'essais + comparaison **temps constant**. Le défi est **supprimé** après
  succès (usage unique doublement garanti) ; une nouvelle demande **écrase** le défi précédent.
- **Ancien mot de passe invalidé** : le condensat (`password_hash`) est **remplacé** ; l'ancien est
  refusé à la connexion. **Limite assumée (ADR-0013)** : les **jetons déjà émis** restent valides
  jusqu'à expiration (refresh stateless non révocable) — **pas** de déconnexion serveur immédiate.
- **Anti-énumération** : `202` uniforme à la demande, `400` générique unique à la confirmation ; un
  défi est **toujours** généré (atténuation d'oracle temporel). Comptes non `ACTIVE` traités comme
  inexistants.
- **Séparation des usages** : l'OTP de reset vit dans un **dépôt dédié** ; impossible de réutiliser
  un OTP d'inscription pour un reset (ou l'inverse).
- **OTP de reset bloquant et toujours actif** : **indépendant** d'`OTP_ENABLED` (qui ne gouverne que
  l'OTP optionnel d'inscription). Les endpoints **ne dépendent pas** de `JWT_SECRET` (**pas** de
  `503`).
- **Non-journalisation** : code OTP, mot de passe en clair, condensat, numéro et e-mail ne sont
  **jamais** journalisés ni renvoyés. L'envoi SMS/e-mail réel est **différé M5** (stub no-op).

## Autorisation & RBAC (#12 — [ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md))

L'API est **fermée par défaut** (*deny-by-default*) : une route n'est accessible sans jeton que si son
chemin figure dans la liste d'exemption explicite `PUBLIC_ROUTE_PATHS`
(`adapters/inbound/security.py`). **Une route ajoutée sans rien déclarer est protégée, pas ouverte** —
un test énumère les routes de l'application et échoue si l'une n'est ni publique-listée ni gardée.

### Rôles et permissions (PRD §4.1)

La matrice vit dans le **domaine** (`domain/permissions.py`) : c'est l'**unique** source de vérité des
droits. Elle est **fermée** (un rôle inconnu n'a aucune permission) et l'`ADMIN` **n'est pas un joker
implicite** — ses droits de supervision sont listés, donc auditables.

| Rôle | Permissions (résumé — `ROLE_PERMISSIONS` fait foi) |
| --- | --- |
| `CLIENT` | Consulter salons et prestations, réserver, lire **ses** rendez-vous, consulter **ses** reçus de paiement (`PAYMENT_READ_OWN`) |
| `HAIRDRESSER` | Lire **son** salon et les RDV qui lui sont **assignés**, mettre à jour leur statut |
| `MANAGER` | Gérer **son** salon : prestations, employés, RDV, fiches clients, caisse, statistiques, **provisionner les bornes terminal** (`TERMINAL_PROVISION`, #155) |
| `ADMIN` | Supervision plateforme : lire tous les salons, les (dés)activer, gérer les comptes, KPI globaux |
| `TERMINAL` | **Borne terminal** (compte de service, #155) : **exactement** `CUSTOMER_LOOKUP_TERMINAL` + `CUSTOMER_CREATE_WALKIN` + `QUEUE_TICKET_CREATE` — **jamais** `CUSTOMER_MANAGE` ni `APPOINTMENT_BOOK` |

La **permission** dit *ce que* le rôle peut faire ; la **portée** (`domain/access.py`, PRD §11.2) dit
*sur quelles données* : un gérant n'accède qu'aux salons dont il est **propriétaire**, un coiffeur
qu'à son périmètre, un client qu'à **ses** rendez-vous. La portée est **chargée en base** — le
`salon_id` d'une requête n'est qu'une **cible à valider**. L'accès inter-salons est **bloqué**.

### Contrat HTTP (s'applique à toute route protégée)

| Situation | Statut | Corps / en-têtes |
| --- | --- | --- |
| En-tête `Authorization` absent ou mal formé | `401` | `{"detail": "Authentification requise."}` + `WWW-Authenticate: Bearer` |
| Jeton invalide, expiré, altéré, ou **refresh présenté comme jeton d'accès** | `401` | **message identique** (motif jamais divulgué) |
| Compte du jeton introuvable | `401` | idem |
| Compte non `ACTIVE` (`INACTIVE` / `SUSPENDED`) | `403` | `{"detail": "Compte désactivé."}` |
| Rôle ou permission insuffisants (§4.1) | `403` | `{"detail": "Accès refusé."}` |
| **Accès inter-salons** (salon hors portée, §11.2) | `403` | **message identique** au cas précédent |
| `JWT_SECRET` non configuré | `503` | cohérent avec `/auth/login` |

Deux invariants à ne pas affaiblir :

- **le claim `role` du JWT n'autorise rien** : le rôle et le statut sont **relus en base à chaque
  requête protégée** — une rétrogradation ou une suspension prend effet **immédiatement**, sans
  attendre l'expiration du jeton d'accès (15 min) ;
- **un refresh token ne peut pas ouvrir une ressource protégée** (`verify_access` exige
  `type == "access"`).

### Protéger une nouvelle route (mode d'emploi)

Déclarez une garde — **ne réimplémentez jamais** un contrôle d'accès dans un handler :

```python
from typing import Annotated
from fastapi import Depends
from coiflink_api.adapters.inbound.security import (
    get_current_principal, require_roles, require_permission, require_salon_scope,
)
from coiflink_api.domain.access import SalonScope
from coiflink_api.domain.permissions import Permission
from coiflink_api.domain.principal import Principal

# Authentification seule (le compte courant) :
@router.get("/exemple")
def exemple(principal: Annotated[Principal, Depends(get_current_principal)]): ...

# Permission (matrice §4.1) + portée salon (isolation §11.2) :
@router.get("/salons/{salon_id}/appointments")
def list_appointments(
    salon_id: uuid.UUID,
    scope: Annotated[SalonScope, Depends(require_salon_scope)],
    principal: Annotated[
        Principal, Depends(require_permission(Permission.APPOINTMENT_READ_SALON))
    ],
): ...
```

Conventions :

- les ressources à portée salon se montent sous **`/salons/{salon_id}/…`** (`require_salon_scope` lit
  `salon_id` du chemin) ;
- `require_roles(Role.MANAGER, Role.ADMIN)` garde par rôle ; `require_permission(...)` par verbe métier ;
- **ne jamais ajouter un chemin à `PUBLIC_ROUTE_PATHS` sans revue de sécurité** — c'est ouvrir une
  route à Internet.

## Employés — gestion des coiffeuses (US-1.4, #13/#150 — [ADR-0016](../docs/adr/0016-comptes-employes-appartenance-salon.md))

Toutes les routes ci-dessous sont **protégées** par la permission `EMPLOYEE_MANAGE` (matrice §4.1 —
seul le `MANAGER` la possède) **et** par la portée salon (`require_salon_scope`) : un gérant ne gère
d'employés que sur **son** salon (accès hors périmètre → `403` générique, aucun oracle d'existence).

### Créer un compte coiffeur

`POST /salons/{salon_id}/employees` crée le compte d'un **coiffeur** (`role=HAIRDRESSER`) rattaché à
**son** salon.

- **Corps** (JSON) : `full_name`, `phone`, `password` (mot de passe **initial**, ≥ 8 caractères),
  `email` (optionnel), `specialties`/`hired_at` (optionnels, #150 — prestations maîtrisées en texte
  libre, date d'embauche). **Aucun champ `role`** : le rôle `HAIRDRESSER` est **imposé côté serveur**
  (anti-élévation de privilège) — un `role` fourni dans le corps est ignoré.
- **Réponse** : `201` + la coiffeuse créée (**sans secret** : ni mot de passe ni condensat) ;
  `role="HAIRDRESSER"`, `status="ACTIVE"`.
- **Erreurs** : `401` ; `403` ; `409` (téléphone/e-mail déjà pris, ou employé déjà membre du salon) ;
  `422` (nom/téléphone/mot de passe/e-mail/spécialités invalides) ; `503` (`JWT_SECRET` non configuré).

**Appartenance & portée.** La création écrit une ligne dans la table d'appartenance `salon_members`
(créée par la migration `0002`, étendue par `0011`), qui devient la **source d'autorité de la
portée** du coiffeur (PRD §11.2) : il « voit » son salon **dès sa création**, sans dépendre d'un
rendez-vous assigné. La création utilisateur, l'appartenance **et** l'entrée d'audit
`EMPLOYEE_CREATED` sont écrites dans la **même transaction** — si l'une échoue, aucune n'est
persistée (pas de compte orphelin).

**Connexion du coiffeur.** Aucune route dédiée : le coiffeur se connecte via `POST /auth/login`
(#10) avec son téléphone/e-mail + mot de passe initial, puis peut le changer via le reset OTP (#11).

### Lister / charger une coiffeuse

- `GET /salons/{salon_id}/employees` → `200` + la liste des coiffeuses du salon (`role=HAIRDRESSER`),
  triée par nom d'affichage. Liste **vide** = état normal (aucune erreur).
- `GET /salons/{salon_id}/employees/{employee_id}` → `200` + la coiffeuse, ou `404` si inexistante
  **ou** hors salon (indiscernables, §11.2).

Chaque coiffeuse expose `id`, `full_name`, `phone`, `email`, `role`, `status`, `specialties`,
`hired_at`, `created_at`. **`status` reflète `salon_members.status`** (disponibilité aux
affectations) — **pas** `users.status` (compte global).

### Modifier le profil

`PUT /salons/{salon_id}/employees/{employee_id}` remplace **intégralement** identité (`full_name`,
`phone`, `email`) et champs pro (`specialties`, `hired_at`) — sémantique *replace* (comme la
modification RDV #23/fiche client #144). **Aucun** champ `role`/`status` : la disponibilité se
pilote via les deux routes ci-dessous, jamais ici.

- **Erreurs** : `404` (hors salon) ; `409` (téléphone/e-mail déjà pris par un **autre** compte —
  unicité **globale** `users`, distincte de l'unicité salon-scopée de `customer_profiles`) ; `422`.
- Journalise `EMPLOYEE_UPDATED` avec un **diff neutre** (`{"changed": [...]}`, noms de champs
  seulement — jamais une valeur, §11.3/§11.4).

### Activer / désactiver (disponibilité aux affectations)

- `DELETE /salons/{salon_id}/employees/{employee_id}` → `salon_members.status = INACTIVE`
  (idempotent). Retire la coiffeuse de l'éligibilité aux **nouvelles** affectations de ce salon
  (`_require_salon_hairdresser`, réutilisé par la réservation #21 et l'assignation manuelle #25) —
  **ne bloque pas sa connexion** (`users.status` inchangé) ni ses RDV déjà assignés.
- `POST /salons/{salon_id}/employees/{employee_id}/reactivate` → `salon_members.status = ACTIVE`
  (idempotent).
- Les deux journalisent respectivement `EMPLOYEE_DEACTIVATED`/`EMPLOYEE_REACTIVATED` (métadonnées
  vides, aucune valeur sensible).

## Borne terminal — rôle, provisioning & authentification (US-8.1, #155 — [ADR-0041](../docs/adr/0041-authentification-borne-terminal.md))

Une **borne terminal** (terminal public en salon, jalon M7) s'authentifie **en son nom propre**, sans
qu'aucun humain ne s'y connecte. Elle est un **compte de service** au rôle `TERMINAL` (cinquième membre de
l'énumération fermée `Role`), scopé à **un** salon, détenant **exactement** trois permissions dédiées
(`CUSTOMER_LOOKUP_TERMINAL`, `CUSTOMER_CREATE_WALKIN`, `QUEUE_TICKET_CREATE`) — **jamais** `CUSTOMER_MANAGE`
ni `APPOINTMENT_BOOK` (moindre privilège strict). La lecture du catalogue passe par les routes
**publiques** `/catalog/...` (aucune permission dédiée).

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/terminal-devices` | `TERMINAL_PROVISION` + portée salon | `201` device **+ secret (une fois)** · `401` · `403` · `422` |
| `GET` | `/salons/{salon_id}/terminal-devices` | `TERMINAL_PROVISION` + portée salon | `200` liste (sans secret) · `401` · `403` |
| `DELETE` | `/salons/{salon_id}/terminal-devices/{device_id}` | `TERMINAL_PROVISION` + portée salon | `200` device révoqué · `401` · `403` · `404` |
| `POST` | `/auth/terminal/login` | **publique-listée**, rate-limitée | `200` paire JWT + `salon_id` · `401` générique · `429` |

**Provisioning** (gérant, `TERMINAL_PROVISION` — seul le `MANAGER`) : crée un compte de service `TERMINAL`
(ligne `users` + rattachement `salon_members`, écritures atomiques) et **génère** un secret aléatoire
(`secrets.token_urlsafe(32)`, 256 bits). ⚠ **Le secret n'est affiché qu'une fois** (réponse `201`) — il
n'est stocké que **haché** (argon2id), jamais journalisé, jamais relisible. Provisioning et révocation
sont journalisés (`TERMINAL_DEVICE_PROVISIONED` / `TERMINAL_DEVICE_REVOKED`, `metadata` vide).

```bash
# Provisionner une borne (gérant authentifié) — le secret n'est présent que dans cette réponse.
curl -sS -X POST "$API/salons/$SALON_ID/terminal-devices" \
  -H "Authorization: Bearer $MANAGER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label":"Borne entrée"}'
# → 201 {"id":"…","salon_id":"…","label":"Borne entrée","status":"ACTIVE","created_at":"…","secret":"k7Yw…Qc"}

# La borne échange (device_id, secret) contre une paire JWT courte + son salon_id.
curl -sS -X POST "$API/auth/terminal/login" \
  -H "Content-Type: application/json" \
  -d '{"device_id":"<id>","secret":"k7Yw…Qc"}'
# → 200 {"access_token":"…","refresh_token":"…","token_type":"bearer","expires_in":900,"salon_id":"…"}

# Lister les bornes du salon (jamais de secret) ; révoquer une borne (effet immédiat).
curl -sS "$API/salons/$SALON_ID/terminal-devices" -H "Authorization: Bearer $MANAGER_ACCESS_TOKEN"
curl -sS -X DELETE "$API/salons/$SALON_ID/terminal-devices/<id>" -H "Authorization: Bearer $MANAGER_ACCESS_TOKEN"
```

**Cycle de vie d'un device** : *provisionné* (`users.status = ACTIVE`, `salon_members.status = ACTIVE`)
→ *actif* (échange son secret contre des JWT courts, portée = son salon) → *révoqué* (`DELETE` :
`users.status = SUSPENDED` **et** `salon_members.status = INACTIVE`). La révocation est **logique**
(jamais une suppression, traçabilité §11.4) et à **effet immédiat** : la relecture du statut par requête
(`get_current_principal`) coupe l'accès dès la requête suivante, et `/auth/terminal/login` répond alors le
`401` générique. **Ce qui est long est révocable, ce qui est porteur est court** : le secret de device
(stocké côté borne, #159/#161) est durable et révocable ; les JWT émis restent courts (accès 15 min).
Tout échec de `/auth/terminal/login` (device inconnu, secret faux, device révoqué) renvoie le **même** `401`
générique — aucun oracle sur l'existence ou l'état d'une borne.

## Borne — identification téléphone & création walk-in (US-8.2, #156 — [ADR-0041](../docs/adr/0041-authentification-borne-terminal.md), [ADR-0026](../docs/adr/0026-fiche-client-portee-salon.md))

Le parcours « client sans rendez-vous » de la borne (PRD §17) répond d'abord à **qui se présente ?** Deux
routes **réservées au rôle `TERMINAL`** (compte de service d'un device, #155), montées sous
`/salons/{salon_id}/terminal/customers[...]` — imbriquées sous le salon pour hériter de `require_salon_scope`
(isolation §11.2) — et **jamais publiques** (rien n'entre dans `PUBLIC_ROUTE_PATHS`) :

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/terminal/customers/lookup` | portée salon + `CUSTOMER_LOOKUP_TERMINAL` | `200` `{customer_id, first_name}` · `404` neutre · `422` téléphone invalide · `429` + `Retry-After` · `401`/`403` |
| `POST` | `/salons/{salon_id}/terminal/customers` | portée salon + `CUSTOMER_CREATE_WALKIN` | `201` `{customer_id, first_name}` · `409` doublon · `422` champ invalide · `401`/`403` |

Les deux permissions sont **dédiées au rôle `TERMINAL`** et déjà livrées par #155 : #156 **ne modifie pas**
`ROLE_PERMISSIONS`. `CUSTOMER_MANAGE` reste **MANAGER-seul** ; un JWT `CLIENT`/`MANAGER`/`HAIRDRESSER`/
`ADMIN` est refusé (`403` générique) sur ces routes, et un credential `TERMINAL` reste incapable d'atteindre
`CUSTOMER_MANAGE` ou `APPOINTMENT_BOOK` (moindre privilège, ADR-0041).

```bash
# Recherche par téléphone (le numéro voyage en CORPS, jamais en query string).
curl -sS -X POST "$API/salons/$SALON_ID/terminal/customers/lookup" \
  -H "Authorization: Bearer $TERMINAL_ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"phone":"07 00 00 00 00"}'
# → 200 {"customer_id":"…","first_name":"Awa"}   (trouvée — prénom seul)
# → 404 {"detail":"Aucune fiche pour ce numéro dans ce salon."}   (absente, sans écho du numéro)

# Création walk-in (les 3 champs requis ; ni mot de passe, ni user_id, ni genre/notes).
curl -sS -X POST "$API/salons/$SALON_ID/terminal/customers" \
  -H "Authorization: Bearer $TERMINAL_ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"first_name":"Awa","last_name":"Koné","phone":"0700000000"}'
# → 201 {"customer_id":"…","first_name":"Awa"}   (téléphone stocké +2250700000000, user_id = NULL)
# → 409 {"detail":"Une fiche existe déjà pour ce numéro dans ce salon."}   (la borne relance le lookup)
```

**Normalisation téléphone unique côté serveur, idempotente** (`normalize_phone`, indicatif par défaut
`+225`) : `07 00 00 00 00`, `0700000000`, `+225 07-00-00-00-00` et `00 225 07000000 00` produisent tous
`+2250700000000` et retrouvent **la même fiche**, qu'elle ait été créée par le gérant au dashboard (#28)
ou par la borne. Le prénom affiché est le **premier token** du `full_name` — exact pour les fiches créées
par la borne (composition contrôlée « Prénom Nom »), heuristique pour les fiches historiques du gérant.

**Sécurité & confidentialité (ADR-0026, anti-oracle).** La recherche porte **exclusivement** sur
`customer_profiles` — **jamais** la table `users` par téléphone : un numéro titulaire d'un compte CoifLink
mais sans fiche dans le salon répond `404`, indiscernable d'un numéro inconnu (préserve l'oracle
d'existence de **compte** que l'ADR-0026 protège). Défenses : **prénom seul** à l'écran (ni nom complet, ni
téléphone, ni genre, ni notes, ni compteurs) ; **isolation par salon** (`require_salon_scope` + refiltre
SQL `salon_id`) — l'énumération cross-salons est structurellement impossible ; **limitation de débit** des
échecs (`404`/`422`) par **device + IP** (réutilise `LoginRateLimiter`/`InMemoryLoginRateLimiter`, seuils
`TERMINAL_LOOKUP_*`, défaut 10 échecs / 5 min, verrou 10 min) → `429` + `Retry-After` ; **aucune PII** dans les
logs, l'audit ou les erreurs (messages neutres, clé de débit opaque, création journalisée `CUSTOMER_CREATED`
avec `metadata` vide, lookups **non audités**). **Aucune migration** : la table `customer_profiles`, l'index
unique partiel `uq_customer_profiles_salon_phone` (qui sert aussi la recherche par égalité) et la validation
de #28 couvrent déjà le besoin.

## File d'attente walk-in — tickets de passage (US-8.3, #157 — [ADR-0042](../docs/adr/0042-file-attente-walkin-queue-ticket.md))

Une fois le client identifié (#156), la borne lui délivre un **ticket de passage** : un numéro
séquentiel, une heure d'émission et une **estimation d'attente**. Le `QueueTicket` est un **domaine
indépendant** d'`Appointment` (ADR-0042) — aucune ligne `appointments` n'est jamais créée pour un
walk-in (`Appointment.client_id` est `NOT NULL` FK `users` ; un walk-in n'a en général pas de compte).
Migration `0014` **additive** : deux tables (`queue_tickets`, `queue_ticket_services`), aucune colonne
existante modifiée.

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/queue/tickets` | portée salon + `QUEUE_TICKET_CREATE` (rôle `TERMINAL`, #155) | `201` ticket · `404` fiche hors salon · `422` prestation(s) invalide(s) · `401`/`403` |
| `POST` | `/salons/{salon_id}/queue/tickets/{ticket_id}/start` | portée salon + `APPOINTMENT_UPDATE_STATUS` (coiffeuse/gérant) | `200` ticket · `404` ticket/coiffeuse hors salon · `409` transition invalide · `401`/`403` |
| `POST` | `/salons/{salon_id}/queue/tickets/{ticket_id}/complete` | portée salon + `APPOINTMENT_UPDATE_STATUS` | `200` ticket · `404` · `409` · `401`/`403` |
| `GET` | `/salons/{salon_id}/queue` | portée salon + `APPOINTMENT_READ_SALON` | `200` `{appointments, walk_in_tickets}` · `422` jour invalide · `401`/`403` |

**Numérotation par salon et par jour civil, sûre en concurrence** (patron ADR-0040) :
`SqlQueueTicketRepository.create` prend un **verrou consultatif transactionnel**
(`pg_advisory_xact_lock(hashtext('<salon_id>:<jour>'))`) puis lit `MAX(ticket_number)+1` dans la **même**
transaction. Le compteur reparte à **1 chaque jour civil** (`Africa/Abidjan`) sans job de purge ; la
contrainte `UNIQUE (salon_id, issued_date, ticket_number)` est le filet ultime d'une course. `ticket_number`
est un **entier brut** (le formatage « N° 014 » relève de l'impression thermique #160).

**Estimation d'attente V1** (`estimate_wait_minutes`, heuristique **assumée perfectible**, **figée à
l'émission**) : `position × durée moyenne des prestations des tickets actifs (waiting + in_progress) ÷
coiffeuses ACTIVE`, arrondie. Filets pour les cas dégénérés : **aucune coiffeuse active** → constante
documentée (`30 min`, jamais de division par zéro) ; **file vide** → repli sur la moyenne des prestations
**de ce ticket** ; **aucune durée** → `0`.

```bash
# Rejoindre la file (borne TERMINAL) — customer_profile_id optionnel (null = ticket anonyme).
curl -sS -X POST "$API/salons/$SALON_ID/queue/tickets" \
  -H "Authorization: Bearer $TERMINAL_ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"customer_profile_id":"…","service_ids":["…"]}'
# → 201 {"id":"…","ticket_number":7,"issued_date":"2026-08-11","status":"waiting",
#        "estimated_wait_minutes":18,"created_at":"…","service_ids":["…"]}

# Prise en charge par une coiffeuse ACTIVE du salon (gérant/coiffeuse), puis clôture.
curl -sS -X POST "$API/salons/$SALON_ID/queue/tickets/<id>/start" \
  -H "Authorization: Bearer $MANAGER_ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"hairdresser_id":"…"}'
# → 200 {"id":"…","ticket_number":7,"status":"in_progress","hairdresser_id":"…","started_at":"…","completed_at":null}
```

**Visibilité gérant — fusion en lecture, jamais en écriture.** `GET /salons/{salon_id}/queue` renvoie
désormais un **objet à deux clés** : `appointments` (RDV planifiés, contenu **inchangé** champ à champ,
#150) et `walk_in_tickets` (tickets du jour `waiting`/`called`/`in_progress`/`done`, hors `expired`).
Aucune ligne `appointments` fictive n'est jamais créée. PII minimisée à l'écran partagé : **prénom seul**
(`customer_first_name`, aligné #156) — jamais le nom complet ni le téléphone. Le seul consommateur du
contrat (`web-dashboard/.../queue-board.tsx`) est mis à jour dans la même PR.

**Sécurité & journalisation.** Aucune route publique (rien dans `PUBLIC_ROUTE_PATHS`). Toutes les
méthodes du dépôt filtrent `salon_id` en SQL (isolation §11.2) : un ticket ou un `customer_profile_id`
d'un autre salon est **indiscernable** d'un inexistant (`404`/`QueueTicketNotFound`, aucun oracle). La
prise en charge/clôture sont journalisées (`QUEUE_TICKET_STARTED`/`QUEUE_TICKET_COMPLETED`, `metadata`
vide) ; l'**émission** d'un ticket n'est pas auditée (aucune action humaine de gestion, aucune PII propre).

## Salons — création & médias (US-2.1, #15 — [ADR-0017](../docs/adr/0017-creation-salon-medias-et-reservabilite.md))

`POST /salons` permet à un **gérant** de créer un salon **rattaché à son compte** (nom, description,
téléphone, localisation). Route protégée par `SALON_CREATE` (matrice §4.1 — **seul** le `MANAGER`).
L'`owner_id` est **imposé côté serveur** depuis le principal authentifié : **aucun champ `owner_id`**
n'est lu du corps (anti-élévation de privilège). Un salon fraîchement créé a `status="ACTIVE"` et
`opening_hours=null` ⇒ **`is_bookable=false`** : **sans horaire, un salon n'est pas encore réservable**
(§8.3 ; la configuration des horaires est l'objet de #16).

- **Consultation** : `GET /salons` (ses salons) ; `GET /salons/{salon_id}` (portée salon + `SALON_READ_OWN`
  **ou** `SALON_READ_ANY` pour l'ADMIN). Un accès hors périmètre renvoie le `403` **générique**.
- **Catalogue client** : `GET /catalog/salons` (voir ci-dessous) — ressource **distincte** de gestion.
- **Médias** (logo/photos) via **URLs signées** (ADR-0005), le binaire ne transite jamais par l'API :
  `POST /salons/{id}/media/upload-url` → `PUT` navigateur→bucket → `PUT /salons/{id}/logo` /
  `POST /salons/{id}/photos` (`{ object_key }`). La clé d'objet est **fabriquée par le serveur** (sans
  PII) et **revalidée** contre le préfixe du salon. `logo_object_key` stocke une **clé**, jamais une
  URL (l'URL signée est calculée à la lecture). Sans stockage objet configuré, les routes médias
  répondent **503** — mais `POST /salons` reste possible (créer un salon sans logo).

Créer un salon **débloque mécaniquement** la portée du gérant (`salons.owner_id`) : `POST /salons/{id}/employees`
(#13) passe alors de `403` à `201`.

## Horaires d'ouverture (US-2.2, #16 — [ADR-0018](../docs/adr/0018-configuration-horaires-salon.md))

`PUT /salons/{salon_id}/opening-hours` permet à un **gérant** d'enregistrer les horaires de son salon
(protégée par `SALON_UPDATE` **et** `require_salon_scope` ; `403` générique hors périmètre). Sémantique
***replace*** : le corps remplace intégralement les horaires. La structure est **validée par le domaine
pur** (`domain/opening_hours.py`) puis **normalisée** (clés de jour minuscules, intervalles triés,
`version`, `timezone`) ; toute incohérence → **`422 InvalidOpeningHours`** (message neutre). Enregistrer
des horaires valides fait passer **`is_bookable` à `true`** (§8.3) — aucune logique de réservation n'est
ajoutée (#21+).

Contrat JSONB (colonne `salons.opening_hours`, déjà au schéma — **aucune migration**) :

```jsonc
{
  "version": 1,
  "timezone": "Africa/Abidjan",          // défaut serveur (non éditable UI MVP)
  "weekly": {
    "mon": [{ "start": "08:00", "end": "12:00" }, { "start": "14:00", "end": "18:00" }], // pause 12h–14h
    "tue": [{ "start": "08:00", "end": "18:00" }]
    // jour absent ou [] ⇒ fermé
  },
  "exceptions": [
    { "date": "2026-08-07", "closed": true, "intervals": [] },
    { "date": "2026-12-24", "closed": false, "intervals": [{ "start": "08:00", "end": "13:00" }] }
  ]
}
```

Règles : `HH:MM` 24h, `end > start` (pas de passage minuit) ; intervalles d'un jour non chevauchants
(adjacence `end == start` tolérée) ; dates d'exception distinctes ; `closed=true` ⇒ pas d'intervalle ;
au moins un créneau d'ouverture (non-vacuité) ; bornes ≤ 6 intervalles/jour, ≤ 366 exceptions.

### Gestion des prestations (US-2.3, #17)

Le **CRUD des prestations d'un salon** est monté sous `/salons/{salon_id}/services` (imbriqué pour
hériter de `require_salon_scope`, isolation §11.2). Toutes les routes sont **protégées** ; aucune n'est
publique (le catalogue client relève de #18/#19). Détails dans
[ADR-0019](../docs/adr/0019-journalisation-audit-et-prestations.md).

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/services` | `SERVICE_MANAGE` + portée | `201` + prestation | `SERVICE_CREATED` |
| `GET` | `/salons/{salon_id}/services` | `SERVICE_READ` + portée | `200` + liste (actives **et** désactivées) | — |
| `GET` | `/salons/{salon_id}/services/{service_id}` | `SERVICE_READ` + portée | `200` \| `404` | — |
| `PUT` | `/salons/{salon_id}/services/{service_id}` | `SERVICE_MANAGE` + portée | `200` (*replace*) \| `404` \| `422` | `SERVICE_UPDATED` |
| `DELETE` | `/salons/{salon_id}/services/{service_id}` | `SERVICE_MANAGE` + portée | `204` (**désactivation**) \| `404` | `SERVICE_DEACTIVATED` |
| `POST` | `/salons/{salon_id}/services/media/upload-url` | `SERVICE_MANAGE` + portée | `200` URL signée \| `422` \| `503` | — |
| `PUT` | `/salons/{salon_id}/services/{service_id}/image` | `SERVICE_MANAGE` + portée | `200` \| `404` \| `422` | `SERVICE_UPDATED` |

- **Champs** (`domain/service.py`, validation **avant** écriture — les `CHECK` SQL restent un filet) :
  `name` non vide ≤ 255 ; `price` **obligatoire**, `>= 0`, ≤ `NUMERIC(12,2)`, au plus 2 décimales ;
  `duration_minutes` **obligatoire**, entier `> 0`, ≤ 24 h ; `category` libre ≤ 128 ; `description`
  libre. `salon_id`/`id`/`is_active` ne sont **jamais** lus du corps. Invalide → **`422`**.
- **`DELETE` = désactivation (soft-delete)** : passe `is_active=false` (pas de suppression physique —
  la FK `appointment_services → services` est `ON DELETE RESTRICT`, et l'historique/`price_at_booking`
  des RDV est préservé). Une réactivation (`is_active=true`) journalise `SERVICE_REACTIVATED`.
- **Illustration de la prestation** (image/photo affichée sur la borne cliente) — décision de
  conception **miroir du logo salon** (#15, ADR-0005/ADR-0017) : le binaire ne transite **jamais** par
  l'API. Flux en deux temps :
  1. `POST .../services/media/upload-url` (corps `{content_type}`) fabrique une clé d'objet **sans
     PII** (`services/{salon_id}/{uuid}.{ext}`, MIME validé contre la liste blanche
     `domain.salon.ALLOWED_IMAGE_TYPES` — `image/png`/`image/jpeg`/`image/webp`) et renvoie une URL
     signée `PUT` (navigateur → stockage objet direct, `expires_in` secondes) ;
  2. `PUT .../services/{service_id}/image` (corps `{object_key}`) **revalide** que la clé appartient
     au préfixe de ce salon (sinon `422`, `MediaKeyMismatch` — sans quoi l'isolation §11.2 serait
     contournable *par les médias*) puis l'attache ; `object_key: null` **efface** l'illustration.
     L'ancienne image remplacée est nettoyée **best-effort** (jamais bloquant) du stockage. Journalise
     `SERVICE_UPDATED` (`metadata.changed = ["image_object_key"]`).

  L'illustration n'est **jamais** posée par `POST`/`PUT .../services` (création/modification générales) :
  action **dédiée**, découplée — la prestation peut ne pas encore exister au moment du téléversement.
  Chaque réponse `ServiceResponse` porte `image_url` (URL signée de **lecture**, ou `null` si aucune
  image ou stockage non configuré) — **jamais** la clé d'objet brute. Les **lectures** (`GET`) tolèrent
  l'absence de stockage objet (`image_url: null`) ; seule l'émission d'URL de téléversement l'exige
  (`503` sinon, miroir logo/photos salon).

**Journalisation §11.4** — la table `audit_logs` (migration `0004`, modèle ORM `AuditLog`) trace *qui*
(`actor_user_id`, UUID opaque = le `Principal`) a fait *quelle* action sur *quelle* prestation de
*quel* salon, *quand*, avec un `metadata` **neutre** (`{"changed": [...]}` : noms de champs modifiés).
L'entrée d'audit partage la **même `Session`** que la mutation (commit/rollback conjoint — pas de trace
« fantôme »). **Invariant : aucun secret ni PII dans l'audit** (`test_secrets_policy.py`). La lecture du
journal (supervision) est hors périmètre (#17 **écrit** seulement).

## Catalogue client — recherche/liste des salons (US-2.3, #18 — [ADR-0020](../docs/adr/0020-catalogue-salons-cote-client.md))

`GET /catalog/salons` liste/recherche les salons **`ACTIVE` uniquement** (§8.3) pour le client. C'est
une **ressource distincte** de `/salons` (gestion) : lecture seule, projection de **vitrine**. La route
est **publique** (ajoutée à `PUBLIC_ROUTE_PATHS`, décision de sécurité revue — voir l'ADR) : elle
répond `200` **sans jeton**. Le filtre `status = ACTIVE` est appliqué **au niveau SQL** (premier
`where`, port dédié `SalonCatalogRepository`) — un salon `INACTIVE`/`SUSPENDED` **n'apparaît jamais**.

Paramètres de requête (tous optionnels) :

| Param | Type | Défaut | Rôle |
| --- | --- | --- | --- |
| `q` | string | — | recherche par nom (`ILIKE` sous-chaîne, métacaractères `LIKE` échappés) |
| `city` | string | — | filtre par ville (insensible à la casse) |
| `commune` | string | — | filtre par commune (insensible à la casse) |
| `limit` | int (1..50) | `20` | taille de page (bornée ; hors bornes → `422`) |
| `offset` | int (≥ 0) | `0` | décalage de page |

```jsonc
// Réponse 200
{
  "items": [
    {
      "id": "…uuid…",
      "name": "Salon Élégance",
      "description": "Coiffure afro et tresses.",
      "address": "Rue des Jardins, Cocody",
      "city": "Abidjan",
      "commune": "Cocody",
      "latitude": 5.359952,
      "longitude": -3.996643,
      "logo_url": "https://…signée…",   // ou null (stockage non configuré)
      "is_bookable": false               // §8.3 : ACTIVE sans horaire ⇒ pas encore réservable
    }
  ],
  "total": 1, "limit": 20, "offset": 0
}
```

**Aucun** `owner_id`, `status`, `opening_hours`, `phone` ni timestamp dans la projection publique
(pas d'oracle de compte, pas de divulgation d'état de modération). `logo_url` est **toujours** une URL
signée (ADR-0005) ou `null` — jamais une clé d'objet brute.

## Fiche salon client — détail (US-2.4, #19 — [ADR-0021](../docs/adr/0021-consultation-salon-cote-client.md))

`GET /catalog/salons/{salon_id}` renvoie la **fiche publique** d'un salon **`ACTIVE` uniquement**
(§8.3). Même router `/catalog` (ressource distincte de gestion), **publique** (chemin littéral
`"/catalog/salons/{salon_id}"` ajouté à `PUBLIC_ROUTE_PATHS`) : répond `200`/`404` **sans jeton**. La
fiche s'appuie **exclusivement** sur `SalonCatalogRepository.get_active` (filtre `status = ACTIVE` en
SQL) — un salon `INACTIVE`/`SUSPENDED` ou inexistant renvoie **404** (« absent du catalogue », pas
d'oracle) ; un `salon_id` mal formé → **422**. Les prestations proviennent de `list_active_services`
(**actives seulement**, filtre `is_active = true` en SQL) : une prestation désactivée (#17) n'apparaît
jamais. Depuis #158, chaque prestation porte `image_url` — une **URL signée** de lecture (miroir
`logo_url`/`photos`, ADR-0005) ou `null` si aucune illustration ou stockage non configuré, jamais la
clé d'objet brute. Depuis #150, les **coiffeuses actives** du salon (`list_active_hairdressers`, filtre
`salon_members.status = ACTIVE` en SQL) sont incluses dans `hairdressers` : le client mobile peut
**optionnellement** en choisir une à la réservation (#22, `hairdresser_id` reste facultatif —
réservation au niveau salon toujours possible). Projection **minimale** (`id`/`full_name`/
`specialties`) : jamais `phone`/`email`/`hired_at`/`status` (PII de gestion, spec §A.4) ; une
coiffeuse désactivée (#150) n'apparaît jamais.

```jsonc
// Réponse 200 — GET /catalog/salons/{salon_id}
{
  "id": "…uuid…",
  "name": "Salon Élégance",
  "description": "Coiffure afro et tresses.",
  "phone": "+2250700000000",            // donnée d'établissement (reportée de #18)
  "address": "Rue des Jardins, Cocody",
  "city": "Abidjan",
  "commune": "Cocody",
  "latitude": 5.359952,
  "longitude": -3.996643,
  "logo_url": "https://…signée…",        // ou null
  "photos": [ { "id": "…uuid…", "url": "https://…signée…" } ],   // ou []
  "opening_hours": {                      // ou null si non configuré (⇒ is_bookable=false)
    "version": 1, "timezone": "Africa/Abidjan",
    "weekly": { "mon": [ { "start": "08:00", "end": "18:00" } ] },
    "exceptions": []
  },
  "services": [                           // prestations ACTIVE uniquement
    { "id": "…uuid…", "name": "Coupe homme", "description": "…",
      "price": "5000.00", "duration_minutes": 30, "category": "Coupe",
      "image_url": "https://…signée…" }   // ou null (aucune image / stockage non configuré) — #158
  ],
  "hairdressers": [                       // coiffeuses ACTIVE uniquement (#150) — choix optionnel
    { "id": "…uuid…", "full_name": "Awa Koné", "specialties": "Tresses, colorations" }
  ],
  "is_bookable": false                    // §8.3 : ACTIVE mais sans horaire ⇒ pas encore réservable
}
```

**Aucun** `owner_id`, `status` ni timestamp de salon ; **aucune** prestation `is_active`/`salon_id` ;
**aucune** coiffeuse `phone`/`email`/`hired_at`/`status` de gestion ; jamais de clé d'objet brute.
C'est le **point d'entrée** de la réservation (livrée par #21/#22, ci-dessous), `hairdresser_id`
restant facultatif à chaque étape (disponibilité et réservation).

## Rendez-vous : disponibilité & anti double-réservation (US-3.7, #21 — [ADR-0023](../docs/adr/0023-moteur-disponibilite-anti-double-reservation.md))

Deux surfaces au-dessus du **moteur de disponibilité pur** (`domain/availability.py`) et du chemin
d'écriture transactionnel (`application/appointments.py`) :

| Méthode | Route | Accès | Réponse | Erreurs |
| --- | --- | --- | --- | --- |
| `GET` | `/catalog/salons/{salon_id}/availability?date=&service_id=&hairdresser_id=` | **public** | `200` créneaux libres `{slots:[{date,start,end}]}` | `404` salon/prestation · `409` non réservable |
| `POST` | `/salons/{salon_id}/appointments` | `APPOINTMENT_BOOK` (client) | `201` RDV `PENDING` | `409` créneau pris/non réservable · `422` sans prestation · `404` salon/prestation |

- **La garantie anti double-réservation vient de la base**, pas de l'application : la contrainte
  d'exclusion `ex_appointments_hairdresser_slot` (schéma #3) tranche **deux réservations concurrentes**
  sur le même créneau/coiffeur — **une seule** aboutit (SQLSTATE `23P01` → `SlotAlreadyBooked` → `409`).
  Le contrôle applicatif `is_offered` n'est qu'une **défense en profondeur** ; il ne remplace jamais
  l'arbitrage base (TOCTOU fermé par l'`EXCLUDE`).
- **Créneau fermé-ouvert `[start, end)`** : deux créneaux dos-à-dos (`end == start`) ne sont pas en
  conflit. Fuseau **Africa/Abidjan = UTC+0** (cohérent avec `slot tsrange`). Grille MVP **15 min**.
- **Anti-élévation** : `client_id = principal.id`, `salon_id` du chemin — jamais du corps
  (`extra="ignore"`). Un `CLIENT` n'ayant aucune portée salon, la réservation **n'utilise pas**
  `require_salon_scope`. La disponibilité n'expose que les créneaux **libres** (§11.3), jamais qui
  occupe les créneaux pris. Un RDV **sans coiffeur** (`hairdresser_id` absent) est autorisé mais **hors**
  garantie (l'`EXCLUDE` ne s'applique qu'à `hairdresser_id NOT NULL`).
- **`hairdresser_id` validé contre `salon_members`** (§11.2) : l'exclusion porte sur
  `(hairdresser_id, slot)` **sans** `salon_id` — elle est donc globale, inter-salons. Un
  `hairdresser_id` qui n'est pas membre **`ACTIVE`** du salon ciblé est refusé (`404` générique) **avant**
  l'écriture, sans quoi un client pourrait occuper l'agenda d'un coiffeur d'un autre salon.

```jsonc
// POST /salons/{salon_id}/appointments — corps (jamais client_id/salon_id/status)
{ "date": "2026-08-01", "start_time": "09:00",
  "service_ids": ["…uuid…"], "hairdresser_id": "…uuid…", "client_note": "Je préfère court." }
```

### Tests de concurrence (critère d'acceptation dur — PostgreSQL requis)

La règle est **spécifique PostgreSQL** (`btree_gist` + `EXCLUDE`) : les tests de concurrence ne
s'exécutent **pas** sur SQLite et **skip proprement** sans `DATABASE_URL` (patron
`test_service_e2e.py`). Deux transactions/HTTP concurrents sur le même créneau/coiffeur → **exactement
une réussite** et un `409`.

```bash
cd backend
DATABASE_URL=postgresql://user:pwd@host/db alembic upgrade head
DATABASE_URL=postgresql://user:pwd@host/db pytest tests/test_appointment_concurrency.py -v
```

## Annulation d'un rendez-vous (client, US-3.3, #24 — [ADR-0025](../docs/adr/0025-annulation-rendez-vous-client.md))

Le client annule **son** RDV **actif** (`PENDING`/`CONFIRMED`) via une sous-ressource d'**action**,
au-dessus du **schéma inchangé** (transition d'état + motif optionnel + audit). C'est **la route** qui
décide de la transition vers `CANCELLED` — jamais un `status` soumis (anti-élévation §11.2).

| Méthode | Route | Accès | Réponse | Erreurs |
| --- | --- | --- | --- | --- |
| `POST` | `/appointments/{appointment_id}/cancellation` | `APPOINTMENT_BOOK` (client) | `200` RDV `CANCELLED` | `409` non annulable (terminé/déjà annulé) · `404` inexistant/hors appartenance · `401` · `403` |

- **Verrou d'état (§8.1)** : un RDV `COMPLETED`/`CANCELLED`/`NO_SHOW` est **non annulable** →
  `AppointmentNotCancellable` (**409**). La règle est **pure** (`is_client_cancellable`) **et**
  ré-affirmée par un **UPDATE conditionnel** `WHERE status IN ('PENDING','CONFIRMED')` (garde TOCTOU) ;
  une double annulation est un `409`. L'annulation **reste possible même si le salon est devenu non
  réservable/inactif** (on n'empêche jamais un client d'annuler).
- **Créneau libéré (mécanique)** : un RDV `CANCELLED` sort de l'ensemble actif de l'`EXCLUDE` **et** de
  `booked_slots` — son créneau **redevient disponible**, sans code dédié. L'annulation ne peut pas
  violer l'exclusion (elle **libère** un créneau).
- **Motif optionnel (§11.3)** : `reason` normalisé (trim, vide → `NULL`, borné à 500, tronqué) et écrit
  dans `cancellation_reason` — **jamais** journalisé (ni `logging`, ni métadonnées d'audit). Le contrat
  `AppointmentResponse` **n'expose pas** `cancellation_reason`.
- **Anti-élévation** : corps **sans** `client_id`/`salon_id`/`status` (`extra="ignore"`) ; appartenance
  imposée serveur (`get_owned`, §11.2) ; un RDV inexistant **ou** d'autrui est un `404` **indiscernable**.
- **Audit §11.4** : `APPOINTMENT_CANCELLED` **neutre** (`metadata={"reason_provided": bool}`) dans la
  **même** unité de travail que l'écriture (patron #17/#20/#23). **Aucune** notification (§8.4 → Épic 7).
- **Exclusion du CA = invariant, pas un calcul** : aucun agrégat de CA n'existe encore (M4/M5). Le
  prédicat de domaine pur `counts_towards_revenue(status)` (`False` pour `CANCELLED`) **documente et
  verrouille** l'invariant que M4/M5 réutiliseront — un RDV annulé est exclu du CA **par construction**.

```jsonc
// POST /appointments/{appointment_id}/cancellation — corps (jamais client_id/salon_id/status)
{ "reason": "Empêchement de dernière minute." }   // reason est facultatif
```

Les tests e2e (transition réelle, **créneau libéré**, verrou terminé, audit neutre) **skip proprement**
sans `DATABASE_URL` (patron `test_appointment_concurrency.py`).

## Planning personnel du coiffeur — lecture assignée (US-3.6, #27)

Le coiffeur **consulte** son planning : les RDV **qui lui sont assignés**, jamais ceux d'un collègue,
jamais un RDV non assigné, jamais ceux d'un autre salon (§11.2, cœur de l'AC). C'est **avant tout une
garantie d'autorisation** — la permission `APPOINTMENT_READ_ASSIGNED` (que seul le `HAIRDRESSER` détient)
est **câblée ici pour la première fois**.

| Méthode | Route | Accès | Réponse | Erreurs |
| --- | --- | --- | --- | --- |
| `GET` | `/appointments/assigned?date_from=&date_to=&status=` | `APPOINTMENT_READ_ASSIGNED` (coiffeur) | `200` `list[AppointmentResponse]` (triée par date puis heure) | `401` · `403` (rôle sans la permission) · `422` (dates absentes/mal formées, plage > 42 j, statut hors énumération) |

- **Route d'appartenance** (patron `GET /appointments` client) : **pas** de `salon_id` dans le chemin,
  **pas** de `require_salon_scope`. Le `hairdresser_id` est **imposé serveur** (`principal.id`), jamais
  un paramètre (anti-élévation §11.2) ; le dépôt refiltre `hairdresser_id` **en SQL**
  (`list_for_hairdresser`) — défense en profondeur. Un `CLIENT`/`MANAGER`/`ADMIN` reçoit un `403`
  générique (deny-by-default) ; **rien** n'est ajouté à `PUBLIC_ROUTE_PATHS`.
- **Plage bornée** : `date_from`/`date_to` **inclusifs**, amplitude ≤ `MAX_PLANNING_RANGE_DAYS` (42 j,
  garde de coût §12 réutilisée de #26) ; `date_to < date_from` ou plage trop large → `422`. Filtre
  `status` **répétable** (absent = tous statuts). Liste **plate triée** — le groupement par statut et la
  découpe jour/semaine/mois sont un concern d'affichage porté par le web (domaine de planning #26).
- **Séparation gérant / coiffeur** : la route gérant `GET /salons/{salon_id}/appointments` (#26) reste
  `APPOINTMENT_READ_SALON` et **n'est pas élargie**. #27 ajoute un **chemin de lecture parallèle**, propre
  au coiffeur ; aucune règle de portée ni permission n'est modifiée.
- **Frontière lecture/écriture (⚠ non franchie)** : la route de statut #25 est **salon-scopée**, or un
  `HAIRDRESSER` détient `APPOINTMENT_UPDATE_STATUS` **et** une portée salon. #27 se limite strictement à
  la **lecture assignment-scopée** — **aucune** action de statut coiffeur n'est exposée tant que #25
  n'impose pas `hairdresser_id == principal.id` côté écriture (suivi).
- **Aucun nouveau schéma** : la lecture s'appuie sur `hairdresser_id`/`appointment_date`/`start_time`/
  `status` (schéma #3). Les tests e2e Postgres (isolation inter-coiffeurs/inter-salons, RDV non assignés
  exclus) **skip proprement** sans `DATABASE_URL`.

## Historique de prestations — côté client (US-4.4, #30)

Le **client** consulte, depuis l'application mobile, **son propre** historique de RDV **terminés**
(`COMPLETED`), tous salons confondus — et **rien d'autre** (unique critère d'acceptation). C'est la
contrepartie cliente de l'historique salon-scopé livré au gérant (#29) : là où le gérant lit
l'historique d'une **fiche de son salon**, le client lit **ses** RDV réalisés.

| Méthode | Route | Accès | Réponse | Erreurs |
| --- | --- | --- | --- | --- |
| `GET` | `/appointments/history` | `APPOINTMENT_READ_OWN` (client) | `200` `list[AppointmentResponse]` (`COMPLETED`, du plus récent au plus ancien, prestations + `price_at_booking`) | `401` · `403` (rôle sans la permission) |

- **Route d'appartenance** (patron `GET /appointments`) : **pas** de `salon_id` dans le chemin, **pas**
  de `require_salon_scope`. Le filtre `client_id = principal.id` est **imposé serveur** — un client ne
  voit **que ses propres** RDV, jamais ceux d'un tiers (§11.2/§11.3).
- **Statut forcé serveur (« rien d'autre »)** : le jeu `CLIENT_HISTORY_STATUSES = (COMPLETED,)`
  (`domain/appointment.py`) est **décidé serveur** ; le client ne soumet **aucun** paramètre de statut.
  Impossible, par construction, d'obtenir un RDV `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` via cette
  route. La route « Mes rendez-vous » (`GET /appointments`, actifs) reste **inchangée**.
- **Ordre & montants** : lecture **du plus récent au plus ancien** (`list_for_client(newest_first=True)`,
  additif, défaut inchangé pour `GET /appointments`) ; montants = `price_at_booking` **figés** (aucun
  calcul, aucun agrégat, aucun reçu — statistiques client différées #31). Lecture seule (RDV terminal
  §8.1). **Route protégée** : **rien** ajouté à `PUBLIC_ROUTE_PATHS`.
- **Aucun nouveau schéma** : la lecture s'appuie sur `status`/`appointment_date`/`start_time` et la
  jonction `appointment_services.price_at_booking` (schéma #3), via l'index `ix_appointments_client_id`.

## Clients — fiche client (US-4.1, #28 — [ADR-0026](../docs/adr/0026-fiche-client-portee-salon.md))

Le gérant **crée une fiche client rattachée à son salon** (critère d'acceptation). Les routes sont
montées sous `/salons/{salon_id}/customers` (imbriquées pour hériter de `require_salon_scope`,
isolation §11.2) et **toutes protégées** ; #28 est la **première mise en service** de la permission
`CUSTOMER_MANAGE` (§4.1), détenue par le **seul `MANAGER`** — la matrice n'est **pas** modifiée
(l'`ADMIN` ne l'a pas : supervision ≠ exploitation). **Rien** n'est ajouté à `PUBLIC_ROUTE_PATHS`.

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/customers` | `CUSTOMER_MANAGE` + portée | `201` + fiche \| `409` doublon \| `422` | `CUSTOMER_CREATED` |
| `GET` | `/salons/{salon_id}/customers?limit=&offset=` | `CUSTOMER_MANAGE` + portée | `200` + page (`items`, `total`, `limit`, `offset`) | — |
| `GET` | `/salons/{salon_id}/customers/{customer_id}` | `CUSTOMER_MANAGE` + portée | `200` \| `404` | — |

```bash
curl -X POST "$API/salons/$SALON_ID/customers" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"full_name":"Awa Koné","phone":"0700000000","gender":"FEMALE","notes":"Préfère le samedi matin."}'
```

- **Champs** (`domain/customer.py`, validation **avant** écriture — les contraintes SQL restent un
  filet) : `full_name` **obligatoire**, non vide ≤ 255 ; `phone` **optionnel** (client walk-in),
  normalisé **E.164** (`+225` par défaut) ; `gender` **optionnel** et **fermé**
  (`FEMALE` | `MALE` | `OTHER` ; `null` = non renseigné, aucune tolérance de casse) ; `notes`
  **optionnelles** ≤ 2000, **internes au salon**. `salon_id`/`id`/`user_id`/`total_visits`/
  `last_visit_at` ne sont **jamais** lus du corps (`extra="ignore"`). Invalide → **`422`**.
- **Isolation §11.2 (cœur de l'AC)** : `require_salon_scope` sur chaque route **et** filtre `salon_id`
  en SQL dans le dépôt. Un accès inter-salons reçoit le `403` **générique** (aucun oracle d'existence) ;
  le `404` n'arrive qu'**après** validation de portée.
- **Doublon de téléphone → `409`** : garanti par l'index unique **partiel**
  `uq_customer_profiles_salon_phone` (migration `0005`). Le pré-contrôle applicatif couvre le cas
  nominal ; en concurrence, l'`IntegrityError` du perdant est retraduite en `CustomerAlreadyExists`.
  L'unicité est **par salon** — deux salons peuvent ficher le même numéro.
- **Fiche walk-in** : `user_id` reste `NULL` et **n'est pas exposé** ; la table `users` n'est
  **jamais** interrogée par téléphone (ce serait un **oracle d'existence de compte**, §11.1/§11.3).
  `last_visit_at`/`total_visits` restent à leurs défauts (`NULL`/`0`) — l'historique des visites est
  l'objet de #29.

**Journalisation §11.4/§11.3** — chaque création écrit une `AuditEntry` `CUSTOMER_CREATED`
(entité `customer`) dans la **même `Session`** que l'écriture (commit/rollback conjoint). Elle est
journalisée au titre de §11.3 (« journalisation des accès sensibles » : créer une fiche est une
**collecte de PII**) et reste **neutre** : `metadata = {}` — ni nom, ni téléphone, ni genre, ni note.
Les lectures ne sont pas journalisées. **Invariant : aucune PII dans l'audit, les logs ou les messages
d'erreur** (« Une fiche existe déjà pour ce numéro dans ce salon. » ne rappelle pas le numéro).

## Clients — note privée (US-4.5, #32 — [ADR-0026](../docs/adr/0026-fiche-client-portee-salon.md))

Le gérant **ajoute/édite une note privée** sur une fiche existante (préférences, allergies, habitudes ;
critère d'acceptation « non visible du client »). #28 saisissait la note **à la création** puis la
figeait ; #32 ajoute une **route d'écriture ciblée** — **sans migration** (la colonne
`customer_profiles.notes` `TEXT NULL` existe depuis `0001`) ni élargissement de droits. Sémantique
*replace* : la note fournie **remplace** la précédente ; `null`, chaîne vide ou blanche **efface** la
note (`notes = NULL`) — « éditer » couvre « retirer ». **Seule** `notes` est éditable ; l'édition du
nom/téléphone/genre reste hors périmètre. **Rien** n'est ajouté à `PUBLIC_ROUTE_PATHS`.

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `PUT` | `/salons/{salon_id}/customers/{customer_id}/notes` | `CUSTOMER_MANAGE` + portée | `200` + fiche à jour \| `401` \| `403` \| `404` fiche hors salon \| `422` note trop longue | `CUSTOMER_NOTE_UPDATED` |

```bash
curl -X PUT "$API/salons/$SALON_ID/customers/$CUSTOMER_ID/notes" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"notes":"Allergie au réactif X. Préfère le samedi matin."}'
# Effacer la note : -d '{"notes":null}' (ou "") → 200 avec notes:null.
```

- **Champs** : `notes` **optionnelle** ≤ 2000 (validation `normalize_notes` **avant** écriture — une
  note trop longue ne produit ni mutation ni audit). Tout champ privilégié du corps (`full_name`,
  `phone`, `gender`, `salon_id`, `id`, `user_id`, `total_visits`, `last_visit_at`) est **ignoré**
  (`extra="ignore"`). La réponse est identique à `GET` fiche (`CustomerResponse`, `updated_at` régénéré,
  **pas de `user_id`**).
- **Isolation §11.2** : `require_salon_scope` sur la route **et** filtre `(salon_id, customer_id)` en
  SQL dans `update_notes`. Un accès inter-salons reçoit le `403` **générique** (aucun oracle) ; le `404`
  n'arrive qu'**après** validation de portée. Une fiche d'un autre salon est indiscernable d'une fiche
  inexistante.
- **Permission `CUSTOMER_MANAGE`** (§4.1), détenue par le **seul `MANAGER`** — la matrice n'est **pas**
  modifiée. La note reste hors du catalogue public (#18/#19), de la disponibilité (#21) et de **toutes**
  les routes de l'application mobile : jamais exposée au client.

**Journalisation §11.4/§11.3** — chaque édition écrit une `AuditEntry` `CUSTOMER_NOTE_UPDATED`
(entité `customer`) dans la **même `Session`** que l'écriture (commit/rollback conjoint), levée
**après** `CustomerNotFound` (aucune trace pour une cible inexistante). Elle est journalisée au titre de
§11.3 (« accès sensibles » : la note peut contenir des **données de santé**, allergies) et reste
**neutre** : `metadata = {}` — ni le contenu de la note, ni l'ancienne valeur, ni un indicateur de
présence n'entre au journal.

## Clients — historique des visites (US-4.2, #29)

Le gérant **consulte l'historique des visites d'un client** — ses RDV **terminés** avec prestations et
montants (critère d'acceptation). Une route **de lecture** s'ajoute à la tranche « clients », sous le
même préfixe fiche-scopé et **protégée** par `CUSTOMER_MANAGE` + portée salon (rien n'entre dans
`PUBLIC_ROUTE_PATHS`).

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/customers/{customer_id}/appointments` | `CUSTOMER_MANAGE` + portée | `200` historique \| `401` \| `403` \| `404` fiche hors salon | — (lecture) |

```bash
curl "$API/salons/$SALON_ID/customers/$CUSTOMER_ID/appointments" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

La réponse porte les visites (`items`, plus récente d'abord) — chacune avec sa `date`, son créneau,
ses `services` (`name` + `price_at_booking`) et son `total_amount` — ainsi qu'un **résumé dérivé** :
`total_visits`, `last_visit_at`, `total_amount`, `currency` (`XOF`).

- **« Terminé » = `COMPLETED`.** L'historique liste les RDV **réalisés** (`domain/visit.py`,
  `HISTORY_STATUSES == (COMPLETED,)` — nommé distinctement de `REVENUE_STATUSES`). Les RDV
  `CANCELLED`/`NO_SHOW`/actifs ne sont **pas** des visites.
- **Montants figés.** Le montant d'une visite est la **somme des `price_at_booking`** (prix figé à la
  réservation, jamais le tarif courant) ; devise **XOF** (§9.6), `NUMERIC(12,2)` sérialisé en chaîne
  décimale (jamais de flottant). Le **nom** de prestation est le libellé courant (`services.name`) —
  résoluble même pour une prestation soft-deletée (FK `RESTRICT`).
- **Lien fiche → RDV encapsulé (anti-oracle ADR-0026).** Le pont
  `customer_profiles.user_id == appointments.client_id` (même `salon_id`) est calculé **entièrement en
  SQL** ; `user_id`/`client_id` ne sont **jamais** renvoyés ni journalisés, et `users` n'est **jamais**
  interrogée par téléphone. Une **fiche walk-in** (`user_id = NULL`) ou sans visite réalisée renvoie
  `200` avec `items: []`, `total_visits: 0`, `last_visit_at: null`, `total_amount: "0"` — comportement
  **normal**, indiscernable d'une fiche liée sans visite (aucun signal sur l'existence d'un compte).
- **Isolation §11.2 en profondeur.** `require_salon_scope` (403 générique) **et** fiche résolue via
  `(salon_id, customer_id)` (réutilise `GetCustomer` → `404` **après** portée) **et** RDV refiltrés
  `salon_id`/`client_id` en SQL : jamais les visites du même client dans un **autre** salon.
- **Agrégats dérivés en lecture** — `total_visits`/`last_visit_at`/`total_amount` sont calculés à la
  volée (`domain/visit.py::build_history`) ; les colonnes homonymes de `customer_profiles` **restent à
  leurs défauts** (aucune dénormalisation, aucune migration). Lecture pure : **aucun** audit.

## Clients — historique des paiements (fiche client)

Le gérant **consulte l'historique des paiements d'un client** — tous statuts confondus
(`PENDING`/`VALIDATED`/`CANCELLED`/`ADJUSTED`), c'est justement l'objet de la colonne « statut ». Une
route **de lecture** s'ajoute à la tranche « clients », sous le même préfixe fiche-scopé et **protégée**
par `CUSTOMER_MANAGE` + portée salon (rien n'entre dans `PUBLIC_ROUTE_PATHS`). Miroir de l'historique des
visites (#29), sur `payments` plutôt que `appointments`.

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/customers/{customer_id}/payments` | `CUSTOMER_MANAGE` + portée | `200` historique \| `401` \| `403` \| `404` fiche hors salon | — (lecture) |

```bash
curl "$API/salons/$SALON_ID/customers/$CUSTOMER_ID/payments" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

```jsonc
// 200 — paiements du compte lié, plus récent d'abord
{
  "customer_id": "…uuid…",
  "items": [
    { "payment_id": "…", "created_at": "2026-07-20T09:30:00Z", "amount": "5000.00", "currency": "XOF", "status": "VALIDATED" }
  ]
}
```

- **Tous statuts, aucun filtre.** Contrairement à l'historique des visites (borné à `COMPLETED`), la
  lecture renvoie **tous** les paiements du compte lié — `PENDING`/`VALIDATED`/`CANCELLED`/`ADJUSTED` —
  triés `created_at DESC`. Le montant reste `NUMERIC(12,2)` sérialisé en chaîne décimale (jamais de
  flottant), devise **XOF** (§9.6).
- **Lien fiche → paiement encapsulé (anti-oracle ADR-0026).** Le pont
  `customer_profiles.user_id == payments.client_id` (même `salon_id`) est calculé **entièrement en
  SQL** (`domain/visit.py::CustomerPayment`) ; `user_id`/`client_id`/`recorded_by`/`reference` ne sont
  **jamais** renvoyés ni journalisés. Une **fiche walk-in** (`user_id = NULL`) ou sans paiement
  rattaché renvoie `200` avec `items: []` — comportement **normal**, indiscernable d'une fiche liée
  sans paiement (aucun signal sur l'existence d'un compte).
- **Isolation §11.2 en profondeur.** `require_salon_scope` (403 générique) **et** fiche résolue via
  `(salon_id, customer_id)` (réutilise `GetCustomer` → `404` **après** portée) **et** paiements
  refiltrés `salon_id`/`client_id` en SQL : jamais les paiements du même compte dans un **autre**
  salon. Lecture pure : **aucun** audit.

## Clients — prestations préférées (US-4.3, #31)

Le gérant **connaît les prestations préférées d'un client** — les prestations les **plus fréquentes**,
classées de la plus à la moins fréquente (critère d'acceptation). Une route **de lecture** s'ajoute à la
tranche « clients », sous le même préfixe fiche-scopé et **protégée** par `CUSTOMER_MANAGE` + portée
salon (rien n'entre dans `PUBLIC_ROUTE_PATHS`). **Aucun nouvel accès base** : le classement est **dérivé
en lecture** des mêmes visites `COMPLETED` que l'historique #29 (`list_visits`).

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/customers/{customer_id}/stats` | `CUSTOMER_MANAGE` + portée | `200` classement \| `401` \| `403` \| `404` fiche hors salon | — (lecture) |

```bash
curl "$API/salons/$SALON_ID/customers/$CUSTOMER_ID/stats" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

```jsonc
// 200 — prestations les plus fréquentes d'abord
{
  "customer_id": "…uuid…",
  "services": [
    { "service_id": "…", "name": "Coupe homme", "count": 5, "total_amount": "25000.00" },
    { "service_id": "…", "name": "Barbe",        "count": 3, "total_amount": "6000.00"  }
  ],
  "total_visits": 6,      // visites COMPLETED considérées (dérivé)
  "total_services": 8,    // occurrences de prestations agrégées (dérivé)
  "currency": "XOF"
}
```

- **« Préférée » = fréquence des `COMPLETED`.** L'agrégation (`domain/visit.py::favourite_services`, pure)
  parcourt les visites **réalisées** (mêmes `HISTORY_STATUSES` que #29) et compte, **par `service_id`**,
  le nombre d'**occurrences** (`count`) et la **somme des `price_at_booking`** (`total_amount`). Un RDV
  `CANCELLED`/`NO_SHOW`/actif ne pèse **pas**.
- **Clé d'agrégation = `service_id`** (jamais le nom) : deux prestations distinctes partageant un libellé
  ne sont **pas** fusionnées. Le `name` affiché est le libellé **courant** (`services.name`) — résoluble
  même pour une prestation soft-deletée (FK `RESTRICT`).
- **Tri déterministe** : fréquence décroissante, puis `total_amount` décroissant, puis `name` croissant,
  puis `service_id` — ordre stable (le backend est l'autorité du classement, le front ne re-trie pas).
- **Montants figés.** `total_amount` = somme des `price_at_booking` (prix figés à la réservation, jamais
  le tarif courant) ; devise **XOF** (§9.6), `NUMERIC(12,2)` sérialisé en chaîne décimale (jamais de
  flottant).
- **Lien fiche → RDV encapsulé (anti-oracle ADR-0026).** Réutilise `list_visits` : le pont
  `customer_profiles.user_id == appointments.client_id` (même `salon_id`) reste calculé **entièrement en
  SQL** ; `user_id`/`client_id` ne sont **jamais** renvoyés ni journalisés. Une **fiche walk-in**
  (`user_id = NULL`) ou sans visite réalisée renvoie `200` avec `services: []`, `total_visits: 0`,
  `total_services: 0` — comportement **normal**, indiscernable d'une fiche liée sans visite.
- **Isolation §11.2 en profondeur.** `require_salon_scope` (403 générique) **et** fiche résolue via
  `(salon_id, customer_id)` (réutilise `GetCustomer` → `404` **après** portée) **et** RDV refiltrés
  `salon_id`/`client_id` en SQL : jamais les prestations consommées par le même client dans un **autre**
  salon. Lecture pure : **aucun** audit.

## Encaissement — enregistrement d'un paiement (US-5.1, #33)

Le gérant **encaisse une prestation** : `POST /salons/{salon_id}/payments` crée un paiement
**`VALIDATED`** lié à un RDV ou à une prestation, l'inscrit au **journal de caisse** (ligne `PAYMENT`) et
le **journalise** (`PAYMENT_RECORDED`, §11.4) dans la **même unité de travail** (atomicité). La route est
**protégée** par `PAYMENT_RECORD` (§4.1, **seul le `MANAGER`**) + portée salon ; rien n'entre dans
`PUBLIC_ROUTE_PATHS` (données financières jamais publiques). La tranche d'écriture a été livrée comme
socle de #34 (journal de caisse) ; **#33 y ajoute la vérification de cohérence du montant**.

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/payments` | `PAYMENT_RECORD` + portée | `201` paiement \| `401` \| `403` \| `422` | `PAYMENT_RECORDED` (`metadata` **vide**) |

**Règle de cohérence du montant (§5.3/§8.2, cœur de #33).** Le montant saisi doit **correspondre au prix
de la prestation liée** — il n'est plus possible d'encaisser un montant arbitraire. Le « montant
attendu » est résolu depuis une source **salon-scopée**, jamais depuis un champ soumis :

- paiement lié à un **RDV** (`appointment_id`) → attendu = **somme des `price_at_booking`** des lignes du
  RDV (prix **figés** à la réservation ; un changement de tarif ne réécrit pas l'historique) ;
- paiement lié à une **prestation seule** (`service_id`, sans RDV) → attendu = **`Service.price`** de la
  prestation **active** du salon ;
- si les deux sont fournis, la cohérence porte sur le **RDV** et le `service_id` doit faire partie de ses
  prestations.

Règle MVP = **égalité stricte au centime** (comparaison en `Decimal` quantifié à `0.01`, jamais un
flottant). Tout écart → `422` **« Le montant ne correspond pas à la prestation. »** Une référence
inexistante ou **hors salon** est **indiscernable** (aucun oracle §11.2) → `422` **« Prestation ou
rendez-vous introuvable pour ce salon. »**. Dans les deux cas, le rejet a lieu **avant** toute écriture :
**aucune** ligne `payments`/`cash_journal`/`audit_logs` n'est créée.

**Sécurité/PII.** `recorded_by` vient **toujours** du `Principal` (non-répudiation §8.2), jamais du corps ;
`status` est imposé `VALIDATED`. L'audit `PAYMENT_RECORDED` est **neutre** (`metadata = {}` : ni montant,
ni mode, ni identité client). Les messages `422` restent **métier et neutres** — ils ne reprennent **jamais**
le montant saisi ni le prix attendu (§11.3).

```bash
# Cas cohérent (montant = prix de la prestation active) → 201
curl -X POST "$API/salons/$SALON_ID/payments" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"amount": "5000.00", "payment_method": "CASH", "service_id": "'"$SERVICE_ID"'"}'

# Cas incohérent (montant ≠ prix) → 422 « Le montant ne correspond pas à la prestation. »
curl -X POST "$API/salons/$SALON_ID/payments" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"amount": "4000.00", "payment_method": "CASH", "service_id": "'"$SERVICE_ID"'"}'
```

## Historique des transactions filtrable (US-5.2, #35)

Le gérant **retrouve une transaction** : `GET /salons/{salon_id}/payments` liste les paiements du salon
**du plus récent au plus ancien**, **paginé** et **filtrable côté serveur** par **date**, **client**,
**montant** et **mode de paiement**. La route est **protégée** par `CASH_JOURNAL_READ` (§4.1, **seul le
`MANAGER`**) + portée salon ; **lecture seule** (aucune écriture, aucun audit §11.4), rien n'entre dans
`PUBLIC_ROUTE_PATHS`. La **source de vérité** est la table `payments` — la même qui alimente la ligne
`PAYMENT` du journal de caisse (#34) : montant, horodatage (`created_at`) et auteur (`recorded_by`)
**concordent** avec le journal, et un paiement corrigé apparaît **`ADJUSTED`** dans la liste **et** possède
une ligne `ADJUSTMENT` au journal.

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/payments` | `CASH_JOURNAL_READ` + portée | `200` page filtrée \| `401` \| `403` \| `422` filtre invalide | *(aucun — lecture)* |

**Filtres** (tous **optionnels**, combinés en **ET** ; absents = aucune contrainte) :

| Param | Type | Sémantique |
| --- | --- | --- |
| `date_from` / `date_to` | `date` (`YYYY-MM-DD`) | plage **inclusive**, jour civil **`Africa/Abidjan`** (UTC+0) → bornes UTC `[00:00, 23:59:59.999999]` |
| `client_id` | `uuid` | client lié (`payments.client_id`) ; un `client_id` étranger au salon → **liste vide** (aucun oracle §11.2) |
| `amount_min` / `amount_max` | `Decimal` (≥ 0, ≤ 2 déc.) | plage de montants |
| `payment_method` | `str` ∈ `PaymentMethod` | `CASH` \| `MOBILE_MONEY_MANUAL` \| `CARD_MANUAL` \| `OTHER` |
| `limit` / `offset` | `int` (1..200, défaut 50) / (≥ 0) | pagination |

**Validation (§11.3).** Une plage incohérente (`date_from > date_to`, `amount_min > amount_max`), un mode
hors énumération ou un montant mal formé → `422` **« Filtre de transactions invalide. »** — message
**métier et neutre**, sans reprendre la valeur saisie. Le filtrage est **toujours en SQL** (garde de coût
§12.1), jamais en mémoire sur un jeu complet. Chaque item réutilise `PaymentResponse` (montant **brut** +
`status`), enrichi du seul `client_name` (résolu `client_id → users.full_name`, colonne non sensible ;
`null` sinon).

```bash
# Paiements en Mobile Money de mars 2026 ≥ 10 000 FCFA (plus récent d'abord) → 200
curl -G "$API/salons/$SALON_ID/payments" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "date_from=2026-03-01" \
  --data-urlencode "date_to=2026-03-31" \
  --data-urlencode "payment_method=MOBILE_MONEY_MANUAL" \
  --data-urlencode "amount_min=10000.00"

# Plage de dates incohérente → 422 « Filtre de transactions invalide. »
curl -G "$API/salons/$SALON_ID/payments" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "date_from=2026-03-31" --data-urlencode "date_to=2026-03-01"
```

## Détection des écarts de caisse (US-5.4, #36)

Le gérant **voit ce qui a été réalisé mais pas encaissé** :
`GET /salons/{salon_id}/cash-discrepancies` liste les **RDV `COMPLETED` sans paiement rattaché** — un
écart au sens de §8.2 (« les écarts entre prestations réalisées et paiements doivent être visibles »),
**du plus récent au plus ancien**, **paginé**. La route est **protégée** par `CASH_JOURNAL_READ` (§4.1,
**seul le `MANAGER`**) + portée salon ; **lecture pure** qui **signale** sans corriger (aucune écriture,
aucun audit §11.4), rien n'entre dans `PUBLIC_ROUTE_PATHS`. Voir
[ADR-0028](../docs/adr/0028-detection-ecarts-de-caisse.md).

Le rapprochement se fait **uniquement** sur `payments.appointment_id` : un RDV est un écart s'il
n'existe **aucun** paiement `VALIDATED` **ou** `ADJUSTED` rattaché (un paiement `CANCELLED`/`PENDING` ne
couvre rien). Seul `COMPLETED` compte comme « réalisé » (jamais `NO_SHOW`/`CANCELLED`/`PENDING`/
`CONFIRMED`). Chaque écart porte le **montant attendu** (somme des `price_at_booking` du RDV — la valeur
« qui manque en caisse ») et le nom du client résolu (`users.full_name`, colonne non sensible §11.3 ;
`null` sinon). Aucune migration : la détection dérive de tables/colonnes/index existants.

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/cash-discrepancies` | `CASH_JOURNAL_READ` + portée | `200` page d'écarts \| `401` \| `403` \| `422` filtre invalide | *(aucun — lecture)* |

**Filtres** (tous **optionnels**, combinés en **ET** ; absents = aucune contrainte) :

| Param | Type | Sémantique |
| --- | --- | --- |
| `date_from` / `date_to` | `date` (`YYYY-MM-DD`) | plage **inclusive** sur `appointment_date`, jour civil **`Africa/Abidjan`** (UTC+0 ; comparaison directe, sans conversion) |
| `limit` / `offset` | `int` (1..200, défaut 50) / (≥ 0) | pagination |

**Validation.** Une plage incohérente (`date_from > date_to`) → `422`
**« Filtre des écarts de caisse invalide. »** — message **métier et neutre**. Tri, `NOT EXISTS` et
bornes sont **toujours en SQL** (garde de coût §12.1), jamais en mémoire.

```bash
# Écarts de juillet 2026 (RDV terminés non encaissés, plus récent d'abord) → 200
curl -G "$API/salons/$SALON_ID/cash-discrepancies" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "date_from=2026-07-01" --data-urlencode "date_to=2026-07-31"

# Plage de dates incohérente → 422 « Filtre des écarts de caisse invalide. »
curl -G "$API/salons/$SALON_ID/cash-discrepancies" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "date_from=2026-07-31" --data-urlencode "date_to=2026-07-01"
```

## Reçu numérique de paiement (client) (US-5.5, #38)

Le **client** récupère un **reçu numérique** de ses paiements : `GET /me/receipts` liste ses reçus **du
plus récent au plus ancien** (paginé), `GET /me/receipts/{payment_id}` renvoie un reçu précis. Ce sont
des **lectures d'appartenance** — gardées par `PAYMENT_READ_OWN` (§4.1, **seul le `CLIENT`**), **sans**
portée salon (un client paie potentiellement dans plusieurs salons). Le filtre `client_id =
principal.id` est **imposé serveur** (jamais soumis) : un client ne voit **que ses** reçus. Voir
[ADR-0030](../docs/adr/0030-recu-numerique-remise-differee.md).

Le reçu est une **projection en lecture seule** dérivée du paiement (#33) — **aucune** écriture,
**aucune** migration : montant, devise, mode, statut, référence et horodatage viennent du `payment`
(source de vérité) ; l'identité **publique** du salon (`salons.name`) est résolue depuis
`payment.salon_id` ; les **lignes** de prestation sont figées (`appointment_services.price_at_booking`
pour un RDV, `services.price` pour une prestation seule). Le total de référence reste `amount`. Montants
en **chaîne décimale** (`NUMERIC(12,2)`, jamais de flottant). **Aucune PII tierce** (jamais
`recorded_by`, ni un autre client, ni donnée de gestion).

**Non-remise assumée.** #38 **génère** un reçu **récupérable** ; il n'**envoie** rien. La remise
proactive (push FCM / SMS / e-mail) dépend du worker de notifications **différé en M5** (Épic 7,
[ADR-0006](../docs/adr/0006-notifications-fcm-sms.md)) ; le stub no-op existant n'est pas sollicité.
Rien n'entre dans `PUBLIC_ROUTE_PATHS` : un reçu financier n'est **jamais** public.

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `GET` | `/me/receipts` | `PAYMENT_READ_OWN` | `200` page de reçus \| `401` \| `403` | *(aucun — lecture)* |
| `GET` | `/me/receipts/{payment_id}` | `PAYMENT_READ_OWN` | `200` reçu \| `401` \| `403` \| `404` (tiers/inexistant, neutre) | *(aucun — lecture)* |

Un `payment_id` d'un **autre** client **ou** inexistant est un `404` **neutre indiscernable** (non-oracle
§11.3) ; un paiement **sans `client_id`** (encaissement au comptoir) n'apparaît dans **aucun** reçu
client. Bornes de pagination `1..100` (défaut `20`) ; tri, filtre et bornes **toujours en SQL**.

```bash
# Le client liste ses reçus (plus récent d'abord) → 200
curl -G "$API/me/receipts" -H "Authorization: Bearer $CLIENT_ACCESS_TOKEN"

# Un reçu précis du client → 200 ; reçu d'un tiers/inexistant → 404 neutre
curl "$API/me/receipts/$PAYMENT_ID" -H "Authorization: Bearer $CLIENT_ACCESS_TOKEN"
```

## Impression du reçu (gérant) (ADR-0040)

Le **gérant** peut consulter/imprimer le reçu d'un paiement de son salon, pour le remettre
physiquement à la cliente : `GET /salons/{salon_id}/payments/{payment_id}/receipt`, gardé par
`require_salon_scope` + `CASH_JOURNAL_READ` (§4.1, **même permission** que l'historique des
transactions #35 et le journal de caisse #34 — aucune permission nouvelle). Voir
[ADR-0040](../docs/adr/0040-impression-recu-encaissement-gerant.md), qui étend
[ADR-0030](../docs/adr/0030-recu-numerique-remise-differee.md) (#38) sans la remplacer.

Réutilise la **même** projection `Receipt`/`ReceiptLine` que le reçu client, via une seconde méthode de
lecture du dépôt (`get_receipt_for_salon`, portée **salon** au lieu de `client_id`) — inclut donc les
paiements **comptoir sans client rattaché** (`client_id` nul), invisibles du reçu client. Étend la
projection de `client_name`/`client_phone` (résolus `client_id → users.full_name/phone`, `null` pour un
paiement comptoir) — **jamais** exposés côté client (il connaît déjà sa propre identité).

**Numéro de reçu séquentiel par salon.** Depuis la migration `0012`, `payments.receipt_number`
(`INTEGER`, `UNIQUE (salon_id, receipt_number)`) remplace l'ancien identifiant dérivé de l'UUID du
paiement (révision assumée de ADR-0030 §Open Question 3) : `format_receipt_number` renvoie désormais
un libellé court `REC-000042`, identique sur le reçu client **et** le reçu gérant. Alloué **de façon
atomique** à la création du paiement (`SqlPaymentRepository.create`) via un verrou consultatif
transactionnel par salon (`pg_advisory_xact_lock`), sans nouvelle table de compteur.

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/payments/{payment_id}/receipt` | `CASH_JOURNAL_READ` + portée | `200` reçu (nom/téléphone client si rattaché) \| `401` \| `403` \| `404` (hors salon/inexistant, neutre) | *(aucun — lecture)* |

```bash
# Reçu imprimable d'un paiement du salon → 200
curl "$API/salons/$SALON_ID/payments/$PAYMENT_ID/receipt" -H "Authorization: Bearer $MANAGER_ACCESS_TOKEN"
```

**Impression : aperçu navigateur, succès *best-effort*.** Le web-dashboard imprime via `window.print()`
+ CSS `@media print` scopée (largeur 80mm par défaut) — aucun PDF serveur. L'état « imprimé » se déduit
de l'évènement `afterprint` (dialogue d'impression fermé) : un signal best-effort, pas une confirmation
matérielle (le navigateur ne peut pas savoir si le ticket est réellement sorti de l'imprimante).

**Côté client mobile**, l'écran « Mes reçus » (liste + détail, bouton « Partager ») consomme les
endpoints **déjà livrés** par #38 (`GET /me/receipts*`) — **aucun** changement backend pour cette
tranche, pas d'impression thermique réelle depuis le téléphone (partage natif uniquement).

## Chiffre d'affaires jour/semaine/mois (US-6.2, #40)

Le gérant **voit ses revenus** : `GET /salons/{salon_id}/revenue/summary` renvoie, pour une **date de
référence** (jour civil `Africa/Abidjan`, défaut = aujourd'hui), le chiffre d'affaires du salon sur
**trois périodes** — le **jour**, la **semaine** civile (**lundi → dimanche**) et le **mois** civil qui la
contiennent. La route est **protégée** par `STATS_READ_SALON` (§4.1, **seul le `MANAGER`**) + portée
salon (`require_salon_scope`) ; c'est le **deuxième** usage de `STATS_READ_SALON` après le décompte RDV
du jour (US-6.1, #39). **Lecture pure** (aucune écriture, aucun audit §11.4) ; rien n'entre dans
`PUBLIC_ROUTE_PATHS` — une donnée financière n'est jamais publique.

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/revenue/summary` | `STATS_READ_SALON` + portée | `200` CA (3 périodes) \| `401` \| `403` \| `422` `date` mal formée | *(aucun — lecture)* |

Le CA dérive de la **même source de vérité** que les autres lectures financières — le **journal de
caisse** (#34) : la **somme signée** des lignes `PAYMENT`/`ADJUSTMENT`, donc **nette des corrections** (un
paiement corrigé fait **baisser** le CA, comme le « montant net » de #37). C'est bien un CA **« calculé à
partir des paiements »** (AC #40) ; **« annulés exclus »** (§8.1) est vrai **par construction** — un RDV
`CANCELLED` n'a ni paiement ni ligne de journal, donc **aucune** contribution. Le calcul est **en base**
(`SUM` sur un intervalle couvert par l'index `ix_cash_journal_salon_id (salon_id, created_at)`), sans
rapatrier de ligne : la réponse ne porte **que** des montants (`Decimal` en chaîne, `NUMERIC(12,2)`), des
dates et la devise (§11.3). Un salon **sans activité** → totaux à `0.00` (état vide légitime, ≠ erreur).

```bash
# CA du salon à la date du jour (Africa/Abidjan) → 200
curl -G "$API/salons/$SALON_ID/revenue/summary" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# CA pour une date de référence explicite (semaine/mois dérivés côté serveur) → 200
curl -G "$API/salons/$SALON_ID/revenue/summary" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "date=2026-08-02"
```

```json
{
  "reference_date": "2026-08-02",
  "currency": "XOF",
  "day":   { "date_from": "2026-08-02", "date_to": "2026-08-02", "total": "35000.00" },
  "week":  { "date_from": "2026-07-27", "date_to": "2026-08-02", "total": "210000.00" },
  "month": { "date_from": "2026-08-01", "date_to": "2026-08-31", "total": "185000.00" }
}
```

## Prestations les plus demandées (US-6.3, #41)

Le gérant **connaît ses prestations les plus demandées** : `GET /salons/{salon_id}/service-demand` renvoie
les prestations du salon **classées par volume et par revenu** (deux ordres, **mêmes** entrées). La route
est **protégée** par `STATS_READ_SALON` (§4.1, **seul le `MANAGER`**) + portée salon (`require_salon_scope`)
; c'est le **troisième** usage de `STATS_READ_SALON` après le décompte RDV du jour (US-6.1, #39) et le CA
(US-6.2, #40). **Lecture pure** (aucune écriture, aucun audit §11.4) ; rien n'entre dans
`PUBLIC_ROUTE_PATHS` — une donnée d'exploitation salon n'est jamais publique. Le segment `service-demand`
est **distinct** de `/{salon_id}/services/{service_id}` (aucun littéral parsé comme un `service_id`).

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/service-demand` | `STATS_READ_SALON` + portée | `200` deux classements \| `401` \| `403` \| `422` bornes mal formées/incohérentes | *(aucun — lecture)* |

Le classement est **dérivé en lecture** des RDV **réalisés** (`COMPLETED`, imposé serveur — « réalisées
uniquement ») : par prestation, `volume` = **nombre d'occurrences** (`COUNT`) et `revenue` = **somme des
`price_at_booking`** (prix **figés** à la réservation, XOF, `Decimal` en chaîne `NUMERIC(12,2)`). Le calcul
est **en base** (`GROUP BY service_id`, jointure `appointment_services`/`services` par la composite
`(salon_id, service_id)`, index `ix_appointments_salon_id` + `ix_appointment_services_service_id`), sans
rapatrier de ligne : la réponse ne porte **que** des libellés, des compteurs, des montants, la période et la
devise (§11.3) — **aucune** PII (`client_id`, `appointment_id`, ligne de RDV/paiement). Le tri des deux
classements (par volume décroissant, par revenu décroissant, départages déterministes) est une **fonction
pure du domaine** (`domain/service_demand.py`). Une prestation **désactivée** (`is_active = false`) présente
dans un RDV réalisé reste **nommée** (le classement reflète l'**historique réalisé**, pas le catalogue
courant). Un salon **sans RDV réalisé** → classements **vides** (état vide légitime, ≠ erreur).

Les bornes `date_from`/`date_to` (jour civil `Africa/Abidjan`) sont **optionnelles** — absentes = **toute
l'histoire** ; une seule fournie laisse l'autre borne ouverte ; `date_to < date_from` → `422`.

> **Revenu par prestation ≠ CA du salon (#40).** Ce revenu (valeur des prestations réalisées, somme des
> `price_at_booking` des RDV `COMPLETED`) mesure une grandeur **différente** du CA #40 (dérivé du **journal
> de caisse net** — paiements réellement encaissés, net des `ADJUSTMENT`) : un RDV `COMPLETED` non payé
> compte ici mais pas dans le CA #40 ; une correction (#34) baisse le CA #40 mais pas ce revenu. Les
> `payments` d'un RDV multi-prestations n'étant pas ventilés par prestation, `price_at_booking` est la
> **seule** source d'un revenu **par prestation** (base déjà utilisée par #31).

```bash
# Prestations les plus demandées du salon, tout l'historique → 200
curl -G "$API/salons/$SALON_ID/service-demand" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# Sur une fenêtre de dates (Africa/Abidjan) → 200
curl -G "$API/salons/$SALON_ID/service-demand" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "date_from=2026-08-01" \
  --data-urlencode "date_to=2026-08-31"
```

```json
{
  "currency": "XOF",
  "date_from": null,
  "date_to": null,
  "by_volume": [
    { "service_id": "…", "name": "Coupe homme", "volume": 42, "revenue": "210000.00" },
    { "service_id": "…", "name": "Barbe",        "volume": 30, "revenue": "60000.00"  }
  ],
  "by_revenue": [
    { "service_id": "…", "name": "Coupe homme", "volume": 42, "revenue": "210000.00" },
    { "service_id": "…", "name": "Tresses",      "volume": 12, "revenue": "180000.00" }
  ]
}
```

## Clients actifs — nouveaux / récurrents / inactifs (US-6.4, #42)

Le gérant **segmente ses clients** sur une période : `GET /salons/{salon_id}/active-clients` renvoie la
répartition des clients du salon en **trois compteurs** — **nouveaux**, **récurrents** et **inactifs**. La
route est **protégée** par `STATS_READ_SALON` (§4.1, **seul le `MANAGER`**) + portée salon
(`require_salon_scope`) ; c'est le **quatrième** usage de `STATS_READ_SALON` après le décompte RDV du jour
(US-6.1, #39), le CA (US-6.2, #40) et les prestations les plus demandées (US-6.3, #41). **Lecture pure**
(aucune écriture, aucun audit §11.4) ; rien n'entre dans `PUBLIC_ROUTE_PATHS` — une donnée d'exploitation
salon n'est jamais publique. Le segment `active-clients` est **distinct** de `/{salon_id}/customers/…`
(router `customers.py`, permission `CUSTOMER_MANAGE`, fiche-scopé) : il reste sous `STATS_READ_SALON`.

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/active-clients` | `STATS_READ_SALON` + portée | `200` trois compteurs \| `401` \| `403` \| `422` bornes mal formées/incohérentes | *(aucun — lecture)* |

La segmentation est **dérivée en lecture** des **comptes ayant des RDV réalisés** (`COMPLETED`, imposé
serveur — « réalisées uniquement », une « visite » au sens de #29). Relativement à la période
`[date_from, date_to]`, un client est **nouveau** si sa **première** visite au salon tombe dans la période,
**récurrent** s'il a été vu **dans** la période **et** **avant**, **inactif** s'il a été vu **avant** mais
pas dans la période. Les trois segments sont **mutuellement exclusifs** ; `active = new + recurring` (clients
vus sur la période) est exposé pour éviter un recalcul côté front. Le calcul est **en base**
(`GROUP BY client_id`, `MIN(appointment_date)` + deux `SUM(CASE …)` filtrés, index
`ix_appointments_salon_id`), sans rapatrier de ligne ni le `client_id` (**groupé mais jamais sélectionné**) :
la réponse ne porte **que** des compteurs et des dates (§11.3) — **aucune** PII (`client_id`,
`appointment_id`, nom, téléphone, ligne de RDV). La règle de classification est une **fonction pure du
domaine** (`domain/client_segments.py`). Un salon **sans RDV réalisé** sur la période → compteurs à `0`
(état vide légitime, ≠ erreur).

Les bornes `date_from`/`date_to` (jour civil `Africa/Abidjan`) sont **optionnelles** — absentes (ou une
seule fournie) = **mois civil courant** (résolu serveur, `month_bounds`, symétrie #40) ; `date_to <
date_from` → `422`.

> **Segmentation par compte, pas par fiche.** #42 segmente les **comptes** qui réservent
> (`appointments.client_id`), seule source portant des visites réelles. Une **fiche walk-in sans compte**
> (`customer_profiles.user_id = NULL`, #28) n'apparaît dans aucun segment — elle ne se relie à aucun RDV
> (point dur hérité de #29). #42 ne renvoie **que** des compteurs : la consultation nominative d'un client
> reste la **fiche** (#28/#29/#31, permission `CUSTOMER_MANAGE`), jamais ce KPI.

```bash
# Clients actifs du salon, mois civil courant (défaut) → 200
curl -G "$API/salons/$SALON_ID/active-clients" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# Sur une fenêtre de dates explicite (Africa/Abidjan) → 200
curl -G "$API/salons/$SALON_ID/active-clients" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "date_from=2026-08-01" \
  --data-urlencode "date_to=2026-08-31"
```

```json
{
  "date_from": "2026-08-01",
  "date_to": "2026-08-31",
  "new": 12,
  "recurring": 27,
  "inactive": 8,
  "active": 39
}
```

## Performance des coiffeurs — prestations, CA, taux d'annulation (US-6.5, #43)

Le gérant **mesure la performance de ses coiffeurs** : `GET /salons/{salon_id}/hairdresser-performance`
renvoie, pour une période, **une ligne par coiffeur** assigné à ≥ 1 RDV du salon, portant les **prestations
réalisées**, le **CA généré** et le **taux d'annulation**. La route est **protégée** par `STATS_READ_SALON`
(§4.1, **seul le `MANAGER`**) + portée salon (`require_salon_scope`) ; c'est le **cinquième** usage de
`STATS_READ_SALON` après le décompte RDV du jour (US-6.1, #39), le CA (US-6.2, #40), les prestations les
plus demandées (US-6.3, #41) et les clients actifs (US-6.4, #42). **Lecture pure** (aucune écriture, aucun
audit §11.4) ; rien n'entre dans `PUBLIC_ROUTE_PATHS` — une donnée d'exploitation salon n'est jamais
publique. Le segment `hairdresser-performance` est **distinct** des autres routes `/{salon_id}/…` (aucun
littéral n'est parsé comme un UUID).

| Méthode | Chemin | Garde(s) | Réponse | Audit §11.4 |
| --- | --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/hairdresser-performance` | `STATS_READ_SALON` + portée | `200` une ligne/coiffeur \| `401` \| `403` \| `422` bornes mal formées/incohérentes | *(aucun — lecture)* |

**Trois indicateurs, deux sources autoritaires.** Prestations réalisées et taux d'annulation dérivent **du
planning** (`appointments` assignés — même source que #26/#27/#39) ; le CA dérive **de la caisse** (net
`cash_journal` — même source que #40/#34). Chaque indicateur est ainsi **cohérent avec son autorité** (le
critère d'acceptation #43) :

- **`services_completed`** — occurrences des prestations réalisées : `COUNT` des lignes
  `appointment_services` des RDV **`COMPLETED`** assignés au coiffeur (mêmes « occurrences » que le volume
  #41, filtrées par `hairdresser_id`) ;
- **`revenue`** — CA net **attribué** au coiffeur : somme signée des lignes `cash_journal`
  `PAYMENT`/`ADJUSTMENT`, attribuée par la chaîne `cash_journal → payments.appointment_id →
  appointments.hairdresser_id`, **net des corrections** (#34) — un `ADJUSTMENT` fait **baisser** le CA du
  coiffeur ;
- **`cancellation_rate`** — taux d'annulation : `cancelled_count / total_count` (`Decimal`, `"0.0000"` si
  `total_count == 0`), exposé **avec** ses deux compteurs bruts (`cancelled_count` = RDV `CANCELLED`,
  `total_count` = **tous** les RDV assignés sur la période). Un `NO_SHOW` (**absence**) ne compte **pas**
  comme annulation (statut distinct).

Les statuts (`COMPLETED`, `CANCELLED`) sont **décidés serveur**, jamais soumis par l'appelant. Le calcul est
**en base** (deux `GROUP BY hairdresser_id`, index `ix_appointments_salon_id` / `ix_cash_journal_salon_id`),
sans rapatrier de ligne : la réponse ne porte **que** l'identité **d'affichage** de l'employé
(`hairdresser_id` + `hairdresser_name` = `users.full_name`, convention #34), des compteurs, des montants
(`Decimal` en chaîne), un taux (`Decimal` en chaîne) et des dates — **jamais** de PII **client**
(`client_id`, `appointment_id`) ni de **contact employé** (`phone`/`email`/`role`). Le calcul du taux et
l'ordre du classement (CA décroissant, puis prestations, puis nom) sont une **fonction pure du domaine**
(`domain/hairdresser_performance.py`). Un salon **sans coiffeur assigné** sur la période → liste **vide**
(état vide légitime, ≠ erreur).

Les bornes `date_from`/`date_to` (jour civil `Africa/Abidjan`) sont **optionnelles** — absentes (ou une
seule fournie) = **mois civil courant** (résolu serveur, `month_bounds`, symétrie #42) ; `date_to <
date_from` → `422`.

> **Écarts de couverture assumés.** Le CA d'#43 est **attribué par RDV** : les paiements **sans RDV**
> (prestation directe, `appointment_id IS NULL`) et les RDV **non assignés** (`hairdresser_id IS NULL`) sont
> **inattribuables** et **exclus** des lignes coiffeur — la somme des CA par coiffeur peut donc **différer**
> du CA salon #40. Le CA est en outre borné par `appointment_date` (axe **planning**, pas
> `cash_journal.created_at`), ce qui **aligne les trois indicateurs sur la même période**. La liste des
> coiffeurs dérive **du planning** : un coiffeur avec du CA mais aucun RDV assigné dans la fenêtre n'apparaît
> pas. Voir [ADR-0031](../docs/adr/0031-performance-des-coiffeurs.md).

```bash
# Performance des coiffeurs, mois civil courant (défaut) → 200
curl -G "$API/salons/$SALON_ID/hairdresser-performance" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# Sur une fenêtre de dates explicite (Africa/Abidjan) → 200
curl -G "$API/salons/$SALON_ID/hairdresser-performance" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "date_from=2026-08-01" \
  --data-urlencode "date_to=2026-08-31"
```

```json
{
  "currency": "XOF",
  "date_from": "2026-08-01",
  "date_to": "2026-08-31",
  "hairdressers": [
    {
      "hairdresser_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "hairdresser_name": "Awa Koné",
      "services_completed": 58,
      "revenue": "290000.00",
      "cancelled_count": 3,
      "total_count": 64,
      "cancellation_rate": "0.0469"
    }
  ]
}
```

## Dashboard Manager — activité du salon (§7.2, #148 — [ADR-0039](../docs/adr/0039-dashboard-manager-activite-salon.md))

Écran d'activité « temps réel » consolidé au-dessus du socle analytique #39–#43 : quatre **cartes KPI**
(+ évolution vs période précédente), deux **graphiques** (CA, fréquentation), une **liste des
prestations en cours**, une **timeline des dernières activités** et des **alertes importantes**, sous
`/salons/{salon_id}/dashboard/*`. **Sixième+** usage de `STATS_READ_SALON` (§4.1, **seul le `MANAGER`**)
après RDV du jour (#39), CA (#40), prestations demandées (#41), clients actifs (#42) et performance des
coiffeurs (#43) — même garde `require_salon_scope`, même router `stats.py` (aucun nouveau router monté).
**Entièrement dérivé en lecture** : aucune migration, aucun nouveau statut, aucun audit §11.4.

| Méthode | Chemin | Réponse | PII |
| --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/dashboard/kpis?period&date_from&date_to&reference` | `200` 4 KPI + évolution \| `401` \| `403` \| `422` période mal formée | Non |
| `GET` | `/salons/{salon_id}/dashboard/revenue-series?period&date_from&date_to&reference` | `200` buckets `{bucket_start,bucket_end,total}` \| `401` \| `403` \| `422` | Non |
| `GET` | `/salons/{salon_id}/dashboard/attendance-series?period&date_from&date_to&reference` | `200` buckets `{bucket_start,bucket_end,count}` \| `401` \| `403` \| `422` | Non |
| `GET` | `/salons/{salon_id}/dashboard/in-progress` | `200` liste `{client_name,service_names,hairdresser_name,start_time,end_time,status}` \| `401` \| `403` | Nom d'affichage |
| `GET` | `/salons/{salon_id}/dashboard/activity?limit` | `200` flux fusionné `{occurred_at,kind,label,amount?,client_name?}` \| `401` \| `403` \| `422` | Nom d'affichage (paiements) |
| `GET` | `/salons/{salon_id}/dashboard/alerts` | `200` `{kind,severity,count}` \| `401` \| `403` | Non |

**Définitions dérivées (ADR-0039, aucune migration).** Le modèle MVP n'a que cinq statuts de RDV
(`PENDING/CONFIRMED/CANCELLED/COMPLETED/NO_SHOW`, PRD §9.4) et aucune colonne d'horodatage
d'arrivée/début/fin :

- **« Prestations en cours »** = RDV `CONFIRMED` dont le créneau contient l'instant présent — le
  prédicat SQL réel `slot @> now::timestamp` sur la colonne générée `slot` (déjà présente pour
  l'exclusion anti-double-réservation #21), fuseau salon `Africa/Abidjan` = UTC+0. **Instantané**, sans
  évolution.
- **« Clients en attente »** = RDV `PENDING` sur la période (la source « queue » la plus proche
  existante) — aucune salle d'attente walk-in (§16.7/§17, hors MVP).
- **« Nombre de clientes »** = comptes distincts (`COUNT(DISTINCT client_id)`) ayant un RDV `COMPLETED`
  sur la période (une **visite**, §8.1, cohérent avec `active = new + recurring` de #42).
- **Filtre de période** = `today | week | month | custom`, résolu **côté serveur** en bornes de jour
  civil (réutilise `day_bounds`/`week_bounds`/`month_bounds` de #40) ; **évolution** = comparaison à la
  **période précédente de même longueur**, calculée serveur (le front n'a rien à recalculer).
- **Alertes** — `payment_anomaly` (écarts de caisse #36, RDV `COMPLETED` sans paiement), `late` (RDV
  `CONFIRMED` du jour dont le créneau est passé sans clôture), `prolonged_wait` (RDV `PENDING` du jour
  dont le début est dépassé) — ne renvoyées que si leur effectif est `> 0`, ordre d'affichage stable.

> **Non représenté au MVP (dashboard).** « Arrivée cliente », « début » et « fin » de prestation
> **n'ont pas de source horodatée dans `dashboard/activity`** : la timeline reste bornée aux faits
> **réellement horodatés** — paiements et notifications salon `NEW_BOOKING`/`CANCELLATION`/
> `APPOINTMENT_UPDATE` (#47/#48, libellé neutre). Le pointage réel arrivée/début existe **depuis #150**
> (`arrived_at`/`started_at`, ci-dessous) mais alimente la **file d'attente**, pas cette timeline —
> les deux lectures restent volontairement séparées. Voir [ADR-0039](../docs/adr/0039-dashboard-manager-activite-salon.md).

## File d'attente & pointage réel (§7.2, #150)

Vue opérationnelle de la journée pour le gérant : la liste des rendez-vous **existants** (confirmés ou
réalisés du jour) avec leur statut de file dérivé, plus deux actions de **pointage manuel** (arrivée,
début de prestation). Complète le Dashboard Manager (#148) sans le modifier : aucune nouvelle
dépendance, mêmes conventions RBAC/isolation.

| Méthode | Chemin | Permission | Réponse |
| --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/queue?day` | `APPOINTMENT_READ_SALON` | `200` liste triée par heure \| `401` \| `403` \| `422` jour mal formé |
| `POST` | `/salons/{salon_id}/appointments/{id}/arrival` | `APPOINTMENT_UPDATE_STATUS` | `200` RDV à jour (idempotent) \| `401` \| `403` \| `404` \| `409` non `CONFIRMED` |
| `POST` | `/salons/{salon_id}/appointments/{id}/start` | `APPOINTMENT_UPDATE_STATUS` | `200` \| `401` \| `403` \| `404` \| `409` arrivée/coiffeuse manquante ou non `CONFIRMED` |

**Portée : RDV existants uniquement.** La file liste les RDV du jour dont `status ∈ {CONFIRMED,
COMPLETED}` — ni `PENDING` (non confirmé), ni `CANCELLED`/`NO_SHOW`. Aucune création de RDV « walk-in »
sans réservation (décision produit, hors périmètre #150).

**Pointage réel — deux colonnes, pas un nouveau statut (migration `0011`).** `appointments.arrived_at`/
`started_at` (`TIMESTAMPTZ NULL`) sont posées par les deux actions ci-dessus, **indépendamment** de
`status` (`AppointmentStatus` reste à cinq valeurs, `domain/appointment.py` inchangé) :

- **`waiting`** (« En attente ») = `CONFIRMED` et `started_at IS NULL`. `arrived_at` est **informatif**
  (affiché) — il ne fait pas franchir d'étape à lui seul.
- **`in_progress`** (« En cours ») = `CONFIRMED` et `started_at IS NOT NULL`.
- **`completed`** (« Terminée ») = `COMPLETED` **sans** paiement validé rattaché.
- **`paid`** (« Payée ») = `COMPLETED` **avec** un paiement `VALIDATED`/`ADJUSTED` rattaché — dérivé du
  **paiement réel** (réutilise l'encaissement #33/#34, `PaymentRepository.list_paid_appointment_ids`,
  même prédicat que les écarts de caisse #36) : aucun drapeau `paid` n'est stocké sur le RDV.

**Actions.** « Marquer l'arrivée » (`POST .../arrival`) et « Démarrer la prestation »
(`POST .../start`) sont **idempotentes** : un second appel ne décale pas l'horodatage déjà posé (pas de
double-clic accidentel). Démarrer exige l'arrivée déjà pointée **et** une coiffeuse déjà assignée
(`AppointmentArrivalRequired`/`AppointmentHairdresserRequired` → `409` sinon) ; l'assignation elle-même
réutilise `PUT .../hairdresser` (#25, ci-dessus). « Terminer » réutilise `POST .../status`
(`target=COMPLETED`, #25) ; « Marquer payée » réutilise `POST /salons/{id}/payments` (#33) avec
`appointment_id` — **aucune nouvelle route d'écriture** pour ces deux dernières étapes.

Chaque ligne de la file (`GET .../queue`) porte `appointment_id`, `client_name`, `service_names`,
`hairdresser_id`/`hairdresser_name`, `start_time`/`end_time`, `status`, `queue_status`, `arrived_at`/
`started_at` — noms d'affichage seuls (§11.3, patron #43/#36), jamais `client_id`/contact.
`hairdresser_id` reste exposé (opaque, non-PII) : le gérant en a besoin pour l'assignation. Journalise
`APPOINTMENT_ARRIVED`/`APPOINTMENT_STARTED` (métadonnées vides — aucune valeur, §11.4).

```bash
# File du jour (défaut : aujourd'hui) → 200
curl -G "$API/salons/$SALON_ID/queue" -H "Authorization: Bearer $ACCESS_TOKEN"

# Pointer l'arrivée d'une cliente → 200 (idempotent)
curl -X POST "$API/salons/$SALON_ID/appointments/$APPOINTMENT_ID/arrival" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

```json
[
  {
    "appointment_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "client_name": "Awa Koné",
    "service_names": ["Tresses"],
    "hairdresser_id": "9c858901-8a57-4791-81fe-4c455b099bc9",
    "hairdresser_name": "Fatou Diarra",
    "start_time": "09:00:00",
    "end_time": "10:30:00",
    "status": "CONFIRMED",
    "queue_status": "in_progress",
    "arrived_at": "2026-08-09T08:55:00Z",
    "started_at": "2026-08-09T09:02:00Z"
  }
]
```

**Émission maîtrisée (§11.3).** `kpis`/`revenue-series`/`attendance-series` sont **counts-only**
(compteurs, montants en chaîne décimale, dates — aucune PII, `client_id` groupé mais jamais émis).
`in-progress`/`activity` émettent **uniquement** un nom d'affichage (`users.full_name`,
`services.name`, patron #43/#36) — jamais `client_id`/`user_id`/contact. Isolation §11.2 en profondeur
(`WHERE salon_id` réaffirmé en SQL) sur chaque route. Graphiques rendus en **SVG inline** côté serveur
(aucune nouvelle dépendance) ; auto-refresh **polling visibility-aware** côté web (`router.refresh()`,
jeton jamais exposé) — voir `web-dashboard/README.md`.

```bash
# 4 KPI + évolution, période = aujourd'hui (défaut) → 200
curl -G "$API/salons/$SALON_ID/dashboard/kpis" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# Prestations en cours maintenant (noms d'affichage) → 200
curl -G "$API/salons/$SALON_ID/dashboard/in-progress" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

```json
{
  "period": { "kind": "today", "date_from": "2026-08-09", "date_to": "2026-08-09" },
  "waiting_clients": { "current": 3, "previous": 5, "delta": -2, "direction": "down" },
  "in_progress": { "current": 2 },
  "revenue": { "current": "125000.00", "previous": "98000.00", "delta": "27000.00", "direction": "up", "currency": "XOF" },
  "clients_count": { "current": 18, "previous": 15, "delta": 3, "direction": "up" }
}
```

## Notifications — confirmation de RDV (US-7.1, #45 — [ADR-0033](../docs/adr/0033-notification-confirmation-rdv.md))

À la **création d'un rendez-vous** (`POST /salons/{salon_id}/appointments`, #21), une **confirmation**
est désormais **émise/tracée** : `BookAppointment` **persiste une** ligne `notifications`
(`type = CONFIRMATION`, `status = PENDING`, rattachée au **client** `user_id`, au `salon_id` et à
l'`appointment_id`) via le port `NotificationRepository` (`enqueue`) dans la **même** unité de travail
que le RDV — committée/rollbackée **avec** lui (patron `AuditLog` #20/#23). Cette ligne **est la trace**
de la notification critique exigée par **§8.4/§11.4** et **la file** que consommera le worker de remise.
Le **contrat HTTP est inchangé** (toujours `201 AppointmentResponse`) ; **aucune** route publique,
**aucune** migration (l'enum `CONFIRMATION` et la table `notifications` existent depuis la migration
`0001`).

**Canal « selon disponibilité ».** Une fonction pure `resolve_confirmation_channel(...)` choisit par
priorité **PUSH → SMS → IN_APP** (`WHATSAPP` **exclu**, V2). Au MVP, faute de **registre de jetons
d'appareil**, `PUSH` n'est jamais ciblable : le canal effectif est **SMS** (le client s'inscrit par
téléphone, #8), `IN_APP` restant le repli garanti.

**Non-remise assumée** ([ADR-0006](../docs/adr/0006-notifications-fcm-sms.md)). #45 **émet/trace** la
confirmation ; il n'**envoie** rien — `status` reste `PENDING`, `sent_at` reste `NULL`. La remise
proactive (push FCM / SMS via file Redis) relève du **worker M5+** ; le stub OTP existant n'est pas
sollicité, aucun appel réseau externe n'entre dans le chemin de requête (budget de latence §12.1).

**Non-fuite de PII** (§11.3). La ligne ne stocke **que** des identifiants **opaques** et un
`title`/`message` **templaté neutre** — **jamais** le téléphone ni le nom du client. Ni
`SqlNotificationRepository` ni `BookAppointment` ne journalisent le destinataire, le canal ou le corps
du message. Le worker de remise (futur) résoudra `user_id → users.phone` **à l'envoi** : le numéro n'est
**jamais** copié dans `notifications`.

**Périmètre strict** : #45 notifie **le client**, **à la création** uniquement, avec une **confirmation**.
Les **rappels** (US-7.2, #46) sont couverts par la section suivante. La notification au salon (US-7.3,
#47) et les notifications d'annulation/modification poussées au client (US-7.4, #48) restent **hors
périmètre** — `ModifyAppointment`/`CancelAppointment`/`SetAppointmentStatus` n'émettent **aucune**
confirmation.

| Déclencheur | Écriture `notifications` | Canal (MVP) | Statut | Remise |
| --- | --- | --- | --- | --- |
| `POST /salons/{salon_id}/appointments` réussi (`201`) | 1 ligne `CONFIRMATION` (client + salon + RDV) | `SMS` | `PENDING` | différée M5+ (aucune) |
| Réservation échouée (`404`/`409`/`422`) | **aucune** (rollback conjoint) | — | — | — |

## Notifications — rappel automatique avant RDV (US-7.2, #46 — [ADR-0034](../docs/adr/0034-rappel-automatique-avant-rdv.md))

À la **création d'un rendez-vous**, en plus de la confirmation (#45), `BookAppointment` **planifie**
jusqu'à **3 rappels** : une ligne `notifications` (`type = REMINDER`, `status = PENDING`,
`scheduled_for = début_du_RDV − offset`) par échéance **encore future** parmi `24h`/`2h`/`30min` avant
le début du RDV — une échéance déjà passée au moment de la réservation n'est **pas** planifiée (aucun
rappel « en retard » à la création). Les rappels sont écrits via le **même** port `NotificationRepository`
(`enqueue`), dans la **même** unité de travail que le RDV et la confirmation — committés/rollbackés
**ensemble**. Le canal est le **même** que la confirmation (fonction pure généralisée
`resolve_notification_channel`, PUSH → SMS → IN_APP, effectif **SMS** au MVP). **Migration `0006`**
requise : colonne `notifications.scheduled_for TIMESTAMPTZ NULL` (`NULL` = confirmation, non-`NULL` =
rappel) + statut `NotificationStatus.CANCELLED`.

**Annulation liée au cycle de vie du RDV (AC).** « L'annulation du RDV annule le rappel » : à
l'**annulation client** (`POST /appointments/{id}/cancellation`, #24) et au **refus gérant**
(`POST /salons/{salon_id}/appointments/{id}/status` `→ CANCELLED`, #25), tous les rappels `PENDING` du
RDV sont **annulés** — marqués `CANCELLED` (trace conservée, pas de suppression) via
`cancel_pending_for_appointment(appointment_id)`, dans la **même** unité de travail que le changement de
statut. Les transitions `CONFIRMED`/`COMPLETED`/`NO_SHOW` n'annulent **aucun** rappel (leur échéance est
déjà passée ; le futur worker ne remet pas un rappel en retard).

**Re-planification sur modification.** `PATCH /appointments/{id}` (#23) déplaçant le RDV **annule** les
rappels `PENDING` existants puis les **recrée** sur le nouveau créneau (même unité de travail) — évite
des rappels périmés pointant l'ancien horaire.

**Non-remise assumée** ([ADR-0006](../docs/adr/0006-notifications-fcm-sms.md)). Comme #45, #46
**planifie/annule** ; il n'**envoie** rien — `status` reste `PENDING` ou passe à `CANCELLED`, `sent_at`
reste `NULL`. L'ordonnanceur et le worker de remise (qui interrogeront les lignes `REMINDER` `PENDING`
dont `scheduled_for <= now`) relèvent du **M5+** ; aucun appel réseau externe n'entre dans le chemin de
requête (§12.1).

**Non-fuite de PII** (§11.3). Les lignes `REMINDER` ne portent que des identifiants opaques, un
`scheduled_for` (horodatage, non-PII) et un `title`/`message` templatés neutres (« Rappel de
rendez-vous » / « Vous avez un rendez-vous à venir. ») — jamais le téléphone ni le nom du client.

**Contrat HTTP inchangé** : `POST /salons/{salon_id}/appointments` (`201`),
`POST /appointments/{id}/cancellation` (`200`), `POST .../status` (`200`) et
`PATCH /appointments/{id}` (`200`) renvoient des réponses **inchangées** ; aucune route ajoutée, aucune
route de lecture des rappels, rien dans `PUBLIC_ROUTE_PATHS`.

| Déclencheur | Écriture `notifications` | Statut résultant |
| --- | --- | --- |
| Réservation réussie (`201`) | jusqu'à 3 lignes `REMINDER` (échéances futures) | `PENDING` |
| Annulation client / refus gérant (`200`) | rappels `PENDING` du RDV | `CANCELLED` |
| Modification (`PATCH`, `200`) | anciens rappels annulés + nouveaux planifiés | `CANCELLED` puis `PENDING` |
| Confirmation / terminé / absence (`CONFIRMED`/`COMPLETED`/`NO_SHOW`) | **aucune** | inchangé |

## Notifications — au salon à la réservation (US-7.3, #47 — [ADR-0035](../docs/adr/0035-notification-salon-a-la-reservation.md))

À la **création d'un rendez-vous**, en plus de la confirmation (#45) et des rappels (#46) — destinés au
**client** —, `BookAppointment` **notifie le salon** : **une** ligne `notifications`
(`type = NEW_BOOKING`, `channel = IN_APP`, `status = PENDING`, `scheduled_for = NULL`) est persistée pour
le **gérant** (`user_id = salon.owner_id`, déjà chargé — aucun accès base supplémentaire), rattachée au
`salon_id` et à l'`appointment_id`, via le **même** port `NotificationRepository` (`enqueue`), dans la
**même** unité de travail que le RDV — committée/rollbackée **avec** lui. Cette ligne **est la trace** de
la notification critique « nouvelle réservation reçue par le salon » (§8.4/§11.4) et **la file** que
consommera le futur worker pour la remise **optionnelle** email/SMS. **Une** réservation → **une**
notification salon ; une réservation échouée (`404`/`409`/`422`) n'en laisse **aucune** (rollback
conjoint). **Migration `0007`** requise : valeur d'enum `NotificationType.NEW_BOOKING` + **régénération**
du `CHECK` `ck_notifications_type` (drop + recreate incluant `NEW_BOOKING`) — patron du `CHECK` `status`
régénéré par `0006`.

**Destinataire = le gérant, pas le client.** La seule vraie différence avec la confirmation client est le
destinataire : `user_id = salon.owner_id` (imposé serveur, jamais soumis). Le `salon_id` de la ligne est
celui du chemin ; l'`appointment_id` est celui du RDV créé.

**Canal « dashboard » = `IN_APP`.** Le backlog dit « Notification **dashboard** + **option** email/SMS ».
La notification que le salon consulte est **`IN_APP`** (passée explicitement, pas « selon disponibilité »
téléphone/push). L'**option** email/SMS est une **remise proactive** qui relève — comme le push/SMS
client de #45/#46 — du **worker M5+** ([ADR-0006](../docs/adr/0006-notifications-fcm-sms.md)) : `status`
reste `PENDING`, `sent_at` reste `NULL` — rien n'est envoyé ici.

**Non-fuite de PII** (§11.3). La ligne ne stocke **que** des identifiants **opaques** (`user_id = owner`,
`salon_id`, `appointment_id`) et un `title`/`message` **templaté neutre** (« Nouvelle réservation » /
« Un nouveau rendez-vous a été réservé dans votre salon. ») — **jamais** le nom ni le téléphone du client.
Les détails du RDV (date/heure/prestation/client), que le salon a le droit de voir, sont résolus **à la
lecture** via `appointment_id`, jamais copiés dans `notifications`. Ni `SqlNotificationRepository` ni
`BookAppointment` ne journalisent le destinataire, le canal ou le corps du message.

**Périmètre strict : création uniquement.** #47 notifie le salon **à la réservation**
(`BookAppointment`). Les notifications d'**annulation/modification** (au client comme au salon) relèvent de
**#48 (US-7.4)** : `ModifyAppointment`/`CancelAppointment`/`SetAppointmentStatus` n'émettent **aucune**
`NEW_BOOKING` (une modification ne **re-notifie pas** le salon dans #47).

**Lecture « dashboard » différée.** Comme #45 (dont l'ADR-0033 a *reporté* `GET /me/notifications`), #47
livre l'**émission/trace** ; l'endpoint de **lecture salon-scopé** (`GET /salons/{salon_id}/notifications`)
qui matérialiserait l'affichage est **différé** (voir ADR-0035). **Contrat HTTP inchangé** :
`POST /salons/{salon_id}/appointments` reste `201 AppointmentResponse` ; **aucune** route ajoutée, rien
dans `PUBLIC_ROUTE_PATHS`.

| Déclencheur | Écriture `notifications` | Destinataire | Canal | Statut | Remise |
| --- | --- | --- | --- | --- | --- |
| `POST /salons/{salon_id}/appointments` réussi (`201`) | 1 ligne `NEW_BOOKING` (owner + salon + RDV) | gérant (`salon.owner_id`) | `IN_APP` | `PENDING` | option email/SMS différée M5+ (aucune) |
| Réservation échouée (`404`/`409`/`422`) | **aucune** (rollback conjoint) | — | — | — | — |
| Annulation / modification du RDV | **aucune** (périmètre #48) | — | — | — | — |

## Notifications — annulation/modification de RDV (US-7.4, #48 — [ADR-0036](../docs/adr/0036-notification-annulation-modification.md))

« Un **changement de statut** déclenche la notification aux **parties concernées** » (AC #48), et §8.4
impose qu'« une **annulation** notifie **le client et le salon** ». Après #45/#46/#47, `CancelAppointment`
(#24), `SetAppointmentStatus` (#25) et `ModifyAppointment` (#23) **annulaient/re-planifiaient les rappels**
mais ne **notifiaient personne** de l'événement. #48 ajoute l'**émission/trace** de la notification au
moment du changement, dans la **même** unité de travail que l'écriture du statut — sans construire aucune
remise réelle.

**Volet A — annulation (sans migration).** Sur **toute** transition `→ CANCELLED` (annulation client #24
**ou** refus gérant #25), **deux** lignes `notifications` `type = CANCELLATION` `status = PENDING` sont
**émises/tracées** : une au **client** (`user_id = appointment.client_id`, canal résolu « selon
disponibilité » → **SMS** au MVP) et une au **salon** (`user_id = salon.owner_id`, canal **`IN_APP`**). Le
type `CANCELLATION` existant (enum + `CHECK`, migration `0007`) suffit — **aucune migration**.

**Volet B — autres changements & modification (migration `0008`).** Les transitions gérant
`CONFIRMED`/`COMPLETED`/`NO_SHOW` notifient le **client** ; une **modification** (#23) notifie le **salon**
(`salon.owner_id`, déjà chargé) — via `type = APPOINTMENT_UPDATE`. La **migration `0008`** ajoute la valeur
d'enum et **régénère** le `CHECK` `ck_notifications_type` (drop + recreate incluant les 5 valeurs) — patron
de `0007` ; `downgrade` symétrique, round-trip vérifié en CI.

**Résolution du gérant.** `ModifyAppointment` a déjà `salon.owner_id` (chargé par `_load_bookable_salon`).
`CancelAppointment`/`SetAppointmentStatus` reçoivent une dépendance **optionnelle** `SalonRepository`
(défaut `None`) et résolvent `owner_id` via `find_by_id(salon_id)` — un `get` par clé primaire
**indépendant du statut** (une annulation reste possible sur un salon inactif §8.3). Le câblage HTTP
(`get_salon_repository`, **même** `Session`) l'injecte toujours ; en son absence (ou si `find_by_id`
renvoie `None`, théoriquement impossible), l'annulation **n'échoue pas** et seule la notification salon est
omise.

**Atomicité, non-remise, non-fuite.** L'émission passe par le port `enqueue` sur la **même** `Session` que
l'écriture du statut : un changement échoué (verrou terminal, TOCTOU, RDV d'autrui) ne laisse **aucune**
notification. Comme #45/#46/#47, rien n'est **envoyé** (`status = PENDING`, `sent_at = NULL`, remise
différée M5+, ADR-0006) ; les lignes sont **neutres** (identifiants opaques + `title`/`message` templatés,
**jamais** le nom/téléphone d'une partie ni le **motif** d'annulation). `AssignHairdresser` n'émet **rien**
(pas un changement de statut). **Contrats HTTP inchangés** (`cancel`/`status`/`modify` → `200`) ; **aucune**
route ajoutée, rien dans `PUBLIC_ROUTE_PATHS`. La **lecture** (`GET /me/notifications`,
`GET /salons/{salon_id}/notifications`) reste différée (parité #45/#47).

| Déclencheur | Écriture `notifications` | Destinataire(s) | Canal | Statut | Remise |
| --- | --- | --- | --- | --- | --- |
| `POST /appointments/{id}/cancellation` réussi (annulation client) | 2 lignes `CANCELLATION` | client + gérant (`salon.owner_id`) | SMS (client) / `IN_APP` (salon) | `PENDING` | différée M5+ (aucune) |
| `POST /salons/{id}/appointments/{id}/status` `→ CANCELLED` (refus gérant) | 2 lignes `CANCELLATION` | client + gérant | SMS / `IN_APP` | `PENDING` | différée M5+ (aucune) |
| `POST /salons/{id}/appointments/{id}/status` `CONFIRMED`/`COMPLETED`/`NO_SHOW` | 1 ligne `APPOINTMENT_UPDATE` | client | SMS | `PENDING` | différée M5+ (aucune) |
| `PATCH /appointments/{id}` réussi (modification) | 1 ligne `APPOINTMENT_UPDATE` | gérant (`salon.owner_id`) | `IN_APP` | `PENDING` | différée M5+ (aucune) |
| Changement de statut échoué (`404`/`409`/`422`) | **aucune** (rollback conjoint) | — | — | — | — |
| (Dés)assignation d'un coiffeur | **aucune** (hors périmètre) | — | — | — | — |

## Campagnes/messages aux clients (US-7.5, #49 — [ADR-0037](../docs/adr/0037-campagnes-messages-clients.md))

Le gérant compose un message (**rappel**, **promotion** ou **fermeture exceptionnelle**) et le diffuse à
un **segment** de son fichier clients (#28) : `POST /salons/{salon_id}/campaigns` (`CUSTOMER_MANAGE` +
`require_salon_scope`, **MANAGER** seul — matrice RBAC inchangée). La campagne est **émise/tracée** dans
une table dédiée `campaigns` (migration `0009`, `down_revision = 0008`), dans la **même** unité de
travail que l'entrée d'audit `CAMPAIGN_CREATED` (§11.4) — la **remise proactive** (fan-out SMS) reste
**différée M5+** (ADR-0006) : rien n'est envoyé, `status = PENDING`, `sent_at = NULL`.

**Table dédiée, pas une ligne par destinataire.** Contrairement à `notifications` (#45–#48, rattachées à
un RDV et un destinataire unique), une campagne est **un-à-plusieurs** avec un **texte libre** composé par
le gérant. Matérialiser une ligne par fiche à la création serait volumineux (§12.1) et figerait un
snapshot de PII (téléphones). `campaigns` porte donc un **effectif** (`recipient_count`, entier
non-PII) — le fan-out réel (résolution `segment → customer_profiles.phone`) est **différé** au worker
M5+, qui re-résout le segment à l'envoi.

**Segment = prédicat salon-scopé sur les fiches (#28).** `segment` (`ALL`/`FEMALE`/`MALE`/`OTHER`) se
traduit en `CustomerFilter` (`domain/campaign.py::segment_to_customer_filter`) : `ALL` cible toutes les
fiches **joignables** du salon, `FEMALE`/`MALE`/`OTHER` y ajoutent un filtre de genre exact. **Toutes**
les traductions imposent `has_phone=True` : le canal effectif au MVP est **SMS**
(`customer_profiles.phone`), donc une fiche walk-in **sans** numéro ne peut recevoir de campagne — elle
n'entre **jamais** dans `recipient_count`, même si son genre correspond au segment ciblé.

**Effectif = un seul `COUNT`, jamais un fan-out.** `CreateCampaign` résout `recipient_count` via **un**
`COUNT` salon-scopé (`CustomerRepository.count_for_salon`) sur le segment traduit — aucune liste de
fiches n'est matérialisée ni journalisée. Un segment sans fiche joignable donne un effectif `0` : la
campagne est quand même créée (l'émission n'est pas conditionnée à un effectif non nul).

**Permission : `CUSTOMER_MANAGE` réutilisée.** Le gérant qui gère déjà son fichier clients (#28) peut
créer une campagne — aucune modification de `ROLE_PERMISSIONS` (§4.1). `CLIENT`/`HAIRDRESSER`/`ADMIN`
ainsi qu'un gérant hors portée du salon reçoivent un `403` générique (ADR-0015).

**Non-fuite de PII (§11.3, ADR-0006).** Aucune colonne de `campaigns` ni entrée d'audit ne porte un
téléphone, un nom ou une identité de destinataire. Le `metadata` de `CAMPAIGN_CREATED` ne porte que
`type`/`segment`/`recipient_count` — **jamais** le titre ni le corps du message composé par le gérant
(contenu métier, diffusé à l'identique à tout le segment, mais non journalisé). La lecture
(`GET /salons/{salon_id}/campaigns`, paginée) projette un résumé **sans** le corps du message
(`CampaignSummaryResponse`) — celui-ci n'est renvoyé qu'à la création (`POST`).

**Atomicité, non-remise.** La persistance de la campagne (`flush`, `status = PENDING`) et l'audit
`CAMPAIGN_CREATED` partagent la **même** `Session` (`get_session`) : une validation domaine échouée
(titre/message/type/segment invalide, `422`) ne persiste **ni** campagne **ni** audit. Comme #45–#48,
`sent_at` reste `NULL` tant qu'aucun worker de remise n'existe (M5+, ADR-0006) ; l'**opt-out marketing**
par client reste un pré-requis à durcir avant toute remise réelle (#52).

| Déclencheur | Écriture `campaigns` | Effectif | Statut | Remise |
| --- | --- | --- | --- | --- |
| `POST /salons/{salon_id}/campaigns` réussi (`201`) | 1 ligne (`type`/`segment`/`title`/`message` du gérant) | `COUNT` salon-scopé, fiches joignables du segment | `PENDING` | différée M5+ (aucune) |
| Payload invalide (`type`/`segment`/`title`/`message`, `422`) | **aucune** (rollback conjoint) | — | — | — |
| `GET /salons/{salon_id}/campaigns` | lecture seule, paginée, **sans** le corps du message | — | — | — |

## Configuration

La configuration est lue **depuis l'environnement** (jamais en dur). Voir `.env.example` ;
les **secrets réels** (DSN base/Redis, `JWT_SECRET`, etc.) sont injectés **hors dépôt** et ne doivent
**jamais** être committés. Modèle d'environnements, matrice de configuration et politique de secrets :
**[docs/environnements-et-secrets.md](../docs/environnements-et-secrets.md)** (ADR-0011).

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `OTP_ENABLED` | `false` | Active l'OTP à l'inscription (#8). Envoi réel différé à M5 ; capacité testable même désactivée. |
| `OTP_CODE_LENGTH` | `6` | Longueur du code OTP (optionnel). |
| `OTP_TTL_SECONDS` | `300` | Durée de validité de l'OTP en secondes (optionnel). |
| `OTP_MAX_ATTEMPTS` | `3` | Nombre d'essais autorisés par OTP (optionnel). |
| `JWT_SECRET` | *(vide)* | **SECRET** — requis pour la connexion (#10) : signe les JWT (HS256). Absent → `/auth/login` et `/auth/refresh` répondent `503`. Vit hors dépôt (ADR-0011). |
| `JWT_ALGORITHM` | `HS256` | Algorithme de signature JWT (#10, ADR-0013). |
| `JWT_ACCESS_TTL_SECONDS` | `900` | Durée du jeton d'accès (court) en secondes. |
| `JWT_REFRESH_TTL_SECONDS` | `2592000` | Durée du refresh (long, rotaté) en secondes (30 j). |
| `LOGIN_MAX_ATTEMPTS` | `5` | Anti-bruteforce : nombre d'échecs avant verrou (#10). |
| `LOGIN_WINDOW_SECONDS` | `300` | Anti-bruteforce : fenêtre glissante des échecs, en secondes. |
| `LOGIN_LOCKOUT_SECONDS` | `900` | Anti-bruteforce : durée du verrou après seuil, en secondes. |
| `PASSWORD_RESET_OTP_TTL_SECONDS` | *(= `OTP_TTL_SECONDS`)* | Réinitialisation (#11, optionnel) : durée de validité de l'OTP de reset. Défaut = valeur OTP d'inscription. |
| `PASSWORD_RESET_OTP_MAX_ATTEMPTS` | *(= `OTP_MAX_ATTEMPTS`)* | Réinitialisation (#11, optionnel) : essais autorisés par OTP de reset. |
| `PASSWORD_RESET_MAX_ATTEMPTS` | *(= `LOGIN_MAX_ATTEMPTS`)* | Réinitialisation (#11, optionnel) : demandes avant verrou anti-flood. |
| `PASSWORD_RESET_WINDOW_SECONDS` | *(= `LOGIN_WINDOW_SECONDS`)* | Réinitialisation (#11, optionnel) : fenêtre glissante de l'anti-flood, en secondes. |
| `PASSWORD_RESET_LOCKOUT_SECONDS` | *(= `LOGIN_LOCKOUT_SECONDS`)* | Réinitialisation (#11, optionnel) : durée du verrou anti-flood, en secondes. |
| `TERMINAL_LOOKUP_MAX_ATTEMPTS` | `10` | Borne — anti-énumération lookup (#156, optionnel) : échecs par device + IP avant verrou. Plus permissif que `LOGIN_*` (saisie tactile fréquente, terminal physiquement surveillable). |
| `TERMINAL_LOOKUP_WINDOW_SECONDS` | `300` | Borne — anti-énumération lookup (#156, optionnel) : fenêtre glissante des échecs, en secondes (5 min). |
| `TERMINAL_LOOKUP_LOCKOUT_SECONDS` | `600` | Borne — anti-énumération lookup (#156, optionnel) : durée du verrou après seuil, en secondes (10 min). Distinct de `LOGIN_LOCKOUT_SECONDS` (verrouiller les recherches ne verrouille ni le login ni la connexion humaine). |
| `S3_ENDPOINT_URL` | *(vide)* | Stockage objet médias (#15, ADR-0005) : endpoint S3-compatible (MinIO en local, fournisseur en prod). Vide ⇒ AWS S3 « pur ». |
| `S3_BUCKET` | *(vide)* | Bucket **privé** des médias. Absent ⇒ `media_storage=None` ⇒ routes médias en `503`. |
| `S3_REGION` | `us-east-1` | Région du bucket. |
| `S3_ACCESS_KEY_ID` | *(vide)* | **SECRET** — clé d'accès S3. Hors dépôt (ADR-0005/0011). |
| `S3_SECRET_ACCESS_KEY` | *(vide)* | **SECRET** — clé secrète S3. Hors dépôt. |
| `MEDIA_URL_TTL_SECONDS` | `900` | Durée de vie des URLs signées (lecture/téléversement). |
| `MEDIA_MAX_UPLOAD_BYTES` | `5242880` | Taille max d'un média (5 Mio). |
| `MEDIA_MAX_PHOTOS` | `10` | Nombre max de photos par salon (`409` au-delà). |

> **Médias en local** : un service **MinIO** est fourni dans `deploy/docker-compose.yml` (identifiants
> de **développement** dans `deploy/.env`, jamais un secret réel). Le téléversement direct
> navigateur→bucket exige que le bucket autorise l'origine du dashboard (**CORS**) — configuration
> d'infrastructure, hors code.

> La réinitialisation par OTP (#11) **ne dépend pas** d'`OTP_ENABLED` (OTP de reset **toujours actif**)
> ni de `JWT_SECRET`. La longueur du code de reset réutilise `OTP_CODE_LENGTH`. Les variables
> `PASSWORD_RESET_*` sont **optionnelles** : absentes, elles retombent sur les valeurs OTP (#8) et
> login (#10).

## Modèle de données & migrations

Le schéma relationnel initial (issue #3) matérialise les **8 entités du PRD §9** plus une
table de jonction, avec leurs contraintes d'intégrité critiques. L'outillage est figé par
**[ADR-0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md)** : **SQLAlchemy 2.0**
(ORM, style typé `Mapped[...]`) · **Alembic** (migrations versionnées) · **psycopg 3**
(driver) · **PostgreSQL 16**.

Conformément à l'hexagonal (ADR-0008), tables ORM, `metadata` et migrations sont un **détail
de persistance** et vivent dans `adapters/outbound/` ; seules les **énumérations métier** sont
des `enum.Enum` purs du `domain/`. Aucun import de SQLAlchemy depuis `domain/` ou
`application/`.

```
coiflink_api/
  domain/enums.py                          # enums purs (Role, AppointmentStatus, ...) — source des CHECK
  adapters/outbound/persistence/
    base.py                                 # DeclarativeBase + metadata + convention de nommage
    models.py                              # tables ORM (source de vérité du schéma)
    session.py                              # fabrique d'engine (lit DATABASE_URL ; non câblée à l'app en #3)
migrations/
  env.py                                    # importe la metadata ; lit DATABASE_URL (jamais de secret)
  versions/0001_schema_initial.py           # migration initiale up/down
alembic.ini                                 # config Alembic (DSN via env, aucun secret)
```

### Prérequis & connexion

- **PostgreSQL 16** accessible.
- `DATABASE_URL` défini dans l'environnement (cf. `.env.example`). Il pilote l'application
  **et** Alembic. La forme `postgresql://…` est automatiquement normalisée en
  `postgresql+psycopg://…` (driver psycopg 3) ; `alembic.ini` ne contient **aucun**
  identifiant.

### Commandes de migration

Exécutées depuis `backend/` (avec l'environnement virtuel activé et `DATABASE_URL` défini) :

| Commande | Effet |
| --- | --- |
| `alembic upgrade head` | Applique toutes les migrations (crée le schéma). |
| `alembic downgrade base` | Réverte tout (revient à un schéma vide). |
| `alembic current` | Affiche la révision appliquée. |
| `alembic history` | Liste l'historique des révisions. |
| `alembic check` | Vérifie que la `metadata` ORM correspond à la base (aucun diff attendu). |
| `alembic revision --autogenerate -m "…"` | Génère une nouvelle migration (à **relire** : les `CHECK`/`EXCLUDE` ne sont pas tous autogénérés). |

Le round-trip `upgrade head` → `downgrade base` → `upgrade head` est **réversible et
idempotent**.

### Diagramme relationnel (ERD)

```mermaid
erDiagram
    users ||--o{ salons : "owner_id"
    users ||--o{ appointments : "client_id"
    users |o--o{ appointments : "hairdresser_id"
    users |o--o{ customer_profiles : "user_id"
    users ||--o{ payments : "recorded_by"
    users ||--o{ salon_members : "user_id"
    salons ||--o{ services : ""
    salons ||--o{ appointments : ""
    salons ||--o{ customer_profiles : ""
    salons ||--o{ payments : ""
    salons ||--o{ cash_journal : ""
    salons ||--o{ salon_members : "salon_id"
    salons ||--o{ salon_photos : "salon_id"
    appointments ||--o{ appointment_services : ""
    services ||--o{ appointment_services : ""
    appointments |o--o{ payments : "appointment_id"
    services |o--o{ payments : "service_id"
    payments |o--o{ cash_journal : "transaction_id"
    users |o--o{ notifications : "user_id"
    salons |o--o{ notifications : "salon_id"
    appointments |o--o{ notifications : "appointment_id"
```

### Dictionnaire des tables

> Toutes les tables portent `id UUID PK DEFAULT gen_random_uuid()` et `created_at timestamptz`.
> Celles qui sont mutables portent aussi `updated_at timestamptz`. Montants en `NUMERIC(12,2)`
> (devise XOF). Suppression par défaut `ON DELETE RESTRICT`.

| Table | Colonnes notables | Contraintes & index clés |
| --- | --- | --- |
| **`users`** | `full_name`, `phone`, `email?`, `password_hash`, `role`, `status` | `uq_users_phone` ; `uq_users_email` (unique partiel `WHERE email IS NOT NULL`) ; CHECK `role`/`status` |
| **`salons`** | `owner_id→users`, `name`, `description`, `phone`, `address`, `city`, `commune`, `latitude`, `longitude`, `logo_object_key`, `status`, `opening_hours JSONB` | FK `owner_id` ; CHECK `status` ; index `(city, commune)`, `status`, `owner_id` (`ix_salons_owner_id`, ajouté en `0003`) |
| **`salon_photos`** | `salon_id→salons`, `object_key` (clé S3, jamais une URL), `position` | FK `salon_id` CASCADE ; `uq_salon_photos_salon_id (salon_id, id)` ; `uq_salon_photos_salon_object_key (salon_id, object_key)` ; CHECK `position >= 0` ; index `(salon_id, position)` |
| **`salon_members`** | `salon_id→salons`, `user_id→users`, `role`, `status` | `uq_salon_members_salon_user (salon_id, user_id)` (un compte est employé une seule fois par salon) ; `uq_salon_members_salon_id (salon_id, id)` ; FK `salon_id`/`user_id` RESTRICT ; CHECK `role`/`status` ; index `user_id`, `salon_id` — **source d'autorité** de la portée d'un `HAIRDRESSER` (#13, ADR-0016) |
| **`services`** | `salon_id→salons`, `name`, `price`, `duration_minutes`, `category`, `is_active` | FK `salon_id` ; `uq_services_salon_id (salon_id, id)` ; CHECK `price >= 0`, `duration_minutes > 0` ; index `salon_id` |
| **`appointments`** | `salon_id→salons`, `client_id→users`, `hairdresser_id?→users`, `appointment_date`, `start_time`, `end_time`, `status`, `cancellation_reason?`, `client_note?`, `slot` (généré) | FK `salon_id`/`client_id` NOT NULL (§8.1) ; `uq_appointments_salon_id (salon_id, id)` ; CHECK `end_time > start_time`, `status` ; **EXCLUDE** anti double-booking ; index `(salon_id, appointment_date)`, `client_id` |
| **`appointment_services`** *(jonction)* | `appointment_id→appointments`, `service_id→services`, `salon_id`, `price_at_booking` | PK `(appointment_id, service_id)` ; **FK composites** `(salon_id, appointment_id)` et `(salon_id, service_id)` (cohérence salon) ; `ON DELETE CASCADE` depuis le RDV ; CHECK `price >= 0` |
| **`customer_profiles`** | `salon_id→salons`, `user_id?→users`, `full_name`, `phone?`, `gender?`, `notes?`, `last_visit_at?`, `total_visits` | FK `salon_id`/`user_id` ; `uq_customer_profiles_salon_user (salon_id, user_id) WHERE user_id IS NOT NULL` ; **`uq_customer_profiles_salon_phone (salon_id, phone) WHERE phone IS NOT NULL`** (#28) ; CHECK `total_visits >= 0`, `gender` ; index `salon_id` |
| **`payments`** | `salon_id→salons`, `appointment_id?`, `service_id?`, `client_id?→users`, `amount`, `currency`, `payment_method`, `status`, `recorded_by→users`, `reference?` | FK `salon_id`/`recorded_by` NOT NULL (§8.2) ; FK composites vers RDV/prestation ; **CHECK `appointment_id IS NOT NULL OR service_id IS NOT NULL`** (§8.2) ; CHECK `amount >= 0`, `payment_method`, `status` ; index `(salon_id, created_at)`, `appointment_id` |
| **`cash_journal`** *(append-only)* | `salon_id→salons`, `transaction_id?→payments`, `operation_type`, `amount`, `performed_by→users`, `description?` | FK `salon_id`/`performed_by` NOT NULL ; `created_at` horodaté (§8.2) ; CHECK `operation_type` ; index `(salon_id, created_at)` |
| **`notifications`** | `user_id?→users`, `salon_id?→salons`, `appointment_id?→appointments`, `type`, `channel`, `title`, `message`, `status` (dont `CANCELLED`, #46), `sent_at?`, `scheduled_for?` (rappel, #46) | CHECK `type`/`channel`/`status` ; index `user_id`, `(salon_id, created_at)`, partiel `(scheduled_for) WHERE status='PENDING'` |

### Contraintes clés métier

- **RDV → salon + ≥ 1 prestation (§8.1)** : `salon_id` NOT NULL ; la cardinalité « ≥ 1 »
  passe par la jonction `appointment_services`, garantie par insertion transactionnelle côté
  application (M3). Les **FK composites** `(salon_id, …)` interdisent de mêler des entités de
  salons différents (isolation §11.2).
- **Paiement → prestation ou RDV (§8.2)** : `CHECK (appointment_id IS NOT NULL OR service_id IS
  NOT NULL)`.
- **Anti double-réservation (§8.1)** : colonne générée `slot tsrange` (Abidjan = UTC+0) +
  `EXCLUDE USING gist (hairdresser_id WITH =, slot WITH &&)` restreinte aux RDV actifs
  (`PENDING`/`CONFIRMED`) assignés — requiert l'extension `btree_gist`.
- **Journal de caisse (§8.2)** : horodaté et conçu **append-only** (pas de `DELETE`/`UPDATE` ;
  correction = nouvelle ligne `ADJUSTMENT`/`REFUND`).
- **Pas de hard-delete d'un paiement validé (§8.2)** : `ON DELETE RESTRICT` + statut
  `CANCELLED`/`ADJUSTED`.

### Sécurité & données personnelles

`DATABASE_URL` et tout identifiant sont lus **depuis l'environnement** ; aucune valeur réelle
n'est committée (seul `.env.example`). Les colonnes PII (`users`, `customer_profiles`) et le
`password_hash` (jamais de mot de passe en clair) ne doivent **jamais** être journalisés —
les logs Alembic ne dumpent pas de données.

### Tests

Les invariants de schéma (sans base) et le round-trip de migration (PostgreSQL requis,
**skip si aucun `DATABASE_URL`**) sont couverts par la suite de tests. Issue #5 ajoute
`test_session.py` (fail-fast sur `DATABASE_URL`, normalisation du DSN — aucune infra requise)
et `test_secrets_policy.py` (vérifications statiques sur `.gitignore`, `.env.example`,
`docker-compose.yml`, configs Railway et Dockerfiles). La CI (#4) et les environnements &
secrets (#5) sont désormais en place.

Issue #8 complète la suite avec des **tests unitaires** (logique de domaine : téléphone,
mot de passe, OTP, hacheur argon2id), des **tests API** (`TestClient`, sans base réelle :
`201`, `409` doublon, `422` validation, non-fuite du mot de passe/OTP dans la réponse) et un
test de configuration. Les tests d'**intégration Postgres** (persistance réelle +
contrainte `uq_users_phone`) sont inclus et **skippés proprement si `DATABASE_URL` est absent**.

Issue #9 ajoute trois suites dédiées à l'inscription gérant :

- `test_manager_registration_usecase.py` — rôle `MANAGER` attribué côté serveur, statut
  `ACTIVE`, normalisation E.164, mot de passe jamais persisté en clair, doublon (pré-check +
  fallback `IntegrityError`), validations domaine, OTP off/on, rôle inconnu → `ValueError`,
  non-régression #8 (`RegisterClient` reste `CLIENT`).
- `test_manager_auth_api.py` — `201` + `role=="MANAGER"`, non-fuite du secret, `409` doublon
  (format local et E.164, détail sans le numéro), `422` validation et bornes, anti-escalade
  (champ `role` dans le corps ignoré), `405` sur `GET`.
- `test_manager_registration_integration.py` (PostgreSQL, **skip propre sans `DATABASE_URL`**) —
  persistance `role=MANAGER`/`status=ACTIVE`, `password_hash` ≠ clair dans la table,
  contrainte `uq_users_phone` (dont doublon cross-rôle `CLIENT→MANAGER`), fallback
  `IntegrityError` concurrente → `PhoneAlreadyInUse`.

Issue #10 ajoute six suites dédiées à la connexion JWT et à l'anti-bruteforce :

- `test_identifier.py` — classement de l'identifiant : `@` → e-mail (normalisé) ; sinon téléphone
  normalisé en E.164 (`0700…` et `+2250700…` → même clé) ; rejet des entrées vides/malformées.
- `test_jwt_token_service.py` — `JwtTokenService` : `issue_pair` produit access + refresh avec
  claims corrects (`sub`, `role`, `type`, `jti`, `exp` cohérent avec le TTL) ; `decode` accepte un
  jeton valide et rejette signature invalide / jeton expiré (horloge injectée) / `alg` inattendu /
  mauvais `type` pour `verify_refresh`. Non-émission d'un jeton si `JWT_SECRET` vide.
- `test_login_rate_limiter.py` — `InMemoryLoginRateLimiter` (horloge injectée) : sous le seuil →
  passe ; au seuil → `TooManyLoginAttempts` ; expiration de la fenêtre → de nouveau autorisé ;
  `reset` au succès ré-autorise immédiatement.
- `test_authentication_usecase.py` — `AuthenticateUser` et `RefreshTokens` (ports 100 % fakes) :
  succès par téléphone et par e-mail → `TokenPair` + compteur reset ; mauvais mot de passe →
  `InvalidCredentials` + `record_failure` ; utilisateur introuvable → `InvalidCredentials` +
  vérification **factice** appelée (anti-oracle temporel) ; compte non `ACTIVE` → `InvalidCredentials` ;
  verrou actif → `TooManyLoginAttempts` avant tout accès base. `RefreshTokens` : refresh valide →
  nouvelle paire (rotation) ; refresh expiré/altéré/`type=access` → `InvalidToken`/`ExpiredToken` ;
  compte devenu non `ACTIVE` → refus.
- `test_login_api.py` — adapter entrant (FastAPI `TestClient`, ports fakes, sans base) :
  `POST /auth/login` → `200` + structure `{access_token, refresh_token, token_type, expires_in}` ;
  `401` **générique et indistinguable** (inconnu vs mot de passe faux vs compte inactif) ; `429` +
  `Retry-After` ; `422` champ manquant/vide ; `503` sans `TokenService` câblé ; non-fuite du mot de
  passe dans les réponses. `POST /auth/refresh` → `200` + structure ; `401` sur refresh invalide ou
  expiré ; `422` champ manquant ; `405` sur mauvaise méthode.
- `test_login_e2e.py` — deux groupes : (a) **`TestLoginFullStackE2E`** (PostgreSQL requis, **skip
  propre sans `DATABASE_URL`**) : pile complète sans mock (HTTP → cas d'usage → SQL + argon2 + JWT
  réel) — inscription→login par téléphone et par e-mail, vérification des claims du JWT d'accès
  (`sub=user_id`, `role`, `type=access`, **absence de PII**), rotation du refresh, accumulation du
  rate-limiter jusqu'au `429` + `Retry-After`, reset du compteur après succès ; (b)
  **`TestRateLimitAccumulationE2E`** (sans base) : N requêtes HTTP consécutives avec
  `InMemoryLoginRateLimiter` réel capturé en closure — déclenchement du `429` au seuil, présence et
  valeur positive de `Retry-After`, message `429` sans l'identifiant ciblé.

Issue #11 ajoute trois suites dédiées à la réinitialisation par OTP :

- `test_password_reset_usecase.py` — `RequestPasswordReset` et `ConfirmPasswordReset` (ports
  100 % fakes) : succès par téléphone et par e-mail — OTP stocké + envoyé, canal SMS/EMAIL correct ;
  anti-énumération (compte inconnu/inactif/suspendu, identifiant vide/invalide → silencieux, aucun
  envoi) ; rate-limit déclenché avant tout accès base (`TooManyLoginAttempts`, `retry_after`
  propagé) ; `record_failure` systématique (succès **et** échecs, mais pas si verrou) ; confirmation
  — `update_password` appelé + condensat remplacé + ancien mot de passe invalidé + défi supprimé ;
  OTP invalide/expiré/épuisé/déjà consommé/absent → `InvalidOtp` ; mot de passe trop court
  (`InvalidPassword`) vérifié **avant** l'OTP ; indistinguabilité (même `InvalidOtp` pour toutes les
  causes d'échec, code jamais dans le message).
- `test_password_reset_api.py` — adapter entrant (`TestClient`, ports fakes, sans base) :
  `POST /auth/password/reset/request` → `202` générique pour compte actif **et** inconnu (même
  corps, OTP absent de la réponse) ; `429` + `Retry-After` (message générique) ; `422` sur champs
  manquants/vides ; `405` sur mauvaise méthode. `POST /auth/password/reset/confirm` → `200` +
  message générique (`Mot de passe réinitialisé.`) ; `400` **unique** pour OTP faux / absent /
  expiré (indistinguabilité, code OTP jamais dans la réponse) ; `422` sur mot de passe trop court
  (distinct du `400` OTP) ; `422` sur champs manquants ; `405` sur mauvaise méthode.
- `test_password_reset_e2e.py` — trois groupes : (a) **`TestPasswordResetOtpFlowE2E`** (sans
  base) : deux appels HTTP consécutifs partagent un `InMemoryOtpRepository` réel — le code émis par
  `/request` est relu et accepté par `/confirm` (`200`), condensat mis à jour, ancien mot de passe
  invalidé dans le dépôt, OTP à usage unique (second `/confirm` → `400` générique), deuxième
  demande écrase le premier défi ; (b) **`TestPasswordResetRateLimitE2E`** (sans base) : N appels
  HTTP accumulent l'état d'un `InMemoryLoginRateLimiter` dédié réel — `429` au seuil + `Retry-After`
  positif, message générique sans l'identifiant ciblé ; (c) **`TestPasswordResetFullStackE2E`**
  (PostgreSQL requis, **skip propre sans `DATABASE_URL`**) : pile complète sans mock applicatif (SQL
  + argon2 + `InMemoryOtpRepository`) — inscription → reset OTP → connexion (`POST /auth/login`) :
  ancien mot de passe → `401`, nouveau → `200` + paire JWT ; OTP à usage unique sur pile réelle.

Issue #12 ajoute six suites dédiées au RBAC et à l'autorisation :

- `test_domain_permissions.py` — matrice du PRD §4.1 : chaque rôle a **exactement** ses permissions
  attendues (listes exhaustives) ; rôle inconnu/forgé (`"SUPERADMIN"`, casse incorrecte) →
  `frozenset()` (deny-by-default jusque dans le domaine) ; `ADMIN` n'est **pas** un joker —
  `PAYMENT_RECORD`, `SERVICE_MANAGE`, `EMPLOYEE_MANAGE` absent de ses droits ; `STATS_READ_PLATFORM`
  et `USER_MANAGE` **réservées** à `ADMIN`.
- `test_domain_principal.py` — `Principal` (domaine pur, sans I/O) : `is_active` par statut ;
  `has_permission` : compte actif avec/sans la permission, **compte inactif bloqué** ; `has_role` :
  rôle correct, incorrect, inactif bloqué ; cohérence `permissions` ↔ `permissions_for()` ; invariant
  PII : aucun champ personnel dans la structure.
- `test_domain_access.py` — règles de portée (§11.2, fonctions pures) : `SalonScope` constructeurs
  et `covers()` ; `can_access_salon` : `ADMIN` toujours ✅, `MANAGER`/`HAIRDRESSER` dans leur
  portée ✅ / hors portée ❌ / inter-salons ❌, `CLIENT` toujours ❌, compte inactif bloqué ;
  `can_access_appointment` : `CLIENT` sur **son** RDV ✅ / sur celui d'autrui ❌ ; `HAIRDRESSER`
  sur RDV **assigné** ✅ / non assigné ❌ ; `MANAGER` sur RDV de son salon ✅ / autre salon ❌.
- `test_authorization_policy.py` — `AccessPolicy` (avec `FakeSalonScopeRepository`) :
  `require_roles` : rôle correct, incorrect, l'un parmi plusieurs, **compte inactif refusé même avec
  le bon rôle** ; `require_permission` : accordée, refusée, `ADMIN` refusé pour un droit
  d'exploitation salon ; `scope_of` : `ADMIN` → portée plateforme **sans appeler le dépôt**, compte
  inactif → portée vide (deny-by-default), gérant/coiffeur → portée du dépôt ; `require_salon` :
  salon dans la portée autorisé, salon hors portée → `PermissionDenied` (message **générique**),
  `CLIENT` toujours refusé, `ADMIN` toujours autorisé, gérant inactif refusé.
- `test_security_guards.py` — gardes HTTP (`TestClient`, sans base) : invariant deny-by-default
  (`unprotected_routes(app)` doit être vide) ; `require_authenticated` : `401` (aucun en-tête,
  schéma non-Bearer, jeton illisible, jeton expiré, **refresh présenté comme accès**, compte
  introuvable) — **même message** dans tous les cas, présence de `WWW-Authenticate: Bearer` ;
  `get_current_principal` : `401` compte introuvable, `403` compte `SUSPENDED`/`INACTIVE` ; gardes
  `require_roles`/`require_permission` : `403` rôle/permission insuffisants ; `require_salon_scope` :
  `403` hors portée, `200` dans la portée ; `503` si `app.state.token_service = None`.
- `test_rbac_e2e.py` — **`TestRbacFullStackE2E`** (PostgreSQL requis, **skip propre sans
  `DATABASE_URL`**) : pile complète (HTTP → gardes → dépôt SQL réel + JWT réel) — (1) inscription
  gérant → connexion → `GET /auth/me` → `200`, `role=MANAGER`, **aucun** secret dans le corps ; (2)
  **isolation inter-salons** : jeton du gérant A sur le salon du gérant B → `403`, corps sans donnée
  de B (`SqlSalonScopeRepository` réel) ; (3) jeton altéré → `401` générique ; (4) **refresh token**
  présenté comme jeton d'accès → `401` (même message) ; (5) compte passé à `SUSPENDED` **après**
  émission du jeton → requête suivante → `403` (preuve que la relecture en base prime sur le claim).

Issue #13 ajoute deux suites dédiées à la création d'employés :

- `test_create_employee_usecase.py` — `CreateEmployee` (ports 100 % fakes) : succès
  (`role=HAIRDRESSER`, `status=ACTIVE`, téléphone normalisé E.164, e-mail optionnel) ; **rôle fixé
  côté serveur** (`CreateEmployeeCommand` sans champ `role`, rôle inconnu → `ValueError` à la
  construction) ; mot de passe jamais persisté en clair (le dépôt reçoit le condensat) ;
  **appartenance au salon** (`add_member` appelé une fois, `salon_id` correct, `role=HAIRDRESSER`,
  `status=ACTIVE`) ; doublon de téléphone → `PhoneAlreadyInUse` (pré-check et fallback race
  condition via `IntegrityError`) + aucun `add_member` tenté + message **sans PII** (téléphone
  absent du message d'erreur) ; appartenance déjà existante → `EmployeeAlreadyInSalon` ;
  validations de domaine (nom vide, téléphone invalide, mot de passe trop court) → erreur avant
  appel du dépôt ; entité retournée sans attribut `password` ni `password_hash`.
- `test_employee_api.py` — adapter entrant (FastAPI `TestClient`, ports fakes, sans base) :
  `POST /salons/{salon_id}/employees` → `201` + `role="HAIRDRESSER"` + non-fuite du secret ; `409`
  sur doublon téléphone, doublon e-mail et appartenance déjà existante ; `422` sur validation
  Pydantic et domaine ; `401` sans jeton ; `403` rôle non autorisé (`HAIRDRESSER`, `CLIENT` —
  permission `EMPLOYEE_MANAGE` absente) ; `403` inter-salon (salon hors portée §11.2, **message
  générique identique**) ; anti-élévation : aucun champ `role` déclaré dans le corps de la requête ;
  route absente de `PUBLIC_ROUTE_PATHS` (deny-by-default garanti).

Issue #15 ajoute quatre suites dédiées à la création de salon et aux médias :

- `test_domain_salon.py` — domaine pur (aucune I/O) : `validate_salon_name` (vide, espaces, > 255
  chars → `InvalidSalonName`, `strip()` appliqué, limite exacte acceptée) ; `validate_coordinates`
  (une seule coordonnée → `InvalidLocation`, hors bornes WGS-84, paire `(None, None)` acceptée) ;
  `validate_content_type` (MIME valides → extension canonique, MIME invalide → `InvalidMediaType`) ;
  table de vérité complète de `is_bookable` (§8.3 — cœur du critère d'acceptation de #15) ;
  propriété `Salon.is_bookable` (délègue à la même règle).
- `test_create_salon_usecase.py` — cas d'usage (ports 100 % fakes) : `CreateSalon` : `owner_id`
  imposé par l'appelant (anti-élévation), `status=ACTIVE` et `opening_hours=None` garantis,
  téléphone normalisé E.164, validations nom/coordonnées **avant** toute écriture au dépôt ;
  `_ensure_key_prefix` / `_build_object_key` via les cas d'usage médias — clé hors préfixe du salon
  → `MediaKeyMismatch` ; `AddSalonPhoto` : limite `max_photos` → `PhotoLimitExceeded` ;
  `AttachSalonLogo` : revalide le préfixe, nettoie l'ancien objet (best-effort) ;
  `RemoveSalonPhoto` : suppression best-effort du stockage ; `IssueMediaUploadUrl` : clé sans PII,
  `content_type` invalide → `InvalidMediaType` ; `GetSalon` : `SalonNotFound` si absent, URLs
  signées résolues, sans stockage (`None`) → `logo_url`/`photos` à `None` ; `ListOwnSalons` :
  filtre par `owner_id`.
- `test_salon_api.py` — adapter entrant (`TestClient`, ports fakes, sans base) : matrice RBAC de
  `POST /salons` (`MANAGER` → `201`, `CLIENT`/`HAIRDRESSER`/`ADMIN` → `403`, non authentifié →
  `401`) ; anti-élévation (`owner_id` dans le corps ignoré) ; réponse `is_bookable=false`,
  `opening_hours=null` à la création ; `GET /salons/{id}` par un autre gérant → `403` générique
  (pas `404`) ; `GET /salons/{id}` par l'`ADMIN` → `200` ; `GET /salons` liste vide cohérente ;
  routes absentes de `PUBLIC_ROUTE_PATHS` (deny-by-default).
- `test_salon_media_api.py` — routes médias (`TestClient`, ports fakes, sans base) : MIME hors
  liste blanche → `422` ; `object_key` d'un autre salon → `422` (isolation §11.2) ; quota photos
  dépassé → `409` ; `media_storage=None` → `503` pour les routes d'écriture **mais** `POST /salons`
  reste `201` ; `GET /salons` et `GET /salons/{id}` sans stockage → `200` avec `logo_url`/`photos`
  à `null`.

Issue #16 ajoute trois suites dédiées aux horaires d'ouverture :

- `test_domain_opening_hours.py` — domaine pur (aucune I/O) : `parse_opening_hours` et `to_jsonb`
  sans aucune I/O. Horaires par jour, jours fermés (absent ou `[]`), pauses (plusieurs intervalles),
  intervalles invalides (`end ≤ start`, chevauchement, format `HH:MM` non conforme) ; jours
  exceptionnels (`closed=true` sans intervalle, `closed=false` avec intervalle, doublon de date,
  date invalide) ; **non-vacuité utile** (tout vide → `InvalidOpeningHours`) ; **normalisation
  idempotente** (clés minuscules, intervalles triés, `version`, `timezone`) ; bornes de robustesse
  (> `MAX_INTERVALS_PER_DAY` ou > `MAX_EXCEPTIONS` → `InvalidOpeningHours`). Chaque erreur lève
  `InvalidOpeningHours` avec un message neutre (ni PII, ni détail SQL).
- `test_set_opening_hours_usecase.py` — cas d'usage `SetOpeningHours` (ports 100 % fakes) :
  validation **avant** toute écriture (aucun appel au dépôt si la structure est invalide) ;
  `SalonNotFound` si le salon est introuvable ; JSONB normalisé (`version`, `timezone`, intervalles
  triés) transmis au dépôt ; salon renvoyé avec `opening_hours` non null → `is_bookable=True`
  (§8.3) ; **sémantique replace** : un second appel remplace intégralement le premier.
- `test_salon_opening_hours_api.py` — adapter entrant (`TestClient`, ports fakes, sans base) :
  matrice RBAC (`MANAGER` → `200`, `CLIENT`/`HAIRDRESSER`/`ADMIN` → `403`, sans jeton → `401`) ;
  isolation : `MANAGER` visant un autre salon → `403` générique (pas `404`, message sans oracle
  d'existence, PRD §11.1/§11.2) ; succès : `opening_hours` normalisé, `is_bookable=true` dans la
  réponse ; validation : structure invalide → `422` (domaine, pas Pydantic uniquement) ; sémantique
  replace : un second `PUT` écrase complètement le premier.

Issue #17 ajoute cinq suites dédiées à la gestion des prestations et au journal d'audit §11.4 :

- `test_domain_audit.py` — domaine pur (aucune I/O) : `AuditAction` (domaine fermé, valeurs string,
  membres `SERVICE_CREATED`/`SERVICE_UPDATED`/`SERVICE_DEACTIVATED`/`SERVICE_REACTIVATED`) ;
  `AuditEntry` (construction, `metadata` par défaut, `salon_id` par défaut) ; invariant de non-fuite :
  aucun champ PII ni secret dans la structure.
- `test_domain_service.py` — domaine pur (aucune I/O) : `validate_service_name` (trim, vide, > 255
  chars → `InvalidServiceName`) ; `validate_price` (requis, `None`/booléen/flottant refusés, négatif,
  hors borne `NUMERIC(12,2)`, > 2 décimales → `InvalidServicePrice`) ; `validate_duration` (requis,
  `None`/booléen/flottant refusés, `0`, négatif, > 24 h → `InvalidServiceDuration`) ;
  `normalize_category` (`None`/vide → `None`, trop longue, non-chaîne → `InvalidServiceCategory`) ;
  `normalize_description` (`None`/vide → `None`, trim).
- `test_service_usecases.py` — cas d'usage (ports 100 % fakes, sans base) : `CreateService` :
  `salon_id` imposé par l'argument (anti-élévation), `is_active=True` garanti, validation **avant**
  toute écriture, audit `SERVICE_CREATED` avec le bon acteur — **aucun audit si validation échoue** ;
  `ListSalonServices` : liste vide, filtrée par `salon_id` ; `GetService` : `ServiceNotFound` si
  absent ; `UpdateService` : `ServiceNotFound` si absent, validation avant écriture, `metadata.changed`
  correct, audit `SERVICE_UPDATED` — aucun audit sur validation échouée ; `DeactivateService` :
  `ServiceNotFound` si absent, `is_active=False` garanti, audit `SERVICE_DEACTIVATED` ; atomicité :
  si le dépôt échoue avant l'audit, aucune entrée n'est laissée.
- `test_service_api.py` — adapter entrant (`TestClient`, ports fakes, sans base) : matrice RBAC —
  `MANAGER` → `201`/`200`/`204`, `HAIRDRESSER` (avec portée) → `200` en lecture / `403` en mutation,
  `CLIENT`/`ADMIN` → `403`, non authentifié → `401` ; isolation inter-salons → `403` générique (pas
  `404`) ; validation : corps sans `price`/`duration_minutes` → `422`, prix négatif → `422` ; `404`
  pour prestation inconnue (portée validée) ; journalisation : après `PUT`, une entrée
  `SERVICE_UPDATED` est enregistrée ; `unprotected_routes(app)` reste vide (deny-by-default).
- `test_service_e2e.py` — **`TestServiceCrudE2E`** (PostgreSQL requis, **skip propre sans
  `DATABASE_URL`**) : pile complète sans mock (HTTP → cas d'usage → SQL réel + `audit_logs` réels +
  JWT réel) — inscription gérant → connexion → création salon → création prestation → liste → modification
  (valeurs à jour, audit) → consultation → désactivation (`is_active=false`, audit) ; traçabilité
  complète (`SERVICE_CREATED` → `SERVICE_UPDATED` → `SERVICE_DEACTIVATED` dans l'ordre, bon acteur,
  aucun secret/PII dans `metadata`, invariant §11.3/§11.4) ; isolation inter-salons → `403` générique ;
  validation bout-en-bout : prix ou durée manquants/invalides → `422`, aucune entrée d'audit créée
  (atomicité) ; deny-by-default : toutes les routes → `401` sans jeton.

Issue #18 ajoute deux suites dédiées au catalogue client (recherche/liste) :

- `test_search_salons_usecase.py` — cas d'usage `SearchSalons` (ports 100 % fakes, sans base) :
  invariant §8.3 — seuls les salons `ACTIVE` remontent (`INACTIVE`/`SUSPENDED` exclus) ; recherche
  par nom (`text`, `ILIKE` sous-chaîne), filtre par ville/commune ; résolution du logo en **URL
  signée** (avec et sans `MediaStorage`) ; projection publique — `owner_id`, `status`,
  `opening_hours`, `phone` **absents** de `PublicSalonView` (pas d'oracle de compte, pas de
  divulgation d'état) ; `is_bookable` : `True` si `ACTIVE` + `opening_hours` non null (§8.3), `False`
  sinon ; pagination (`limit`, `offset`, `total` cohérents) ; `escape_like` : métacaractères LIKE
  (`%`, `_`, `\\`) correctement échappés.
- `test_catalog_api.py` — adapter entrant (`TestClient`, ports fakes, sans base) :
  `GET /catalog/salons` accessible **sans jeton** (`200`) — route publique-listée (`PUBLIC_ROUTE_PATHS`) ;
  invariant §8.3 : `INACTIVE`/`SUSPENDED` **jamais** dans la réponse ; salons `ACTIVE` visibles ;
  filtres `?q=`, `?city=`, `?commune=` ; pagination — `?limit=`/`?offset=` valides → `200`, hors
  bornes → `422` ; projection : `owner_id`, `status`, `opening_hours`, `phone` absents du JSON ;
  `logo_url` — URL **signée** si stockage configuré, `null` sinon (jamais la clé d'objet) ;
  invariant deny-by-default (ADR-0015) : aucune route orpheline (`unprotected_routes` vide).

Issue #19 ajoute deux suites dédiées à la fiche salon publique (détail) :

- `test_get_public_salon_usecase.py` — cas d'usage `GetPublicSalon` (ports 100 % fakes, sans base) :
  salon `ACTIVE` → `PublicSalonDetailView` complète ; salon `INACTIVE`/`SUSPENDED`/inconnu →
  `SalonNotFound` ; `services` — **actives seulement** (filtre `is_active=True`, les désactivées
  exclues) ; `PublicServiceView` expose `price` (`Decimal`) + `duration_minutes` + `category` + `id` +
  `description` — **sans** `is_active`, `salon_id` ni timestamps ; salon sans prestation → tuple vide ;
  `opening_hours` remontés tels quels, `None` si non configuré → `is_bookable=False` (§8.3) ;
  logo et photos **signés** via `FakeMediaStorage`, `None`/liste de `None` si stockage absent ;
  `logo_url=None` quand aucun `logo_object_key` même avec stockage configuré (invariant ADR-0005 :
  jamais de clé brute) ; `PublicSalonDetailView` sans `owner_id`, `status`, `created_at`,
  `updated_at` ni `logo_object_key`.
- `test_catalog_detail_api.py` — adapter entrant (`TestClient`, ports fakes, sans base) :
  `GET /catalog/salons/{salon_id}` accessible **sans jeton** (`200`) et même avec un en-tête
  `Authorization` présent (route publique-listée, pas bloquée) ; critère §8.3 : `INACTIVE`/`SUSPENDED`
  → **404**, UUID inconnu → **404**, `salon_id` mal formé → **422** ; salon `ACTIVE` → **200** avec
  `services` (actives seulement — prestation désactivée absente), `opening_hours`, `price`,
  `is_bookable` ; `opening_hours=null` si non configuré → `is_bookable=false` ; projection : ni
  `owner_id`, ni `status`, ni timestamps dans la réponse salon ; prestation sans `is_active`,
  `salon_id` ni `created_at` ; `logo_url` — URL **signée** (jamais la clé brute), `null` si stockage
  absent ; photos — URLs signées, clé d'objet brute non exposée, `[]` si aucune photo ;
  coordonnées sérialisées en **nombres flottants** JSON ; invariant deny-by-default : `unprotected_routes`
  vide après ajout de la route de détail.

Issue #33 ajoute trois suites dédiées à la cohérence du montant et à l'enregistrement d'un paiement :

- `test_domain_payment.py` (étendu) — domaine pur (aucune I/O) : `validate_amount_matches` :
  égalité stricte au centime (en `Decimal` quantifié à `0.01`) ; 0,01 d'écart → `PaymentAmountMismatch` ;
  quantisations différentes pour même valeur → OK ; `metadata` neutre — les messages ne reprennent jamais
  les montants (§11.3). `expected_amount_for_prices` : itérable vide → `Decimal("0.00")` ; une entrée ;
  plusieurs entrées ; résultat toujours quantifié à `0.01` (miroir de `NUMERIC(12,2)`) ; tuple accepté.
- `test_cash_journal_usecases.py` (étendu) — cas d'usage `RecordPayment` avec cohérence (#33, ports 100 %
  fakes) : nominal via **prestation seule** — montant = `Service.price` → paiement `VALIDATED` + ligne
  `PAYMENT` + audit `PAYMENT_RECORDED` neutre (`metadata = {}`) ; **montant incohérent** →
  `PaymentAmountMismatch` sans aucune écriture ; **prestation inconnue** ou **inactive** →
  `PaymentReferenceNotFound` sans aucune écriture ; nominal via **RDV** — attendu = somme des
  `price_at_booking` des lignes du RDV ; **RDV inconnu ou hors salon** → `PaymentReferenceNotFound` ;
  **`service_id` fourni n'appartenant pas au RDV** → `PaymentReferenceNotFound`. Invariant structurel :
  un paiement incohérent ou dont la référence est invalide ne laisse aucune trace dans `payments`,
  `cash_journal` ou `audit_logs`.
- `test_cash_journal_api.py` (étendu) — adapter entrant (`TestClient`, ports fakes, sans base) :
  `POST /salons/{id}/payments` : `201` (paiement `VALIDATED`, `recorded_by` du `Principal`) ; `422`
  (montant négatif, mode inconnu, référence prestation/RDV absente, **montant incohérent** →
  `PaymentAmountMismatch`, **prestation inconnue** → `PaymentReferenceNotFound`) ; `401` sans jeton ;
  `403` `CLIENT`/`HAIRDRESSER`/hors-portée (message **générique et constant**) ; champs privilégiés
  dans le corps (`recorded_by`, `status`, `salon_id`) → **ignorés** (`extra="ignore"`) ; aucune route
  caisse/paiement dans `PUBLIC_ROUTE_PATHS` (données financières jamais publiques).

Issue #21 ajoute cinq suites dédiées au moteur de disponibilité et à l'anti double-réservation :

- `test_domain_appointment.py` — domaine pur (aucune I/O) : `require_services` (tuple vide →
  `AppointmentServiceRequired`, non-vide → OK) ; `validate_booking_window` (`end ≤ start` →
  `SlotUnavailable`, `end > start` → OK) ; `compute_end_time` (calcul normal, somme
  multi-prestations, franchissement minuit → `SlotUnavailable`) ; invariants des dataclasses
  (`BookedService`, `AppointmentToCreate`, `Appointment`) — champs préservés, valeurs par défaut,
  immutabilité garantie.
- `test_domain_availability.py` — moteur pur (aucune I/O) : `overlaps` (chevauchement strict
  fermé-ouvert, adjacence `end == start` tolérée, dates différentes non conflictuelles) ;
  `intervals_for_date` (jour absent/fermé, exception datée fermée prime, exception datée ouverte
  prime, programme hebdomadaire par défaut, pauses/multi-intervalles) ; `free_slots` (cas de base,
  jour fermé, service trop long, pauses, créneaux dos-à-dos adjacents, exclusion des `booked`,
  exclusion des créneaux passés via `now`, granularité, tri, déduplication, `duration=0` → `()`) ;
  `is_offered` (créneau dans l'offre, hors horaires, mal aligné, durée ≠ `duration_minutes`, passé,
  déjà occupé) ; `add_minutes` (calcul normal, résultat franchissant minuit → `None`).
- `test_appointment_usecases.py` — cas d'usage (ports 100 % fakes, sans base) :
  `CheckAvailability` : salon inconnu → `SalonNotFound` ; salon non réservable → `SalonNotBookable` ;
  prestation inactive/hors salon → `ServiceNotFound` ; salon réservable → créneaux libres renvoyés
  par le moteur. `BookAppointment` : `client_id`/`salon_id` jamais issus du corps (anti-élévation) ;
  prestation inconnue → `ServiceNotFound` ; `hairdresser_id` hors salon → `HairdresserNotInSalon` ;
  salon non réservable → `SalonNotBookable` ; créneau hors offre → `SlotUnavailable` ; course
  concurrente simulée (`FakeAppointmentRepository(raise_conflict=True)`) → `SlotAlreadyBooked`
  et **rien persisté** ; réservation valide → `Appointment` avec les bons champs.
- `test_appointment_api.py` — adapter entrant (`TestClient`, ports fakes, sans base) :
  `GET /catalog/salons/{salon_id}/availability` : accessible **sans jeton** (`200` avec créneaux) ;
  `404` salon inconnu/non actif ; `409` salon non réservable (§8.3) ; `422` paramètres invalides ;
  réponse sans PII (§11.3). `POST /salons/{salon_id}/appointments` : `401` sans jeton ; `403`
  mauvais rôle (`MANAGER`/`HAIRDRESSER`/`ADMIN`) ; `201` RDV `PENDING` avec bons champs ; `409`
  course concurrente (`SlotAlreadyBooked`), créneau indisponible (`SlotUnavailable`) et salon non
  réservable (`SalonNotBookable`) ; `404` prestation inconnue ; `422` sans prestation (corps
  invalide) ; anti-élévation : `client_id` et `salon_id` ignorés s'ils figurent dans le corps ;
  invariant deny-by-default (`unprotected_routes` vide — la route de disponibilité **est** publique-listée,
  la réservation **ne l'est pas**).
- `test_appointment_concurrency.py` — critère d'acceptation dur (PostgreSQL requis, **skip propre
  sans `DATABASE_URL`**) : deux niveaux à **parallélisme réel** (`ThreadPoolExecutor` +
  `threading.Barrier`) — (1) **niveau SQL** : deux `Session` distinctes (deux connexions/transactions)
  tentent le même créneau/coiffeur → sous `READ COMMITTED`, exactement **1** succès et **1**
  `SlotAlreadyBooked` ; vérification en base qu'une seule ligne `appointments` subsiste (le perdant
  n'a rien persisté, ni RDV ni jonction `appointment_services`) ; (2) **niveau HTTP** : deux
  `POST /salons/{id}/appointments` simultanés, pile complète (JWT réel, sessions réelles) → exactement
  **un 201** et **un 409** (refus garanti par la contrainte d'exclusion `ex_appointments_hairdresser_slot`
  ou le garde `is_offered` — les deux sont corrects). Les données de test sont supprimées avant et
  après chaque test (pas de dépendance entre tests).

Issue #45 ajoute trois suites dédiées à la notification de confirmation de RDV (US-7.1) :

- `test_notification_domain.py` (nouveau) — domaine pur (aucune I/O) : `ChannelAvailability` :
  valeurs par défaut (les deux faux), immuabilité, porte uniquement des booléens (jamais un numéro
  ni un jeton d'appareil) ; `resolve_confirmation_channel` : priorité **PUSH → SMS → IN_APP**
  déterministe — `PUSH` prime sur `SMS` ; sans canal disponible → `IN_APP` ; `WHATSAPP` et `EMAIL`
  **jamais** renvoyés ; `build_confirmation_notification` : type `CONFIRMATION`, statut `PENDING`,
  `user_id = client_id`, `salon_id`/`appointment_id` corrects, canal transmis, `title`/`message`
  **templatés** (constantes — aucun numéro de téléphone dans le titre/message, §11.3) ; immutabilité
  garantie ; `NotificationToCreate` : statut `PENDING` par défaut, immuable, identifiants à `None`
  par défaut.

- `test_appointment_usecases.py` (étendu — `TestBookAppointmentNotification`) — comportement de
  `BookAppointment` (ports 100 % fakes, sans base) : réservation valide → **5** notifications émises
  (1 `CONFIRMATION` + 3 `REMINDER` + 1 `NEW_BOOKING`) ; la `CONFIRMATION` porte `type=CONFIRMATION`,
  `status=PENDING`, `user_id=client_id`, `salon_id` correct, `appointment_id` correspondant au RDV
  créé, canal `SMS` au MVP (faute de jeton PUSH, cf. §12.1), libellés templatés (§11.3 : aucun
  numéro de téléphone) ; réservation échouée (`SlotAlreadyBooked`, `ServiceNotFound`,
  `SalonNotBookable`, `SlotUnavailable`) → **aucune** notification (invariant d'atomicité §8.4/§11.4 :
  la notification n'est jamais émise sur une réservation qui n'aboutit pas).

- `test_appointment_concurrency.py` (étendu) — la fonction `_wipe_test_data` est complétée pour
  supprimer les lignes `notifications` **avant** les RDV/comptes/salons (FK `RESTRICT`
  `notifications → appointments/users/salons` introduite par #45). Les tests de concurrence
  existants (niveau SQL et HTTP) vérifient implicitement le rollback conjoint : le perdant n'obtient
  ni RDV ni notification.

Issue #47 étend les suites de #45/#46 pour la notification au salon à la réservation (US-7.3) :

- `test_notification_domain.py` (étendu) — `TestNotificationTypeNewBooking` : valeur d'enum
  `NotificationType.NEW_BOOKING == "NEW_BOOKING"` ; distincte de `CONFIRMATION`/`REMINDER`/
  `CANCELLATION` (régression schéma — `CHECK` `type` régénéré par la migration `0007`).
  `TestBuildSalonNewBookingNotification` : type `NEW_BOOKING`, canal `IN_APP`, statut `PENDING`,
  `scheduled_for = None` (pas de planification) ; `user_id = owner_id` (gérant, **jamais** le
  client) ; `salon_id`/`appointment_id` corrects ; libellés `NEW_BOOKING_TITLE`/`NEW_BOOKING_MESSAGE`
  **templatés et sans PII** (ni nom ni téléphone du client, §11.3) ; immuabilité garantie.

- `test_appointment_usecases.py` (étendu — `TestBookAppointmentSalonNotification`) — invariants
  de la notification salon : une réservation valide émet **exactement une** `NEW_BOOKING` ; canal
  `IN_APP` explicite (pas « selon disponibilité ») ; `user_id = salon.owner_id` (gérant chargé,
  jamais le client) ; statut `PENDING` ; libellés `NEW_BOOKING_TITLE`/`NEW_BOOKING_MESSAGE` sans
  PII ; émise **en dernier** (après `CONFIRMATION` et `REMINDER`s) ; `user_id` suit l'`owner_id` du
  salon chargé — deux salons avec des gérants distincts produisent des `NEW_BOOKING` ciblant leurs
  gérants respectifs ; réservation échouée → **aucune** `NEW_BOOKING` (rollback conjoint).
  `TestNoNewBookingOnOtherUsecases` : régression de périmètre — `CancelAppointment`,
  `SetAppointmentStatus` et `ModifyAppointment` n'émettent **aucune** `NEW_BOOKING` (les
  notifications d'annulation/modification relèvent de #48, US-7.4).

- `test_appointment_notification_e2e.py` (étendu — `TestAppointmentNotificationE2E`) — bout-en-bout
  SQL réel (PostgreSQL, skip propre sans `DATABASE_URL`) : une réservation réussie insère **1 ligne**
  `NEW_BOOKING`/`IN_APP`/`PENDING` avec `user_id = salon.owner_id` (gérant, **pas** le client),
  `salon_id`/`appointment_id` liés, `scheduled_for IS NULL`, `sent_at IS NULL`, libellés templatés
  **sans PII** — en plus des lignes `CONFIRMATION`/`REMINDER` du client (#45/#46) ; total = `2 +
  len(REMINDER_OFFSETS)` lignes par réservation. Réservation refusée (`409`) → **aucune**
  `NEW_BOOKING` (rollback conjoint). Chaque ligne respecte les contraintes réelles du schéma
  (FK `RESTRICT`, `CHECK type` incluant `NEW_BOOKING` — migration `0007`).
