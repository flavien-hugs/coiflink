# Tests de sécurité (autorisation par rôle, JWT/refresh, brute-force, journalisation des accès sensibles)

> Issue GitHub **#51** — `Must` · Effort `M` · labels `security` `tests` · Jalon **M6** (Sprint 6, durcissement).
> Dépend de **#12** (middleware RBAC deny-by-default). Réfère PRD **§11.2** (autorisation & isolation),
> **§11.1** (JWT/refresh/anti-bruteforce), **§11.3/§11.4** (données personnelles & journalisation).

## Problem Statement

Le socle de sécurité de CoifLink est **livré et testé pièce par pièce**, mais aucune suite ne le
vérifie **comme un tout**, du point de vue d'un attaquant, à l'échelle de toute la surface d'API
désormais montée (M1→M5 : ~une soixantaine de routes réparties sur `auth`, `salons`, `services`,
`appointments`, `customers`, `payments`, `catalog`, `stats`, `admin`, `campaigns`, `receipts`).

Concrètement :

- Les **tests négatifs d'autorisation par rôle** existent, mais sont **dispersés** et **non
  exhaustifs** : `test_domain_permissions.py` fige la matrice §4.1, `test_authorization_policy.py`
  couvre `AccessPolicy`, `test_security_guards.py` teste les gardes sur des *mini-apps* jetables, et
  `test_rbac_e2e.py` exerce l'isolation inter-salons **sur une mini-app** (elle datait d'avant
  l'existence des routes salon réelles, #15). Il **n'existe pas** de matrice « rôle × route réelle →
  code attendu » qui prouve, sur l'application `main.app` telle qu'exposée, qu'un CLIENT ne peut pas
  toucher une route gérant, qu'un HAIRDRESSER ne peut pas encaisser, etc.
- Les propriétés **JWT** (rejet `alg=none`, signature altérée, expiration, mauvais `type`, rotation
  du refresh) sont couvertes au niveau du service (`test_jwt_token_service.py`) mais **pas
  consolidées** en une suite de sécurité lisible, ni systématiquement rejouées **au niveau HTTP**
  contre les routes protégées réelles.
- Le **brute-force** est couvert unitairement (`test_login_rate_limiter.py`, `test_login_api.py`)
  mais **aucun test e2e** ne prouve le verrou de bout en bout (`429` + `Retry-After`, succès qui
  réinitialise, clé IP+identifiant) contre `POST /auth/login` réel.
- La **journalisation des accès sensibles** (§11.3/§11.4) est câblée sur `audit_logs` par plusieurs
  cas d'usage, mais **aucun test transverse** ne vérifie l'invariant central : *toute* ligne
  d'`audit_logs` est **neutre** (aucun secret, aucune PII), et les actions sensibles réellement
  câblées **produisent bien** une entrée.

L'issue #51 comble ce manque : une **suite de sécurité dédiée et consolidée**, exécutable en CI, qui
transforme les invariants §11 en tests **négatifs et transverses** — sans introduire de fonctionnalité.

## Goals

- Fournir une **matrice de tests négatifs d'autorisation par rôle** couvrant un échantillon
  représentatif de routes protégées réelles (`main.app`) : chaque rôle non habilité reçoit **`403`**
  (permission absente / hors portée) ou **`401`** (non authentifié), avec message **générique**.
- Prouver, **de bout en bout sur des routes réelles** (et non plus une mini-app), l'**isolation par
  salon** (§11.2) : un gérant/coiffeur du salon A n'obtient **jamais** les données du salon B —
  **aucune fuite inter-salons**, aucun oracle d'existence (`403` identique, corps sans donnée de B).
- Consolider les **tests JWT/refresh** de sécurité : rejet de `alg=none` et de la confusion
  d'algorithme, signature altérée → `401`, jeton expiré → `401`, refresh présenté en accès → `401`,
  **rotation** du refresh à `/auth/refresh`, refus d'un compte devenu non `ACTIVE` au refresh.
- Prouver la **protection brute-force** de `POST /auth/login` de bout en bout : verrou après le seuil
  (`429` + `Retry-After`), **anti-énumération** (`401` générique et identique compte inconnu / mot de
  passe faux), un **succès réinitialise** le compteur, clé **IP + identifiant**.
- Vérifier la **journalisation des accès sensibles** (§11.3/§11.4) : les actions sensibles
  **actuellement câblées** écrivent une entrée `audit_logs`, et l'**invariant de non-fuite** tient —
  aucune ligne d'audit ne contient de secret ni de PII (téléphone, e-mail, nom, montant, note, corps
  de message, jeton).
- Vérifier les **invariants de non-divulgation** transverses : aucune réponse d'API n'expose
  `password`/`password_hash`/`JWT_SECRET` ; les corps de refus (`401`/`403`) ne portent ni PII ni
  motif exact.
- Intégrer la suite à la **CI existante sans modifier le workflow** (job `backend` de `ci.yml` :
  `DATABASE_URL` défini, `alembic upgrade head` puis `pytest`), avec **skip propre** hors base pour le
  gate ADW local.

