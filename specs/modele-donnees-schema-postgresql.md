# Modèle de données & schéma initial PostgreSQL

> Spécification de planification pour l'issue GitHub **#3 — Modèle de données & schéma initial
> PostgreSQL** (`infra` `tech-debt` · Must · Effort M · PRD §9). **Dépend de #1** (stack figée par les
> ADR) **et de #2** (arborescence du monorepo + squelette `backend/`).
> **Cette spec ne produit pas de code.** Elle décrit le schéma, l'outillage de migrations et les
> contraintes à implémenter dans une phase ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR). Les en-têtes de
> section ci-dessous sont conservés en anglais car ils sont attendus par le gabarit du pipeline ADW ;
> le contenu livré (README, ADR, commentaires) reste en français, hors identifiants techniques (noms
> de tables/colonnes, SQL, enums).

## Problem Statement

Le domaine CoifLink est fortement relationnel et porte des **contraintes d'intégrité critiques** :
un rendez-vous doit toujours être rattaché à un salon et à **au moins une prestation** (§8.1) ; un
paiement doit toujours être lié à une prestation ou à un rendez-vous (§8.2) ; un créneau ne peut pas
être réservé deux fois pour le même coiffeur (§8.1). L'ADR-0004 a **figé PostgreSQL** comme base
relationnelle principale précisément pour porter ces garanties (ACID, clés étrangères, unicité), mais
a **explicitement renvoyé à l'issue #3** le détail du schéma, des migrations, des versions et du choix
d'**ORM / outil de migrations** (ADR-0004 « Suivi », ADR-0003 « Suivi »).

