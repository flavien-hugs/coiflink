# ADR-0009 : ORM, migrations & driver — SQLAlchemy 2.0 + Alembic + psycopg 3

- **Statut** : Accepté
- **Date** : 2026-06-30
- **Décideurs** : équipe CoifLink
- **Issue** : #3
- **Référence PRD** : §9 (modèle de données), §8.1/§8.2 (règles métier), §11.2/§11.3
  (isolation par salon, données personnelles), §12.1 (performance)

## Contexte et problème

L'**ADR-0003** (FastAPI) et l'**ADR-0004** (PostgreSQL) ont figé la stack mais ont
**explicitement renvoyé à l'issue #3** le choix de l'**ORM**, de l'**outil de
migrations**, du **driver de connexion** et de la **version de référence
PostgreSQL** (voir le « Suivi » de ces deux ADR). Avant d'introduire la moindre
table, il faut acter ces briques afin que le schéma des 8 entités du §9 et ses
contraintes critiques (anti double-réservation §8.1, paiement lié à un RDV /
prestation §8.2) reposent sur un outillage stable, versionné et reproductible.

FastAPI n'impose aucun ORM (contrairement à Django) : c'est précisément le
**coût de câblage** accepté par l'ADR-0003 qu'il faut payer ici.

## Options envisagées

- **Option A — SQLAlchemy 2.0 + Alembic + psycopg 3.** Standard de fait de
  l'écosystème FastAPI. SQLAlchemy 2.0 offre un style déclaratif typé
  (`Mapped[...]`), un support complet des contraintes PostgreSQL avancées
  (`CHECK`, `EXCLUDE`, colonnes générées, index partiels) et Alembic gère les
  migrations versionnées up/down. psycopg 3 est le driver moderne (sync + async).
- **Option B — SQLModel (+ Alembic).** Couche fine au-dessus de SQLAlchemy +
  Pydantic, ergonomique pour FastAPI. Mais elle masque une partie de l'API
  SQLAlchemy nécessaire aux contraintes avancées du §8 (EXCLUDE, FK composites,
  colonnes générées) et reste moins mature pour ces cas.
- **Option C — ORM Django / Tortoise / Peewee.** Écartées : Django impose son
  framework (en contradiction avec l'ADR-0003) ; les ORM async « légers » sont
  moins outillés pour les migrations et les contraintes d'intégrité fortes.

## Décision

La persistance backend repose sur :

- **ORM** : **SQLAlchemy 2.0** (style déclaratif typé `Mapped[...]`).
- **Migrations** : **Alembic** (migrations versionnées sous
  `backend/migrations/versions/`, migration initiale **écrite à la main**).
- **Driver** : **psycopg 3** (`psycopg[binary]`), compatible sync (Alembic) et
  async (application FastAPI à venir).
- **Version de référence** : **PostgreSQL 16** (figée ici, confirmant le « pour
  mémo » du README §4 et de l'ADR-0004).

Décisions de modélisation tranchées au passage (Open Questions de la spec #3) :

- **Clés primaires** : `UUID` avec défaut serveur `gen_random_uuid()` (fonction
  native PG ≥ 13, anti-énumération, pratique côté mobile).
- **Énumérations** : stockées en `text` + contrainte `CHECK` *dérivée des
  `enum.Enum` du domaine* (`coiflink_api/domaine/enums.py`) — évolutif sans
  `ALTER TYPE`, et impossible à désynchroniser du domaine.
- **RDV ↔ prestations** : **table de jonction** `appointment_services`
  (many-to-many), pour honorer le « **≥ 1 prestation** » du §8.1 et le futur
  multi-prestation — plutôt que le `service_id` unique du §9.4 (divergence PRD
  tracée ici, **sans réécrire le PRD**).
- **Paiement ↔ prestation/RDV** : ajout d'un `service_id` optionnel à `payments`
  et `CHECK (appointment_id IS NOT NULL OR service_id IS NOT NULL)` (§8.2).
- **Anti double-réservation** : colonne générée `slot tsrange` (Abidjan = UTC+0)
  + contrainte `EXCLUDE USING gist` (extension `btree_gist`), restreinte aux RDV
  actifs (`PENDING`/`CONFIRMED`) et assignés à un coiffeur (§8.1).
- **Isolation par salon** (§11.2) : `salon_id` indexé sur chaque table à portée
  salon + **FK composites `(salon_id, …)`** interdisant au niveau base de
  rattacher une entité d'un autre salon.

## Justification (compromis)

- **Maturité & contraintes avancées** : SQLAlchemy 2.0 exprime nativement les
  contraintes `CHECK`/`EXCLUDE`, les FK composites, les colonnes générées et les
  index partiels exigés par les règles métier §8 — ce que SQLModel n'expose pas
  aussi directement.
- **Migrations reproductibles** : Alembic fournit des migrations up/down
  versionnées ; une **convention de nommage** des contraintes garantit des noms
  déterministes et des diff stables.
- **Driver moderne** : psycopg 3 couvre le sync (utilisé par Alembic) et l'async
  (futur câblage FastAPI), évitant un second driver.
- **Hexagonal (ADR-0008)** : ORM, `metadata` et migrations vivent dans
  `adapters/sortant/persistance/` ; les `enum.Enum` du domaine restent purs. Le
  domaine n'importe jamais SQLAlchemy.
- **Compromis accepté** : SQLAlchemy 2.0 est plus verbeux que SQLModel ;
  ce coût est assumé au profit du contrôle fin des contraintes d'intégrité, qui
  sont au cœur de la valeur métier (caisse, anti double-booking).

## Conséquences

- **Positives** : schéma initial complet et versionné, contraintes critiques
  portées au niveau base, round-trip `upgrade`/`downgrade` réversible, base
  saine pour les repository ports/adapters des features M1→.
- **Négatives / risques** :
  - `btree_gist` requiert le privilège `CREATE EXTENSION` — à vérifier sur un
    PostgreSQL managé restreint lors de l'hébergement (#5) ;
  - la cardinalité « ≥ 1 prestation » par RDV n'est pas imposée par une simple
    FK : elle est garantie par **insertion transactionnelle** côté application
    (M3) ; un durcissement base (contrainte différée / trigger) reste optionnel ;
  - l'append-only du journal de caisse est porté par la **conception** (pas de
    `DELETE`/`UPDATE`, corrections via `ADJUSTMENT`/`REFUND`) ; le verrouillage
    strict (trigger ou révocation de privilèges) est laissé à M4.
- **Clôture du « Suivi »** : cet ADR ferme les points « ORM + outil de
  migrations » d'**ADR-0003** et **ADR-0004**, et fige la version PostgreSQL 16.
- **Suivi / à confirmer (non bloquant)** :
  - exécution des migrations en CI + service Postgres → **#4** ;
  - injection des secrets de connexion réels → **#5** ;
  - éventuel câblage async (engine/session FastAPI) et repository adapters → M1→.