## Non-Goals

- **Ne pas implémenter de fonctionnalité** : #51 est une issue de **tests**. Aucun changement de
  comportement de production, aucune nouvelle route, aucune migration.
- **Ne pas combler les manques de journalisation §11.4** dans cette issue (voir *Risks & Open
  Questions*). Les actions §11.4 **non encore journalisées** — `Connexion`, `Création rendez-vous`,
  `Création employé`, `Désactivation salon` — relèvent de leur issue métier ou d'une issue de
  durcissement dédiée ; #51 **teste l'existant** et **documente le gap**, sans l'implémenter.
- Pas de **tests de performance/charge** (§12.1) : c'est l'issue **#52**.
- Pas de tests de sécurité **frontend** (web-dashboard BFF/cookies `httpOnly`, app mobile
  `TokenStore`) : la surface d'autorité est le backend ; l'IU est hors périmètre ici.
- Pas de **pentest dynamique** ni de scan DAST/SAST externe (au-delà de `dependency-scan` déjà en CI).
- Pas de **rigueur *constant-time*** garantie sur la comparaison des identifiants (limite déjà
  documentée ADR-0013) : on teste l'anti-énumération **fonctionnelle** (statut/message identiques),
  pas une propriété temporelle.

## Relevant Repository Context

Stack **figée par ADR** : backend **FastAPI** (Python ≥ 3.12), **PostgreSQL 16**,
**architecture hexagonale** (ADR-0008). Les tests vivent sous `backend/tests/` (`pytest`).

### Socle de sécurité déjà en place (à tester, pas à réécrire)