À ce jour, le paquet `backend/` n'est qu'un **squelette hexagonal** (ADR-0008) : il n'expose qu'un
endpoint `/health` et **ne contient ni table, ni entité, ni migration**. Le `.env.example` fournit un
placeholder `DATABASE_URL` mais aucune base n'est modélisée. Tant que le schéma n'existe pas,
**toutes les fonctionnalités M1→ sont bloquées** : l'inscription client/gérant (#8/#9), les salons et
prestations (#15+), les rendez-vous (#21+), l'encaissement (#28+) et les notifications (#39+) écrivent
toutes dans ces tables.

Le besoin : **matérialiser le schéma des 8 entités du §9 sous forme de migrations versionnées
up/down exécutables**, porteuses des contraintes clés métier, **documentées**, et câblées dans
l'architecture hexagonale du backend (persistance = adapter sortant) **sans introduire de dépendance
du domaine vis-à-vis de l'ORM** (ADR-0008).

## Goals

- **Choisir et câbler l'outillage de migrations + l'ORM** laissés ouverts par ADR-0003/0004
  (recommandation : **SQLAlchemy 2.0 + Alembic** + driver **psycopg 3** — voir *Risks* pour la
  décision à confirmer), et le **documenter** (mise à jour d'ADR / nouvel ADR-0009).
- **Définir les 8 entités du §9** : `User`, `Salon`, `Service` (Prestation), `Appointment`,
  `CustomerProfile`, `Payment`, `CashJournal`, `Notification`, avec leurs colonnes, types, valeurs par
  défaut, clés primaires/étrangères, index et contraintes.
- **Fournir une migration initiale up/down exécutable** (`alembic upgrade head` puis
  `alembic downgrade base` réversibles et idempotents).
- **Porter les contraintes clés métier dans le schéma** :
  - RDV obligatoirement lié à **un salon** (FK `NOT NULL`) **et à ≥ 1 prestation** (§8.1) ;
  - **paiement lié à une prestation ou à un rendez-vous** (§8.2) — `CHECK` de présence d'au moins une
    référence ;
  - **anti double-réservation** d'un créneau pour un même coiffeur (§8.1) ;
  - **journal de caisse horodaté** (§8.2) et conçu en **journal append-only** (pas de suppression d'un
    paiement validé ; correction = nouvelle opération `ADJUSTMENT`).
- **Respecter l'isolation par salon** (§11.2) : chaque table à portée salon porte `salon_id` indexé,
  pour servir le RBAC strict des issues M1.
- **Documenter le schéma** : dictionnaire des tables + diagramme relationnel + commandes de
  migration, dans `backend/README.md` (et/ou `docs/`).
- **Geler la version de référence PostgreSQL** (recommandation : **PostgreSQL 16**, déjà citée pour
  mémo par le README §4 et l'ADR-0004).

## Non-Goals

- **Aucune logique métier ni endpoint** : pas de cas d'usage, de repository concret, de router CRUD,
  ni de validation applicative. Le schéma seul est livré ; les ports/adapters de persistance et les
  règles applicatives arrivent avec les features M1→.
- **Pas d'implémentation de l'authentification** (hachage de mot de passe, JWT, OTP, anti-bruteforce →
  M1 #10/#11/#12). Le schéma se contente d'une colonne `password_hash` (jamais de mot de passe en
  clair) ; *aucun* secret n'est stocké ni journalisé.
- **Pas de seed de données métier** (hors éventuelles données de référence techniques si nécessaire) ;
  pas de données réelles ni de PII de test committées.
- **Pas de table d'audit/journalisation** dédiée (§11.4) : elle ne fait pas partie des 8 entités du
  §9 — à trancher hors de #3 (voir *Open Questions*).
- **Pas de mise en place de Redis**, du cache, des files de tâches, du stockage S3 ni des
  notifications réelles (ADR-0004/0005/0006) — hors périmètre.
- **Pas de CI exécutant les migrations** : le câblage CI (jobs, services Postgres) relève de **#4** ;
  l'injection des secrets de connexion réels relève de **#5**.

## Relevant Repository Context

- **Statut du dépôt** : greenfield outillé. Le socle (#1 ADR de stack, #2 arborescence) est posé ; #3
  est la première issue à **introduire de la persistance**.
- **Stack figée (ADR)** :
  - **Backend** : FastAPI · Python **≥ 3.12** (ADR-0003, `backend/pyproject.toml`).
  - **Base** : **PostgreSQL** principale + **Redis** cache/queue (ADR-0004). Versions pour mémo :
    PostgreSQL **16**, Redis **7** (README §4) — #3 fige PostgreSQL 16.
  - **Architecture** : **hexagonale / ports & adapters** (ADR-0008). Dépendance toujours vers
    l'intérieur ; **toute brique externe passe par un port + un adapter sortant** ; aucune importation
    directe d'un client d'infra depuis `domaine/` ou `application/`.
- **Arborescence backend actuelle** (`backend/coiflink_api/`) :
  - `domaine/` — entités & règles métier (zéro dépendance framework/I/O) ;
  - `application/` + `application/ports/` — cas d'usage et interfaces ;
  - `adapters/entrant/` — routers HTTP (ex. `sante.py` → `/health`) ;
  - `adapters/sortant/` — **driven** : Postgres/Redis/S3… (vide aujourd'hui) ;
  - `main.py` — composition root.
- **Conséquence architecturale directe pour #3** : les **tables ORM, la `metadata` SQLAlchemy et les
  migrations Alembic sont un détail de persistance** → ils vivent dans **`adapters/sortant/`**, pas
  dans `domaine/`. Les **enums métier** (rôles, statuts, modes de paiement…) sont des `enum.Enum`
  Python **purs** (sans dépendance framework) et peuvent donc vivre dans `domaine/` pour être
  partagés sans violer l'ADR-0008.
- **Décisions explicitement ouvertes que #3 doit trancher** (citées par les ADR) : ORM + outil de
  migrations (ADR-0003/0004), version PostgreSQL (ADR-0004), driver de connexion (sync/async).
- **Conventions** : code et configuration lus **depuis l'environnement** (jamais de secret en dur —
  `backend/main.py`, `.env.example`) ; commits *Conventional Commits* ; specs avec en-têtes anglais /
  contenu français ; **aucune signature IA** dans le code/commits/PR.
- **Tension à résoudre** : le §9.4 « Modèle de données *simplifié* » liste un champ unique
  `service_id` sur `Appointment`, alors que **§8.1 et les critères d'acceptation exigent « ≥ 1
  prestation »**. Le schéma doit honorer la règle métier (≥ 1), pas seulement le champ simplifié (voir
  *Proposed Implementation* et *Open Questions*).

## Proposed Implementation

### 1. Outillage (décision à figer dans #3)

- **ORM** : **SQLAlchemy 2.0** (style déclaratif typé `Mapped[...]`).
- **Migrations** : **Alembic**, migrations versionnées sous `backend/migrations/versions/`, env
  Alembic important la `metadata` du paquet de persistance (autogenerate possible mais la migration
  initiale est **revue/écrite à la main** pour porter les `CHECK`/`EXCLUDE` qu'Alembic n'autogénère
  pas).
- **Driver** : **psycopg 3** (`psycopg[binary]`), compatible sync (Alembic) et async (app FastAPI).
- **Dépendances ajoutées** à `backend/pyproject.toml` : `sqlalchemy>=2.0`, `alembic>=1.13`,
  `psycopg[binary]>=3.1`. Dépendances de test : un moyen de fournir un Postgres jetable (voir *Testing
  Plan*).
- **Source du DSN** : Alembic et l'app lisent **`DATABASE_URL`** depuis l'environnement
  (`backend/.env.example` le fournit déjà) ; `alembic.ini` ne contient **aucun** identifiant en dur.

### 2. Emplacement dans l'hexagone (ADR-0008)

```
backend/
  alembic.ini                       # config Alembic ; lit DATABASE_URL depuis l'env (aucun secret)
  migrations/
    env.py                          # importe metadata de l'adapter sortant ; configure le contexte
    script.py.mako
    versions/
      0001_schema_initial.py        # up(): crée extensions, enums, tables, contraintes, index
                                    # down(): supprime tout (réversible)
  coiflink_api/
    domaine/
      enums.py                      # Enums purs : Role, AppointmentStatus, PaymentMethod, ...
    adapters/sortant/persistance/
      __init__.py
      base.py                       # DeclarativeBase + metadata + convention de nommage des contraintes
      modeles.py                    # tables ORM (User, Salon, Service, Appointment, ...)
      session.py                    # fabrique d'engine/session lisant DATABASE_URL (optionnel ici)
```

> Périmètre minimal : `enums.py`, `base.py`, `modeles.py` (mapping ORM) et la **migration initiale**.
> Les **repository ports** (`application/ports/`) et leurs **adapters concrets** ne sont **pas** requis
> par #3 et sont laissés aux features M1→ (évite de sur-construire). `session.py` peut être livré comme
> simple fabrique d'engine non câblée à l'app.

### 3. Conventions de schéma

- **PK** : `id UUID PRIMARY KEY DEFAULT gen_random_uuid()` (fonction native PG ≥ 13, pas d'extension).
  *Décision UUID vs bigint à confirmer — voir Risks.*
- **Horodatage** : `created_at timestamptz NOT NULL DEFAULT now()` ; `updated_at timestamptz NOT NULL
  DEFAULT now()` (mise à jour applicative, ou trigger `moddatetime` optionnel).
- **Montants** : `NUMERIC(12,2)` (jamais de flottant) ; devise unique **XOF** (Franc CFA) — colonne
  `currency CHAR(3) NOT NULL DEFAULT 'XOF'` optionnelle pour l'évolutivité (à confirmer).
- **Enums** : représentés en **`text` + contrainte `CHECK`** nommée (plus simple à faire évoluer que
  les `ENUM` natifs PostgreSQL), les valeurs venant des `enum.Enum` du domaine. *Alternative : type
  `ENUM` natif — à confirmer.*
- **Convention de nommage des contraintes** (`base.py`) pour des migrations déterministes :
  `pk_%(table_name)s`, `fk_%(table_name)s_%(column_0_name)s`, `uq_…`, `ck_…`, `ix_…`.
- **FK composites pour l'intégrité multi-tenant** : lorsqu'une ligne référence une entité d'un même
  salon, utiliser une **FK composite `(salon_id, <ref_id>)`** vers une **clé unique `(salon_id, id)`**
  de la table cible, afin de garantir au niveau base que la prestation/le client d'un RDV
  **appartiennent au même salon** (renforce §11.2).
- **Politique de suppression** : `ON DELETE RESTRICT` par défaut (les salons/paiements ne se
  hard-delete pas ; on utilise des statuts). `CASCADE` réservé aux tables purement dépendantes
  (ex. lignes de jonction RDV↔prestation lors d'une suppression de RDV non validé).

### 4. Entités, clés et contraintes (résumé)

> Types indicatifs ; les noms de colonnes suivent le §9. Colonnes `id`/`created_at`/`updated_at`
> implicites selon les conventions ci-dessus.

| Entité | Colonnes clés (au-delà des standards) | Contraintes & index notables |
| --- | --- | --- |
| **`users`** | `full_name`, `phone`, `email NULL`, `password_hash`, `role`, `status` | `UNIQUE(phone)` ; `UNIQUE(email)` (partiel `WHERE email IS NOT NULL`) ; `CHECK role IN (CLIENT,HAIRDRESSER,MANAGER,ADMIN)` ; `CHECK status IN (...)` |
| **`salons`** | `owner_id→users`, `name`, `description`, `phone`, `address`, `city`, `commune`, `latitude`, `longitude`, `logo_url`, `status`, `opening_hours JSONB` | FK `owner_id` ; `CHECK status IN (ACTIVE,INACTIVE,...)` ; `UNIQUE(id, owner_id)`? ; **`UNIQUE(salon_id-cible)`** via `UNIQUE(id)` réutilisée par FK composites ; index sur `(city, commune)`, `status` |
| **`services`** | `salon_id→salons`, `name`, `description`, `price NUMERIC(12,2)`, `duration_minutes INT`, `category`, `is_active` | FK `salon_id` ; **`UNIQUE(salon_id, id)`** (cible des FK composites) ; `CHECK price >= 0` ; `CHECK duration_minutes > 0` ; index `salon_id` |
| **`appointments`** | `salon_id→salons`, `client_id→users`, `hairdresser_id→users NULL`, `appointment_date DATE`, `start_time TIME`, `end_time TIME`, `status`, `cancellation_reason NULL`, `client_note NULL` | FK `salon_id` `NOT NULL` (§8.1) ; **FK composite** `(salon_id, hairdresser_id)` cohérence salon ; `CHECK end_time > start_time` ; `CHECK status IN (PENDING,CONFIRMED,CANCELLED,COMPLETED,NO_SHOW)` ; **EXCLUDE** anti double-booking (voir §5) ; **≥ 1 prestation** via `appointment_services` (voir §5) ; index `(salon_id, appointment_date)`, `client_id` |
| **`appointment_services`** *(table de jonction — voir Open Questions)* | `appointment_id→appointments`, `service_id→services`, `price_at_booking NUMERIC(12,2)` | PK `(appointment_id, service_id)` ; FK composite `(salon_id, service_id)` cohérence salon ; `ON DELETE CASCADE` depuis `appointments` ; garantit le rattachement RDV↔prestation |
| **`customer_profiles`** | `salon_id→salons`, `user_id→users NULL`, `full_name`, `phone`, `notes NULL`, `last_visit_at NULL`, `total_visits INT DEFAULT 0` | FK `salon_id` ; `user_id` **nullable** (clients « walk-in » sans compte) ; `UNIQUE(salon_id, user_id) WHERE user_id IS NOT NULL` ; index `salon_id` |
| **`payments`** | `salon_id→salons`, `appointment_id→appointments NULL`, `client_id→users NULL`, `amount NUMERIC(12,2)`, `payment_method`, `status`, `recorded_by→users`, `reference NULL` | FK `salon_id`, `recorded_by` `NOT NULL` (§8.2) ; **`CHECK (appointment_id IS NOT NULL OR <ref prestation> IS NOT NULL)`** (§8.2) ; `CHECK amount >= 0` ; `CHECK payment_method IN (CASH,MOBILE_MONEY_MANUAL,CARD_MANUAL,OTHER)` ; `CHECK status IN (PENDING,VALIDATED,CANCELLED,ADJUSTED)` ; index `(salon_id, created_at)`, `appointment_id` |
| **`cash_journal`** | `salon_id→salons`, `transaction_id→payments NULL`, `operation_type`, `amount NUMERIC(12,2)`, `performed_by→users`, `description NULL` | FK `salon_id`, `performed_by` `NOT NULL` ; `created_at NOT NULL` (horodatage §8.2) ; `CHECK operation_type IN (PAYMENT,REFUND,ADJUSTMENT,CASH_OPENING,CASH_CLOSING)` ; **append-only** (voir §5) ; index `(salon_id, created_at)` |
| **`notifications`** | `user_id→users NULL`, `salon_id→salons NULL`, `appointment_id→appointments NULL`, `type`, `channel`, `title`, `message`, `status`, `sent_at NULL` | `CHECK channel IN (PUSH,SMS,EMAIL,WHATSAPP,IN_APP)` ; `CHECK status IN (...)` ; index `user_id`, `(salon_id, created_at)` |

### 5. Contraintes clés métier (au cœur de l'acceptation #3)

1. **RDV lié à un salon + ≥ 1 prestation (§8.1)** — approche **recommandée** : table de jonction
   `appointment_services` (many-to-many), qui honore « **au moins une** prestation » et le futur
   « plusieurs prestations par RDV ». La cardinalité « ≥ 1 » ne se garantit pas par une simple FK ;
   l'implémenter par **insertion transactionnelle** (RDV + ≥ 1 ligne de jonction dans la même
   transaction) côté applicatif (M3) **et** documenter la règle. Option de durcissement base : une
   **contrainte différée** ou un **trigger `AFTER` `DEFERRABLE INITIALLY DEFERRED`** vérifiant la
   présence d'au moins une ligne en fin de transaction. *Décision à confirmer (voir Open Questions).*
   - Variante minimale conforme au §9.4 littéral : conserver un `service_id NOT NULL` unique sur
     `appointments` (garantit « exactement 1 », donc « ≥ 1 ») — plus simple mais ferme la porte au
     multi-prestation. **Non recommandée** au vu de §8.1.
2. **Paiement lié à une prestation/RDV (§8.2)** — `CHECK` garantissant qu'au moins une référence est
   présente. Le §9.6 ne porte que `appointment_id` (pas de `service_id` direct) ; recommandation :
   `CHECK (appointment_id IS NOT NULL)` au minimum, **ou** ajouter une référence prestation optionnelle
   et un `CHECK (appointment_id IS NOT NULL OR service_id IS NOT NULL)`. *Décision à confirmer.*
3. **Anti double-réservation d'un coiffeur (§8.1)** — colonne **générée**
   `slot tstzrange` (ou `tsrange` — fuseau d'Abidjan = UTC+0) à partir de
   `appointment_date + start_time/end_time`, puis **contrainte d'exclusion** :
   `EXCLUDE USING gist (hairdresser_id WITH =, slot WITH &&) WHERE (hairdresser_id IS NOT NULL AND
   status IN ('PENDING','CONFIRMED'))`. Nécessite l'**extension `btree_gist`**
   (`CREATE EXTENSION IF NOT EXISTS btree_gist` dans la migration). Les RDV `CANCELLED`/`NO_SHOW` sont
   exclus du conflit. *La forme exacte (chevauchement vs créneau strict) peut être affinée en M3 ;
   #3 pose le socle.*
4. **Journal de caisse horodaté & append-only (§8.2)** — `created_at NOT NULL DEFAULT now()` ;
   conception **immuable** : pas de `DELETE`/`UPDATE` des lignes (corrections via nouvelle ligne
   `ADJUSTMENT`/`REFUND`). L'append-only stricte peut être renforcée par un **trigger `BEFORE
   UPDATE/DELETE`** levant une erreur, ou par des **privilèges de rôle** (révoquer UPDATE/DELETE) — à
   documenter ; #3 fournit a minima le modèle qui le permet.
5. **Pas de suppression d'un paiement validé (§8.2)** — FK `ON DELETE RESTRICT` + statut `CANCELLED`/
   `ADJUSTED` au lieu d'un hard-delete ; règle renforcée côté application (M4).

### 6. Migration initiale

`migrations/versions/0001_schema_initial.py` :
- `upgrade()` : `CREATE EXTENSION IF NOT EXISTS btree_gist` → création des contraintes `CHECK` d'enums
  (ou types `ENUM`) → tables dans l'ordre des dépendances FK → contraintes composites, `EXCLUDE`,
  index → éventuels triggers.
- `downgrade()` : suppression dans l'ordre inverse (drop tables, types/extensions si créés par cette
  migration), de sorte que `alembic downgrade base` ramène à un schéma vide **sans erreur**.

## Affected Files / Packages / Modules

**À créer :**
- `backend/alembic.ini` — configuration Alembic (DSN lu via env, aucun secret).
- `backend/migrations/env.py`, `backend/migrations/script.py.mako`,
  `backend/migrations/versions/0001_schema_initial.py`.
- `backend/coiflink_api/domaine/enums.py` — enums métier purs.
- `backend/coiflink_api/adapters/sortant/persistance/__init__.py`, `base.py`, `modeles.py`,
  (optionnel) `session.py`.

**À modifier :**
- `backend/pyproject.toml` — ajouter `sqlalchemy`, `alembic`, `psycopg[binary]` (+ deps de test).
- `backend/README.md` — section « Modèle de données & migrations » : dictionnaire des tables, ERD,
  commandes `alembic upgrade/downgrade`, prérequis Postgres.
- `backend/.env.example` — préciser que `DATABASE_URL` pilote aussi Alembic (la clé existe déjà).
- `docs/adr/` — **ADR-0009** (recommandé) : décision « ORM = SQLAlchemy 2.0 + migrations = Alembic +
  driver psycopg 3 », fermant le « Suivi » d'ADR-0003/0004 ; mettre à jour `docs/adr/README.md`.
- `backend/tests/` — nouveaux tests (voir *Testing Plan*).

**À lire (contexte) :** `prd-coiflink.md` (§8, §9, §11, §12), `docs/adr/0003`, `0004`, `0008`,
`backend/coiflink_api/main.py`, `backend/coiflink_api/adapters/entrant/sante.py`.

## API / Interface Changes

**Interface CLI (nouvelle, outillage développeur) :** commandes Alembic exécutées depuis `backend/` —
`alembic upgrade head`, `alembic downgrade base`, `alembic revision --autogenerate -m "..."`,
`alembic current/history`. À documenter dans `backend/README.md`.

**API réseau / endpoints HTTP : none.** #3 n'ajoute aucun endpoint ni schéma de requête/réponse
public (les API métier arrivent en M1→). L'endpoint `/health` reste inchangé.

## Data Model / Protocol Changes

**Oui — c'est l'objet de l'issue.** Création du schéma relationnel initial PostgreSQL (8 entités du §9
+ table de jonction `appointment_services`), des enums, des contraintes d'intégrité (FK, `UNIQUE`,
`CHECK`, `EXCLUDE` anti double-booking), des index, et de la **migration versionnée up/down**. Détail
complet en *Proposed Implementation §4–§6*. Aucune autre couche de sérialisation n'est introduite (pas
de schémas Pydantic d'API dans #3).

## Security & Privacy Considerations

- **PII (§11.3)** : `users` (`full_name`, `phone`, `email`) et `customer_profiles` (`full_name`,
  `phone`, `notes`) contiennent des données personnelles. **Ne jamais journaliser** ces colonnes ni les
  valeurs de migration ; les logs Alembic ne doivent pas dumper de données. **Collecte minimale** :
  s'en tenir aux colonnes du §9.
- **Mots de passe** : colonne `password_hash` uniquement — **jamais de mot de passe en clair**, jamais
  loggé. Le hachage (argon2/bcrypt) est implémenté en M1 (ADR-0003) ; #3 ne stocke que le condensat.
- **Secrets / DSN** : `DATABASE_URL` et tout identifiant de connexion sont lus **depuis
  l'environnement** ; `alembic.ini` et le code **ne contiennent aucun secret** ; aucune valeur réelle
  committée (seulement `.env.example`). L'injection des secrets réels relève de **#5**.
- **Isolation par salon (§11.2)** : `salon_id` sur chaque table à portée salon + **FK composites
  `(salon_id, …)`** pour empêcher au niveau base qu'une ligne référence une entité d'un autre salon —
  socle du RBAC strict des features M1.
- **Désactivation de compte (§11.3)** : colonne `status` sur `users` (et `salons`) permet la
  désactivation **logique** (pas de hard-delete) ; les valeurs d'enum de statut sont à figer.
- **Intégrité financière (§8.2)** : `EXCLUDE`/`CHECK`/`RESTRICT` + journal append-only protègent contre
  la perte/altération silencieuse de paiements.
- **Chiffrement au repos (§11.3, « si nécessaire »)** : non requis explicitement ; le chiffrement
  colonne est laissé en option (voir *Open Questions*). Le chiffrement disque/sauvegardes relève de
  l'hébergement (#5).
- **Résidence / hébergement / budgets latence** : aucune contrainte de résidence documentée ; budgets
  perf §12 (API < 3 s, recherche salon < 2 s) **guident les index** (city/commune, salon_id, dates).

## Testing Plan

- **Test gate** : `pytest` (ADR-0003 ; câblage agrégé `MX_AGENT_TEST_CMD` en #6). Les tests existants
  (`tests/test_health.py`) doivent rester verts.
- **Tests d'invariants de schéma (sans base, rapides)** : vérifier que la `metadata` SQLAlchemy déclare
  les 8 tables + la jonction, que les colonnes/PK/FK/`CHECK` attendus existent, et que la convention de
  nommage des contraintes est appliquée. Vérifier la cohérence enums Python ↔ valeurs `CHECK`.
- **Tests de migration round-trip (intégration, Postgres requis)** : sur un **PostgreSQL 16 jetable**,
  exécuter `alembic upgrade head` puis `alembic downgrade base` et revérifier `upgrade head` (idempotence
  / réversibilité). Vérifier la présence effective des contraintes (interrogation du catalogue
  `pg_constraint`). *Fournir le Postgres via testcontainers, un service container CI (#4), ou un DSN
  local ; ces tests doivent se **skip proprement** si aucun Postgres n'est disponible, pour ne pas
  casser le gate tant que #4 n'a pas câblé le service.* — **décision d'outillage à confirmer.**
- **Tests de contraintes métier (intégration, Postgres requis)** :
  - un RDV **sans** prestation est rejeté / un RDV avec ≥ 1 prestation est accepté (§8.1) ;
  - un paiement **sans** `appointment_id` (ni référence prestation) est rejeté (`CHECK`, §8.2) ;
  - deux RDV chevauchants pour le **même** coiffeur (statuts actifs) sont rejetés par l'`EXCLUDE` ;
    deux RDV chevauchants `CANCELLED` sont acceptés ;
  - une prestation d'un autre salon ne peut pas être rattachée à un RDV (FK composite) ;
  - `phone` dupliqué refusé sur `users` (préfigure #8).
- **Documentation** : vérifier que `backend/README.md` documente les commandes de migration et que
  l'ERD/dictionnaire est présent (revue, pas test automatisé).

> Note : tant que #4 (CI + service Postgres) et #5 (secrets) ne sont pas livrés, les tests
> Postgres-dépendants sont **conditionnels** (skip si pas de DSN). Le flag « migrations exécutables »
> de l'acceptation est démontrable **localement** et documenté.

## Documentation Updates

- **`backend/README.md`** : nouvelle section « Modèle de données & migrations » — diagramme relationnel
  (ERD, p. ex. Mermaid), **dictionnaire des tables/colonnes/contraintes**, commandes Alembic, prérequis
  PostgreSQL 16, rappel « DSN via env, aucun secret committé ». (Critère d'acceptation « schéma
  documenté ».)
- **`docs/adr/0009-orm-migrations-sqlalchemy-alembic.md`** (recommandé) : acter ORM + outil de
  migrations + driver + version PostgreSQL, en clôturant le « Suivi » d'ADR-0003/0004 ; ajouter l'entrée
  dans **`docs/adr/README.md`**.
- **`backend/.env.example`** : préciser que `DATABASE_URL` sert aussi à Alembic (sans secret).
- **README racine** : §4 — confirmer PostgreSQL 16 comme version figée (retirer le « pour mémo / à
  arrêter en #2/#3 » une fois tranché) ; mention que #3 livre le schéma.
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit). La divergence §9.4
  (`service_id` unique) vs §8.1 (« ≥ 1 prestation ») est tracée ici et dans l'ADR, pas par réécriture du
  PRD.

## Risks and Open Questions

- **§9.4 `service_id` unique vs §8.1 « ≥ 1 prestation »** *(à confirmer — recommandation : table de
  jonction `appointment_services`)*. Décision structurante : jonction many-to-many (évolutif,
  multi-prestation) **ou** `service_id` unique `NOT NULL` (littéral §9.4, plus simple). La jonction est
  recommandée car alignée sur §8.1 ; impact sur les requêtes de CA et le calcul de durée.
- **Garantie « ≥ 1 » au niveau base** : une FK seule ne l'impose pas. Options : invariant transactionnel
  applicatif (simple, recommandé pour #3) ; contrainte différée/trigger (plus strict, plus complexe).
  *À confirmer.*
- **ORM + migrations + driver** : SQLAlchemy 2.0 + Alembic + psycopg 3 sont **recommandés** (standard
  FastAPI) mais relèvent d'une **décision à acter** (SQLModel est une alternative). À figer via ADR-0009.
- **Type des clés primaires** : **UUID** (`gen_random_uuid()`, anti-énumération, pratique côté mobile)
  vs **bigint identity** (compact, séquentiel). *À confirmer.* Impact sur tous les FK et index.
- **Représentation des enums** : `text` + `CHECK` (évolutif, recommandé) vs `ENUM` PG natif (typé mais
  `ALTER TYPE` contraignant). *À confirmer.*
- **Paiement ↔ prestation** : §9.6 n'a pas de `service_id` direct ; faut-il en ajouter un (et un `CHECK`
  « appointment OU service ») ou se contenter de `appointment_id NOT NULL` ? *À confirmer.*
- **Anti double-booking** : forme exacte (chevauchement `EXCLUDE`/`btree_gist` vs unicité de créneau
  strict), statuts inclus, gestion des coiffeurs non assignés (`hairdresser_id NULL`). `btree_gist`
  exige un privilège `CREATE EXTENSION` (peut manquer sur Postgres managé restreint — vérifier en #5).
  Le raffinement complet peut glisser en **M3 (#21+)** ; #3 pose le socle.
- **Fuseau horaire / type temporel** : Abidjan = **UTC+0** ; choisir `tstzrange` vs `tsrange` et
  `timestamptz` vs `date`+`time`. Cohérence à figer pour éviter des bugs de créneaux.
- **Devise** : XOF (sans sous-unité usuelle) — `NUMERIC(12,2)` suffit ; colonne `currency` optionnelle
  pour l'évolutivité. *À confirmer.*
- **Table d'audit (§11.4)** : hors des 8 entités du §9. L'inclure dès #3 ou la différer (issue dédiée
  M6) ? *Recommandation : différer* — hors périmètre #3.
- **Tests Postgres en l'absence de CI (#4) / secrets (#5)** : comment exécuter les tests d'intégration
  de manière fiable et reproductible (testcontainers vs service container vs skip conditionnel). *À
  confirmer ; recommandation : skip conditionnel sur absence de DSN pour ne pas bloquer le gate.*
- **Triggers `updated_at` / append-only** : utiliser des triggers PostgreSQL (couplage base) ou gérer
  côté application (cohérent avec l'esprit hexagonal) ? *À confirmer ; #3 peut s'en tenir aux défauts +
  documentation.*

## Implementation Checklist

1. **Acter l'outillage** : rédiger `docs/adr/0009-orm-migrations-sqlalchemy-alembic.md` (ORM, migrations,
   driver, PostgreSQL 16) et l'indexer dans `docs/adr/README.md`. Trancher au passage les *Open
   Questions* structurantes (jonction vs `service_id`, type de PK, représentation des enums).
2. **Dépendances** : ajouter `sqlalchemy>=2.0`, `alembic>=1.13`, `psycopg[binary]>=3.1` à
   `backend/pyproject.toml` (+ deps de test pour le Postgres jetable). Vérifier `pip install -e ".[dev]"`.
3. **Enums du domaine** : créer `coiflink_api/domaine/enums.py` (`Role`, `UserStatus`, `SalonStatus`,
   `AppointmentStatus`, `PaymentMethod`, `PaymentStatus`, `CashOperationType`, `NotificationChannel`,
   `NotificationStatus`, `NotificationType`) — `enum.Enum` purs, aucune dépendance framework.
4. **Base ORM** : créer `adapters/sortant/persistance/base.py` (`DeclarativeBase`, `metadata`,
   convention de nommage des contraintes).
5. **Modèles ORM** : créer `adapters/sortant/persistance/modeles.py` avec les 8 tables + la jonction
   `appointment_services`, colonnes/types du §9, FK (dont **FK composites** `(salon_id, …)`), `UNIQUE`,
   `CHECK` d'enums et de bornes (montants ≥ 0, `end_time > start_time`, `duration_minutes > 0`).
6. **Contraintes métier** : ajouter le `CHECK` paiement↔(RDV/prestation) (§8.2), la colonne générée
   `slot` + l'`EXCLUDE` anti double-booking (§8.1), et documenter l'invariant « RDV → ≥ 1 prestation ».
7. **Alembic** : initialiser `alembic.ini` (DSN via `DATABASE_URL`, aucun secret) + `migrations/env.py`
   important la `metadata`.
8. **Migration initiale** : écrire `0001_schema_initial.py` — `upgrade()` (extension `btree_gist`,
   enums/CHECK, tables, contraintes composites, `EXCLUDE`, index, triggers éventuels) et `downgrade()`
   (réversion complète vers schéma vide).
9. **Vérifier le round-trip** localement sur PostgreSQL 16 : `alembic upgrade head` → `alembic downgrade
   base` → `alembic upgrade head`, sans erreur ; contrôler `pg_constraint`.
10. **Tests** : ajouter `tests/test_schema_metadata.py` (invariants sans base) et
    `tests/test_migrations_postgres.py` (round-trip + contraintes métier, **skip si pas de DSN**).
    Garantir que `tests/test_health.py` reste vert.
11. **Documentation** : section « Modèle de données & migrations » dans `backend/README.md` (ERD +
    dictionnaire + commandes Alembic + prérequis), mise à jour `backend/.env.example` et README racine
    (PostgreSQL 16 figé).
12. **Garde-fous** : confirmer qu'**aucun secret/PII** n'est committé (uniquement `.env.example`), que
    `alembic.ini` lit le DSN depuis l'env, et qu'aucune signature IA n'est présente dans le code/commits.
13. **Sanity** : `pytest` vert (tests sans base au minimum ; tests Postgres exécutés si DSN dispo) ;
    `pip install -e .` OK.