- **Autorisation / RBAC (ADR-0015, #12)** —
  `backend/coiflink_api/adapters/inbound/security.py` : gardes en **dépendances FastAPI**,
  **deny-by-default** (`require_authenticated` globale + liste blanche `PUBLIC_ROUTE_PATHS`), rôle et
  statut **relus en base** à chaque requête (le claim `role` n'autorise rien),
  `403`/`401`/`503`/`429` à **messages constants**. Invariant `unprotected_routes(app) == []` déjà
  vérifié par `test_security_guards.py`.
- **Matrice de permissions §4.1** — `backend/coiflink_api/domain/permissions.py`
  (`ROLE_PERMISSIONS`, **fermée** ; `ADMIN` **sans joker implicite**). Portée §11.2 —
  `backend/coiflink_api/domain/access.py` (`SalonScope`, `can_access_salon`,
  `can_access_appointment`). Orchestration — `backend/coiflink_api/application/authorization.py`
  (`AccessPolicy`).
- **JWT / refresh / anti-bruteforce (ADR-0013, #10)** —
  `adapters/outbound/security/jwt_token_service.py` (PyJWT HS256, `algorithms=["HS256"]`, rejet
  `alg=none`, exige `exp`/`iat`/`sub`, `type` access/refresh),
  `adapters/outbound/security/login_rate_limiter_memory.py` (fenêtre glissante + verrou, clé
  IP+identifiant), routes dans `adapters/inbound/auth.py` (`/auth/login`, `/auth/refresh`,
  `/auth/password/reset/*`, `/auth/me`).
- **Journalisation §11.4 (ADR-0019, #17)** — table `audit_logs`, domaine
  `backend/coiflink_api/domain/audit.py` (`AuditAction` **fermé**, `AuditEntry` **neutre**,
  `metadata` = noms de champs modifiés uniquement), port `application/ports/audit_log.py`, adapter
  `adapters/outbound/persistence/audit_log_repository.py` (écriture **même unité de travail**).

### Couverture d'audit §11.4 **réellement câblée aujourd'hui** (vérifiée dans le code)

Écrivent une entrée `audit_logs` (via `self._audit_log.record(AuditEntry(...))`) :

| Action `AuditAction` | Cas d'usage | §11 |
| --- | --- | --- |
| `SERVICE_CREATED/UPDATED/DEACTIVATED/REACTIVATED` | `application/services.py` | §11.4 « Modification prestation » |
| `SALON_UPDATED` | `application/salons.py` | §11.4 « Modification salon » |
| `APPOINTMENT_UPDATED` | `application/appointments.py` (#23) | §11.4 « Modification RDV » |
| `APPOINTMENT_CANCELLED` | `application/appointments.py` (#24/#25) | §11.4 « Annulation » |
| `APPOINTMENT_STATUS_CHANGED` / `APPOINTMENT_HAIRDRESSER_ASSIGNED` | `application/appointments.py` (#25) | §11.4 « Cycle de statuts » |
| `CUSTOMER_CREATED` / `CUSTOMER_NOTE_UPDATED` | `application/customers.py` (#28/#32) | §11.3 « accès sensibles » (collecte PII / donnée de santé) |
| `PAYMENT_RECORDED` | `application/payments.py` (#33) | §11.4 « Paiement enregistré » |
| `CASH_ADJUSTED` | `application/cash_journal.py` (#34) | §11.4 « Correction de caisse » |
| `CAMPAIGN_CREATED` | `application/campaigns.py` (#49) | §11.4 (message manuel du gérant) |

**Non câblées** (PRD §11.4 les liste mais aucune entrée `audit_logs` n'est écrite aujourd'hui —
absence vérifiée) : **`Connexion`** (aucune `AuditAction` de login), **`Création rendez-vous`**
(la réservation #21 émet une **notification** `CONFIRMATION`, pas une entrée d'audit),
**`Création employé`** (#13, antérieure au mécanisme d'audit #17), **`Désactivation salon`** (aucune
route de changement de statut salon montée à ce jour — zone `/admin` absente). #51 **ne les
implémente pas** et **n'assert pas** leur présence (voir *Risks & Open Questions*).

### Tests de sécurité existants (points d'appui et patrons à réutiliser)

`test_domain_permissions.py`, `test_domain_access.py`, `test_authorization_policy.py`,
`test_domain_principal.py` (domaine, sans I/O) ; `test_security_guards.py` (gardes sur mini-apps,
fakes de `tests/conftest.py`) ; `test_rbac_e2e.py` (isolation inter-salons, **PostgreSQL requis**,
mini-app) ; `test_jwt_token_service.py`, `test_login_rate_limiter.py`, `test_login_api.py`,
`test_login_e2e.py`, `test_manager_auth_api.py`, `test_password_reset_*` (auth) ;
`test_secrets_policy.py` (invariants statiques secrets/PII). `test_critical_journeys_e2e.py`
donne le **patron e2e** (fixture partagée, `skipif(not DATABASE_URL)`, plage de téléphones réservée,
nettoyage FK-safe). `tests/conftest.py` expose `FakeTokenService`, `FakeAuthUserRepository`,
`FakeSalonScopeRepository`, `FAKE_ACCESS_CLAIMS`.

### Conventions e2e (à respecter, cf. `docs/strategie-de-tests.md` §5)

Fichier `backend/tests/test_*_e2e.py` ; `@pytest.mark.skipif(not DATABASE_URL, …)` sur la classe +
`pytest.skip(...)` en fixture ; **plage de téléphones distincte** (grep les préfixes déjà pris) ;
**nettoyage FK-safe** — supprimer `notifications` **et** `campaigns` **avant** `appointments` /
`payments` / `cash_journal` / `salons` / `users` (FK `RESTRICT`, mémoire *notifications-fk-restrict*) ;
**JWT de test factice** injecté sur `app.state` (jamais un vrai secret) ; **jamais** journaliser
jeton, mot de passe, téléphone en sortie de test (§11 ; vérifié par `test_secrets_policy.py`).

## Proposed Implementation

Ajouter une **suite de sécurité consolidée** sous `backend/tests/`, organisée par **préoccupation
§11**, en réutilisant au maximum les patrons et fakes existants. Deux niveaux :

1. **Tests rapides (sans base)** — matrice d'autorisation, propriétés JWT, brute-force unitaire,
   invariants statiques. Tournent dans le **gate ADW** et en CI.
2. **Tests e2e (PostgreSQL requis)** — isolation inter-salons sur routes réelles, brute-force HTTP,
   journalisation d'audit sur pile réelle, non-fuite dans les réponses. `skipif` propre sans base.

### 1. Matrice de tests négatifs d'autorisation par rôle — `test_security_authz_matrix.py` (rapide)

But : prouver, sur l'application **réelle** (`from coiflink_api.main import app`), qu'un rôle non
habilité est **refusé** sur un échantillon représentatif de routes protégées, **sans dépendre de la
base** (dépendances surchargées par fakes, patron `test_security_guards.py`).

- Construire une table déclarative `(method, path, allowed_roles)` couvrant au moins un endpoint
  **par famille de permission** : `SALON_CREATE` (`POST /salons`), `SERVICE_MANAGE`
  (`POST /salons/{id}/services`), `APPOINTMENT_BOOK` (`POST /salons/{id}/appointments`),
  `CUSTOMER_MANAGE` (`POST /salons/{id}/customers`), `PAYMENT_RECORD` (`POST /salons/{id}/payments`),
  `CASH_JOURNAL_READ` (`GET /salons/{id}/payments`), `STATS_READ_SALON`
  (`GET /salons/{id}/revenue/summary`), `STATS_READ_PLATFORM` (`GET /admin/kpis`),
  `PAYMENT_READ_OWN` (`GET /me/receipts`), `APPOINTMENT_READ_OWN` (`GET /appointments/history`).
- Pour **chaque route** et **chaque rôle non autorisé** (`CLIENT`/`HAIRDRESSER`/`MANAGER`/`ADMIN`),
  surcharger `get_user_repository` + `get_access_policy` (et `app.state.token_service = FakeTokenService()`)
  pour incarner ce rôle, appeler la route, et **attendre `403`** avec `detail == "Accès refusé."`
  (message générique). Sans jeton → **`401`** + `WWW-Authenticate: Bearer`.
- Dériver la table **au maximum** de `ROLE_PERMISSIONS` pour éviter la dérive : un test paramétré
  vérifie que, pour chaque route, l'ensemble des rôles refusés = tous les rôles − `allowed_roles`.
- Réutiliser l'invariant existant `unprotected_routes(app) == []` (déjà dans `test_security_guards.py`) ;
  **ne pas le dupliquer**, éventuellement le citer.
- **Élévation de privilège via inscription** : `POST /auth/register` / `/auth/register/manager` avec
  un champ `role` dans le corps → le rôle **reste** celui fixé côté serveur (le champ est ignoré,
  `RegisterRequest` ne le déclare pas). Cas négatif explicite.

### 2. Isolation inter-salons de bout en bout — `test_security_isolation_e2e.py` (PostgreSQL requis)

But : remplacer la démonstration sur mini-app de `test_rbac_e2e.py` par une preuve sur **routes de
production réelles** (elles existent depuis #15+), sur la **pile complète** (HTTP → gardes → dépôts
SQL → PostgreSQL, JWT réel injecté).

- Fixture : inscrire **gérant A** et **gérant B** (plage de téléphones réservée), chacun crée son
  salon via `POST /salons` ; A se connecte (paire de jetons réelle).
- **Lecture inter-salons** : jeton A sur `GET /salons/{salon_B}` , `.../services`, `.../appointments`,
  `.../payments`, `.../customers`, `.../revenue/summary`, `.../daily-summary` → **`403`** systématique.
- **Écriture inter-salons** : jeton A sur `POST /salons/{salon_B}/services`,
  `POST /salons/{salon_B}/customers`, `POST /salons/{salon_B}/payments` → **`403`** ; vérifier
  **qu'aucune ligne n'est écrite** dans le salon B (contrôle en base ou via lecture par B).
- **Anti-oracle** : le corps du `403` inter-salons ne contient **ni** `salon_B`, **ni** l'id de B,
  **ni** aucune donnée de B ; `detail == "Accès refusé."` — **identique** au `403` d'un rôle
  insuffisant (comparer les deux corps).
- **Fuite par filtre client étranger** (§11.2, patron déjà appliqué #35/#37) : gérant A liste ses
  paiements en passant un `client_id` appartenant à B → **liste vide**, jamais les données de B.
- **CLIENT** : jeton client sur toute route `/salons/{id}/…` → **`403`** (un client n'a pas de portée
  salon). Un client tente `GET /me/receipts/{payment_id}` d'un **tiers** → **`404`** neutre (pas
  d'oracle). Un client liste `GET /appointments/history` → ne voit **que** ses RDV.
- **HAIRDRESSER** : rôle assigné à ≥ 1 RDV d'un salon → lecture de « son planning » OK ; encaissement
  (`POST /salons/{id}/payments`) → **`403`** (pas de `PAYMENT_RECORD`).

### 3. JWT / refresh — `test_security_jwt.py` (rapide) + volet HTTP dans l'e2e

But : consolider les propriétés cryptographiques et de session en une suite de sécurité lisible
(beaucoup existent déjà dans `test_jwt_token_service.py` ; **regrouper/compléter**, ne pas dupliquer
à l'identique — préférer référencer et ajouter les cas manquants).

- **`alg=none` rejeté** : forger un jeton non signé (`{"alg":"none"}`) → `verify_access` lève
  `InvalidToken` ; au niveau HTTP `GET /auth/me` → **`401`**.
- **Confusion d'algorithme** : jeton signé avec un autre schéma / `alg` inattendu → rejeté (le
  décodage **impose** `algorithms=["HS256"]`).
- **Signature altérée** → `401` (réutiliser `_tamper_signature`, cible l'avant-dernier caractère).
- **Claims manquants** (`exp`/`iat`/`sub` absents) → rejeté.
- **Expiration** : jeton d'accès expiré (TTL négatif via `JwtTokenService` de test) → `401`.
- **Mauvais `type`** : refresh présenté comme accès sur route protégée → `401` ; message **identique**
  à l'absence de jeton (anti-énumération).
- **Rotation du refresh** : `POST /auth/refresh` émet une **nouvelle** paire (access **et** refresh
  changent) et relit `role`/`status` courants.
- **Refus au refresh d'un compte non `ACTIVE`** : compte suspendu → `/auth/refresh` refuse
  (`401`/`403` selon le contrat de `RefreshTokens`, à figer d'après le code).
- **Révocation immédiate par relecture en base** : compte suspendu **après** émission d'un accès
  valide → requête protégée suivante → **`403` « Compte désactivé. »** (le claim ne fait pas
  autorité). *(Volet e2e — déjà esquissé dans `test_rbac_e2e.py`, à conserver/consolider.)*
- **503** si `JWT_SECRET` absent (`token_service` non assemblé) sur route protégée.

### 4. Brute-force — volet e2e dans `test_security_isolation_e2e.py` ou `test_security_bruteforce_e2e.py`

But : prouver le verrou **de bout en bout** contre `POST /auth/login` (l'unitaire existe déjà).

- Injecter un `InMemoryLoginRateLimiter` de test aux seuils déterministes (p. ex. 5/300 s → 900 s,
  comme `test_rbac_e2e.py`). Enchaîner N échecs sur le **même** identifiant + IP → au dépassement,
  **`429`** + en-tête **`Retry-After`**.
- **Anti-énumération** : `401` **générique et identique** pour compte inconnu et mot de passe faux
  (`detail == "Identifiants invalides."`) — jamais de `422` divulguant la politique de mot de passe.
- **Un succès réinitialise** le compteur (une bonne connexion avant le seuil remet à zéro).
- **Clé IP + identifiant** : le verrou d'un identifiant ne verrouille pas un **autre** identifiant
  (défense contre le verrouillage trivial d'un tiers). *(Au niveau `TestClient`, l'IP du pair est
  constante ; ce cas peut rester unitaire sur `InMemoryLoginRateLimiter` si l'e2e ne peut pas varier
  l'IP — à trancher à l'implémentation.)*
- **Reset OTP** : mêmes garanties génériques sur `/auth/password/reset/request` (toujours `202`,
  `429` si flood) — réutiliser/consolider `test_password_reset_e2e.py` si utile.

### 5. Journalisation des accès sensibles §11.3/§11.4 — `test_security_audit_e2e.py` (PostgreSQL requis)

But : prouver que les actions sensibles **câblées** produisent une entrée `audit_logs` et que
**l'invariant de non-fuite** tient.

- **Présence** : pour un échantillon d'actions sensibles réelles — création de fiche client
  (`CUSTOMER_CREATED`), mise à jour de note (`CUSTOMER_NOTE_UPDATED`), enregistrement de paiement
  (`PAYMENT_RECORDED`), correction de caisse (`CASH_ADJUSTED`), modification de prestation
  (`SERVICE_UPDATED`), modification de salon (`SALON_UPDATED`), modification/annulation de RDV
  (`APPOINTMENT_UPDATED`/`APPOINTMENT_CANCELLED`) — exécuter l'action via l'API, puis **compter les
  lignes `audit_logs`** correspondantes (par `action` + `entity_id` + `actor_user_id`) → **≥ 1**.
- **Atomicité** : une action métier qui **échoue** (p. ex. paiement au montant incohérent → `422`)
  ne laisse **aucune** entrée d'audit (même unité de travail, patron ADR-0019).
- **Invariant de non-fuite (cœur du critère §11.3)** : après le parcours, **balayer toutes les lignes
  `audit_logs`** produites (par `actor_user_id` de test) et asserter que, sérialisées, elles ne
  contiennent **aucune** PII ni secret des entités de test — ni le téléphone/e-mail/nom du client, ni
  le montant du paiement, ni le contenu de la note, ni le corps d'un message de campagne, ni un jeton.
  `metadata` ne porte que des **noms de champs** (`{"changed":[...]}`) ou un effectif entier.
- **Portée §11.2 sur le journal** : `actor_user_id` et `salon_id` sont des UUID **opaques** ; la
  lecture directe reste un contrôle DB de test (aucune route de consultation du journal n'existe —
  hors périmètre).

### 6. Invariants de non-divulgation transverses — `test_security_no_leak.py` (rapide, statique/HTTP léger)

- **Réponses sans secret** : `GET /auth/me`, `POST /auth/register*`, `POST /auth/login` ne renvoient
  jamais `password`, `password_hash`, `JWT_SECRET` (déjà partiellement couvert — consolider).
- **`PUBLIC_ROUTE_PATHS`** : figer la liste blanche (test de régression) — toute route financière
  (`/me/receipts*`, `/salons/*/payments`) et toute mutation **hors** de la liste (déjà amorcé par
  `test_receipt_routes_not_in_public_route_paths`). Vérifier qu'aucun chemin `*/payments`,
  `*/customers`, `/admin/*` n'y figure.
- **Append-only caisse** (déjà présent — réutiliser `test_no_destructive_routes_for_payments_or_cash_journal`).

> **Réutilisation vs duplication** : privilégier l'**extension** des fichiers existants quand le
> thème correspond exactement (p. ex. compléter `test_jwt_token_service.py`) ; créer un **nouveau**
> fichier `test_security_*` quand la valeur est la **consolidation transverse** (matrice rôle×route,
> non-fuite d'audit). Éviter de recopier des assertions déjà couvertes ; référencer par commentaire.

## Affected Files / Packages / Modules

**Nouveaux fichiers de test (probables)** :

- `backend/tests/test_security_authz_matrix.py` — matrice rôle × route réelle (rapide).
- `backend/tests/test_security_jwt.py` — propriétés JWT/refresh consolidées (rapide).
- `backend/tests/test_security_no_leak.py` — non-divulgation & liste blanche (rapide).
- `backend/tests/test_security_isolation_e2e.py` — isolation inter-salons sur routes réelles (PG requis).
- `backend/tests/test_security_audit_e2e.py` — journalisation §11.3/§11.4 + non-fuite (PG requis).
- `backend/tests/test_security_bruteforce_e2e.py` — brute-force login HTTP (PG requis) *(ou volet
  intégré à `test_security_isolation_e2e.py` — à trancher).*

**À lire / réutiliser (sans modifier le comportement)** :

- `backend/coiflink_api/adapters/inbound/security.py` (gardes, helpers `unprotected_routes`,
  `PUBLIC_ROUTE_PATHS`).
- `backend/coiflink_api/domain/permissions.py`, `domain/access.py`, `application/authorization.py`.
- `backend/coiflink_api/adapters/outbound/security/jwt_token_service.py`,
  `login_rate_limiter_memory.py`, `adapters/inbound/auth.py`.
- `backend/coiflink_api/domain/audit.py`, `application/ports/audit_log.py`,
  `adapters/outbound/persistence/audit_log_repository.py`, `.../models.py` (table `audit_logs`).
- `backend/tests/conftest.py` (fakes), `test_security_guards.py`, `test_rbac_e2e.py`,
  `test_critical_journeys_e2e.py` (patrons e2e), `test_secrets_policy.py`.

**Documentation (mise à jour légère, voir plus bas)** :

- `README.md` (§6 — mention #51 livrée), `docs/strategie-de-tests.md` (ligne « tests de sécurité »),
  éventuellement `backend/README.md`.

## API / Interface Changes

**None.** Aucune route, aucun schéma, aucun paramètre CLI ne change. #51 n'ajoute que des tests. Les
seuls nouveaux « points d'entrée » sont des fichiers de test invoqués par `pytest` (déjà collecté par
la CI et le gate).

## Data Model / Protocol Changes

**None.** Aucune migration, aucune table, aucune colonne. Les tests **lisent** `audit_logs` /
`salons` / `users` / `payments` en base de test mais n'altèrent pas le schéma. Les tests e2e
**insèrent puis nettoient** des données dans une plage de téléphones réservée (nettoyage FK-safe).

## Security & Privacy Considerations

Cette issue **renforce** les invariants §11 sans les affaiblir ; à respecter dans les tests
eux-mêmes :

- **Jamais de secret ni de PII dans la sortie de test** (§11 ; `docs/strategie-de-tests.md` §6,
  `test_secrets_policy.py`). La sortie du gate est transmise à l'agent en cas d'échec : ne pas
  `print`/assert-message un jeton, un mot de passe, un téléphone, un e-mail. Utiliser des messages
  d'assertion neutres.
- **JWT de test factice uniquement** : injecter un `JwtTokenService`/secret **local** sur
  `app.state` (comme `test_rbac_e2e.py`), jamais un secret réel ; ne pas lire `JWT_SECRET` de prod.
- **Plage de téléphones réservée + nettoyage FK-safe** : choisir un préfixe **non utilisé** (grep les
  préfixes déjà pris — p. ex. `+225 08 999x` semble libre ; **vérifier à l'implémentation**).
  Nettoyer `notifications` **et** `campaigns` **avant** `appointments`/`payments`/`cash_journal`/
  `salons`/`users` (FK `RESTRICT`).
- **L'invariant de non-fuite du journal** (§11.3/§11.4) est **testé** ici, pas relâché : le test
  échoue si une PII/secret apparaît dans `audit_logs`.
- **Anti-énumération / anti-oracle** : les assertions figent des messages **génériques** (`401`/`403`
  constants, `404` neutre) — un test qui exigerait un message spécifique révélant le motif serait
  contraire à l'invariant et ne doit pas être écrit.
- **Résidence / hébergement** : sans objet (tests locaux/CI, PostgreSQL 16 éphémère).

## Testing Plan

Cette issue **est** un plan de tests. Découpage par niveau (cf. `docs/strategie-de-tests.md`) :

- **Unitaire / rapide (gate ADW + CI, sans base)** :
  - Matrice rôle × route → `403`/`401` génériques (`test_security_authz_matrix.py`).
  - Élévation de privilège via `role` dans le corps d'inscription → ignorée.
  - JWT : `alg=none`, confusion d'algorithme, signature altérée, claims manquants, expiration,
    mauvais `type`, `503` sans secret (`test_security_jwt.py`).
  - Brute-force **unitaire** (clé IP+identifiant, reset par succès) si l'e2e ne peut pas varier l'IP.
  - Non-divulgation & régression de `PUBLIC_ROUTE_PATHS` (`test_security_no_leak.py`).
- **e2e / intégration (CI job `backend`, PostgreSQL requis, `skipif` sans `DATABASE_URL`)** :
  - Isolation inter-salons lecture **et** écriture sur routes réelles ; anti-oracle ; filtre
    `client_id` étranger → vide (`test_security_isolation_e2e.py`).
  - Révocation immédiate (compte suspendu après émission → `403`).
  - Rotation du refresh ; refus au refresh d'un compte non `ACTIVE`.
  - Brute-force HTTP `POST /auth/login` : `429` + `Retry-After`, `401` générique identique
    (`test_security_bruteforce_e2e.py` ou volet).
  - Journalisation : présence des entrées sensibles, atomicité (échec → 0 entrée), **non-fuite**
    balayant `audit_logs` (`test_security_audit_e2e.py`).
- **Intégration CI** : aucun changement de workflow. Les fichiers `*_e2e.py` s'exécutent dans le job
  `backend` de `ci.yml` (où `DATABASE_URL` est défini et `alembic upgrade head` précède `pytest`) ;
  les fichiers rapides tournent aussi dans le gate ADW. Vérifier localement :
  `TEST_GATE_PACKAGES="backend" scripts/test-gate.sh` (rapides) et, avec base,
  `DATABASE_URL=… alembic upgrade head && DATABASE_URL=… pytest tests/test_security_*_e2e.py -v`
  (mémoire *local-e2e-postgres* : instance `coiflink-e2e-pg` port `55433`).
- **Déterminisme** : horloge/TTL injectés pour l'expiration et le brute-force ; aucune dépendance à
  l'heure murale.

## Documentation Updates

- **`docs/strategie-de-tests.md`** : ajouter une entrée « tests de sécurité (#51) » dans la pyramide
  (unitaire + e2e) et, si pertinent, une ligne dans le tableau « quoi tourne où ». Documenter la
  **plage de téléphones** réservée par la suite.
- **`README.md`** (§6, chronologie M6) : mention que #51 est livrée (suite de sécurité authz/JWT/
  brute-force/journalisation), après #50. Rester factuel, sans signature IA.
- **`backend/README.md`** : éventuellement lister les nouveaux fichiers `test_security_*` et leur
  périmètre.
- **Aucun ADR requis** : #51 n'introduit aucune décision d'architecture (issue de tests). Documenter
  le **gap §11.4** (actions non journalisées) dans le corps de la PR / une note, plutôt qu'un ADR,
  sauf décision explicite de le combler (voir ci-dessous).
- **Pas de nouvelle API publique** → aucune doc d'endpoint à produire.

## Risks and Open Questions

- **Gap de journalisation §11.4 (décision à confirmer).** La liste PRD §11.4 inclut `Connexion`,
  `Création rendez-vous`, `Création employé`, `Désactivation salon`, **non journalisés** aujourd'hui.
  - *Recommandation par défaut* : #51 **teste l'existant** et **documente** le gap ; il **n'assert
    pas** la présence de ces entrées (sinon les tests échoueraient et impliqueraient un comportement
    inexistant). Combler le gap = **feature work** relevant des issues métier concernées ou d'une
    issue de durcissement dédiée.
  - *Alternative* (si le mainteneur juge le critère « accès sensibles journalisés » incomplet sans
    la connexion) : ouvrir une sous-tâche pour ajouter `AuditAction.LOGIN` (entrée **neutre** :
    `actor_user_id` + horodatage, **jamais** l'identifiant en clair) — **hors périmètre de #51 tel
    que spécifié ici**. À confirmer avant l'implémentation.
  > Note : ADR-0015 (ligne « Suivis ») renvoie la journalisation §11.4 à « #52 », mais le mécanisme a
  > en réalité été livré en **#17** et #52 est devenue « Tests de performance » — la référence de
  > l'ADR est **périmée**. Ne pas s'y fier ; s'appuyer sur la couverture réelle tabulée ci-dessus.
- **`test_rbac_e2e.py` sur mini-app vs routes réelles.** Faut-il **remplacer** la démonstration
  mini-app par l'e2e sur routes réelles, ou **conserver les deux** ? *Recommandation* : conserver
  l'ancien (couvre `require_salon_scope` isolément) et **ajouter** l'e2e routes-réelles (couvre la
  chaîne complète). Éviter la duplication d'assertions strictement identiques.
- **Portée de la matrice rôle × route.** Exhaustive (toutes les routes) ou **représentative** (une par
  famille de permission) ? *Recommandation* : représentative + dérivée de `ROLE_PERMISSIONS` pour
  résister à la dérive ; l'exhaustivité mécanique est déjà assurée par `unprotected_routes(app)`.
- **Compte `ADMIN` inatteignable en production.** Aucun chemin d'amorçage `ADMIN` n'existe
  (ADR-0015). Les tests de routes `/admin/*` doivent **fabriquer** un compte `ADMIN` en base de test
  (insertion directe) pour exercer les cas positifs/négatifs — documenter que c'est un artefact de
  test, pas un chemin de production.
- **Variation d'IP en brute-force e2e.** `TestClient` présente une IP de pair constante : tester la
  clé **IP + identifiant** de bout en bout peut être impossible sans manipuler `request.client`.
  *Recommandation* : garder ce cas en **unitaire** sur `InMemoryLoginRateLimiter`, et se limiter en
  e2e au verrou par identifiant.
- **Coût CI.** Plusieurs nouveaux `*_e2e.py` allongent le job `backend`. Volumétrie faible (MVP) →
  impact marginal ; regrouper les scénarios sous une **fixture partagée** (patron
  `test_critical_journeys_e2e.py`) pour limiter les allers-retours base.
- **Collision de plage téléphone.** Beaucoup de préfixes `+225…` sont déjà pris — **grep obligatoire**
  avant de figer la plage de la suite (candidat : `+225 08 999x`, à confirmer libre).
- **Stack** : rien d'incertain ici — backend Python/FastAPI/PostgreSQL figé par ADR ; aucun choix de
  toolchain à trancher.

## Implementation Checklist

1. **Reconnaissance** : relire `security.py`, `permissions.py`, `access.py`, `authorization.py`,
   `jwt_token_service.py`, `login_rate_limiter_memory.py`, `auth.py`, `audit.py` + adapter d'audit,
   et les tests existants (`test_security_guards.py`, `test_rbac_e2e.py`, `test_jwt_token_service.py`,
   `test_login_*`, `test_critical_journeys_e2e.py`, `conftest.py`). Confirmer la table de couverture
   d'audit §11.4 (grep `\.record(` / `AuditAction.`).
2. **Réserver une plage de téléphones** unique pour la suite e2e (grep les préfixes pris ; figer une
   constante `_SEC_PHONE_PREFIX`).
3. **`test_security_authz_matrix.py`** (rapide) : table `(method, path, allowed_roles)` par famille
   de permission ; helper qui incarne un rôle via fakes (`FakeTokenService`, `FakeAuthUserRepository`,
   `FakeSalonScopeRepository`, overrides `get_user_repository`/`get_access_policy`) ; paramétrer
   rôles refusés → `403` générique ; sans jeton → `401` + `WWW-Authenticate`. Ajouter le cas
   « `role` dans le corps d'inscription ignoré ».
4. **`test_security_jwt.py`** (rapide) : `alg=none`, confusion d'algorithme, signature altérée,
   claims manquants, expiration (TTL négatif), mauvais `type`, message identique à l'absence de
   jeton, `503` sans secret. Ne pas dupliquer ce qui est déjà couvert — compléter/consolider.
5. **`test_security_no_leak.py`** (rapide) : réponses sans `password`/`password_hash`/secret ;
   régression `PUBLIC_ROUTE_PATHS` (aucune route `*/payments`, `*/customers`, `/admin/*`) ; réutiliser
   l'invariant append-only caisse.
6. **`test_security_isolation_e2e.py`** (PG requis) : fixture gérants A/B + salons ; matrice lecture
   **et** écriture inter-salons → `403` ; anti-oracle (corps sans donnée de B, `detail` identique) ;
   filtre `client_id` étranger → vide ; CLIENT/HAIRDRESSER refus ; révocation immédiate (suspendu →
   `403`) ; rotation refresh. `skipif(not DATABASE_URL)` + nettoyage FK-safe (notifications/campaigns
   d'abord).
7. **`test_security_bruteforce_e2e.py`** (PG requis, ou volet du fichier précédent) : limiteur de test
   déterministe ; N échecs → `429` + `Retry-After` ; `401` générique identique (compte inconnu / mot
   de passe faux) ; succès réinitialise. Cas « clé IP+identifiant » en unitaire si l'e2e ne peut varier
   l'IP.
8. **`test_security_audit_e2e.py`** (PG requis) : exécuter des actions sensibles réelles via l'API ;
   asserter la **présence** des entrées `audit_logs` (par `action`+`entity_id`+`actor_user_id`) ;
   **atomicité** (action échouée → 0 entrée) ; **non-fuite** en balayant les lignes produites (aucune
   PII/secret des entités de test) ; compte `ADMIN` de test fabriqué en base pour `/admin/*`.
9. **Exécuter** : rapides via `TEST_GATE_PACKAGES="backend" scripts/test-gate.sh` ; e2e via
   `DATABASE_URL=… alembic upgrade head && DATABASE_URL=… pytest tests/test_security_*_e2e.py -v`
   (Postgres local `coiflink-e2e-pg:55433`). Vérifier `ruff check`.
10. **Vérifier l'hygiène §11** : aucune sortie de test ne contient jeton/mot de passe/PII ;
    `test_secrets_policy.py` reste vert.
11. **Documentation** : mettre à jour `docs/strategie-de-tests.md` (entrée #51 + plage réservée),
    `README.md` §6 (M6, #51 livrée), éventuellement `backend/README.md`. **Documenter le gap §11.4**
    (actions non journalisées) dans la note de PR. Aucune signature IA dans le code, les commits ou la
    PR.
12. **Confirmer les décisions ouvertes** avec le mainteneur avant de figer : traitement du gap §11.4
    (test-only vs ajout `LOGIN`), remplacement ou coexistence de `test_rbac_e2e.py`, portée de la
    matrice.
