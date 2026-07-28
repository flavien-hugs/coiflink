# Journal de caisse horodaté (gérant) (US-5.3)

> Spécification de planification pour l'issue GitHub **#34 — US-5.3 : Journal de caisse horodaté**
> (`feature` `security` `payments` · **Must** · Effort **M** · PRD §6 Épic 5 / §5.3 « Parcours
> encaissement » / §8.2 « Encaissement » / §11.4 « Journalisation »). **Dépend de #33** (US-5.1 —
> enregistrement d'un paiement). **Cette spec ne produit pas de code** : elle décrit l'approche à
> implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 5, US-5.3) pose le besoin : **« en tant que gérant, je veux avoir un journal de caisse
pour contrôler les entrées »**, avec pour spécification fonctionnelle « journal horodaté, utilisateur
ayant enregistré l'opération ». Le critère d'acceptation de l'issue #34 est :

- **Chaque paiement apparaît horodaté + auteur ; suppression interdite ; correction = ligne
  d'ajustement.**

Ces exigences sont des **règles métier explicites** du PRD §8.2 (« Encaissement ») :

- « Un paiement validé ne peut pas être supprimé définitivement. »
- « Toute correction de paiement doit créer une opération d'ajustement. »
- « Le journal de caisse doit être horodaté. »

et de §11.4 (« Journalisation »), qui liste **« Paiement enregistré »** et **« Correction de caisse »**
parmi les actions à journaliser.

### État actuel du dépôt (vérifié pour cette spec)

**Le schéma existe déjà, mais aucun code métier ne le touche.** La migration initiale `0001`
(PostgreSQL 16) et les modèles ORM matérialisent **déjà** les tables `payments` et `cash_journal`
ainsi que les énumérations associées :

- **`payments`** (`models.Payment`, PRD §9.6) : `id`, `salon_id`, `appointment_id?`, `service_id?`,
  `client_id?`, `amount NUMERIC(12,2)`, `currency` (défaut `'XOF'`), `payment_method`, `status` (défaut
  `PENDING`), **`recorded_by` (utilisateur responsable, NOT NULL — PRD §8.2)**, `reference?`,
  `created_at`. Contraintes : `CHECK amount >= 0`, `CHECK (appointment_id IS NOT NULL OR service_id IS
  NOT NULL)` (§8.2 « lié à une prestation OU un RDV »), `enum_check(payment_method)`, `enum_check(status)`,
  `UNIQUE(salon_id, id)` (cible de la FK composite du journal), FK `RESTRICT` vers salon/RDV/prestation/
  client/utilisateur, index `(salon_id, created_at)` et `(appointment_id)`.
- **`cash_journal`** (`models.CashJournal`, PRD §9.7) — décrit dans sa docstring comme **« horodaté et
  append-only »** : `id`, `salon_id`, `transaction_id?` (FK composite `(salon_id, transaction_id) →
  payments(salon_id, id)`, `RESTRICT`), `operation_type`, `amount NUMERIC(12,2)`, **`performed_by`
  (auteur de l'opération, NOT NULL)**, `description?`, `created_at`. `enum_check(operation_type)`, index
  `(salon_id, created_at)`. La docstring dit explicitement : *« Aucune ligne n'est supprimée ni
  modifiée : une correction crée une nouvelle opération `ADJUSTMENT`/`REFUND`. L'immuabilité stricte
  sera renforcée côté application (M4) et, si retenu, par révocation des privilèges UPDATE/DELETE. »*
- **Énumérations** (`domain/enums.py`) : `PaymentMethod` (`CASH`, `MOBILE_MONEY_MANUAL`, `CARD_MANUAL`,
  `OTHER`), `PaymentStatus` (`PENDING`, `VALIDATED`, `CANCELLED`, **`ADJUSTED`**), `CashOperationType`
  (`PAYMENT`, `REFUND`, **`ADJUSTMENT`**, `CASH_OPENING`, `CASH_CLOSING`).
- **Permissions** (`domain/permissions.py`, §4.1) : **`PAYMENT_RECORD`** et **`CASH_JOURNAL_READ`**
  existent déjà et sont **attribuées au seul `MANAGER`** dans `ROLE_PERMISSIONS` (lignes 118-119). Elles
  ne sont câblées sur **aucune route** à ce jour.

**Aucune tranche verticale « encaissement » n'existe encore** : pas de `domain/payment.py`, pas
d'`application/payments.py` ni de `application/cash_journal.py`, pas de port de dépôt paiement/caisse,
pas d'`adapters/inbound/payments.py`, pas de `SqlPaymentRepository`. Côté web, la section
**« Encaissements »** (`/gerant/encaissements`, `src/domain/navigation/sections.ts`) est en
**`coming-soon`**. Aucune `AuditAction` de caisse n'est déclarée (`domain/audit.py` s'arrête à
`CUSTOMER_NOTE_UPDATED`, #32).

**#33 (US-5.1 — enregistrement d'un paiement) n'est pas encore livré** au moment de rédiger cette spec
(le README §6 indique « L'encaissement (#33+) reste à venir »). #34 en **dépend** : la présente spec
suppose que #33 aura livré la tranche verticale d'**enregistrement d'un paiement** (au minimum : cas
d'usage de création d'un `Payment`, `SqlPaymentRepository`, router `payments`, section web
« Encaissements » passée à `available`). Le **partage exact des responsabilités** entre #33 et #34
(qui écrit la ligne `PAYMENT` du journal ? qui valide le paiement ?) est une **question ouverte à
trancher** — voir *Risks and Open Questions*. Cette spec est écrite pour être robuste dans les deux
hypothèses et **ne réimplémente pas #33**.

### Le gap que #34 comble

Sur la base de #33, #34 rend le **journal de caisse observable et incorruptible** :

1. **Chaque paiement apparaît horodaté + auteur** — une **route de lecture** du journal
   (`CASH_JOURNAL_READ`) expose les opérations d'un salon avec `created_at` (horodatage) et l'auteur
   (`performed_by` / `recorded_by`), triées, dans le fuseau `Africa/Abidjan` (convention #21).
2. **Suppression interdite** — aucune route `DELETE`/`PUT`/`PATCH` sur `payments` ni `cash_journal` ;
   invariant **append-only** garanti côté application (et, en option, durci en base). L'invariant est
   vérifié par des tests.
3. **Correction = ligne d'ajustement** — une **route de correction** crée une nouvelle opération
   `ADJUSTMENT` (delta signé) rattachée à la transaction d'origine, **sans jamais supprimer ni écraser**
   le paiement validé, et **journalise** la correction (§11.4 « Correction de caisse »).

## Goals

- **Journal horodaté et authentifié en lecture.** Nouvel endpoint **`GET /salons/{salon_id}/cash-journal`**
  (permission `CASH_JOURNAL_READ` + portée salon `require_salon_scope`) listant les opérations du salon
  du plus récent au plus ancien, chacune portant **`created_at` (horodatage)** et **l'auteur** de
  l'opération (`performed_by`, avec son nom d'affichage résolu), le `operation_type`, le montant signé,
  la devise, un lien vers la transaction (`transaction_id`) et une description. Pagination cohérente avec
  les routes existantes (`limit`/`offset`, cf. `customers`).
- **Invariant append-only du journal (§8.2), en profondeur.** **Aucune** route ne supprime ni ne modifie
  une ligne `cash_journal`, ni ne supprime un `payments` **validé**. L'API ne fournit **aucun** verbe
  `DELETE` sur ces ressources. L'écriture est **exclusivement** un `INSERT` (append). Un test de sécurité
  vérifie qu'aucune route destructive n'est exposée.
- **Correction par opération d'ajustement (§8.2).** Nouvel endpoint **`POST
  /salons/{salon_id}/payments/{payment_id}/adjustments`** (permission `PAYMENT_RECORD` + portée salon)
  qui : (a) **n'efface pas** et **ne réécrit pas** le paiement d'origine ; (b) **insère** une ligne
  `cash_journal` de type `ADJUSTMENT` avec le **delta** (montant signé = correction), `performed_by =
  acteur`, `description` = motif, `transaction_id` = paiement d'origine ; (c) marque le paiement
  d'origine `status = ADJUSTED` (mutation de **statut**, jamais une suppression — voir *Open Questions*) ;
  (d) **journalise** la correction §11.4.
- **Ligne `PAYMENT` du journal présente pour chaque paiement.** Chaque paiement validé possède **une**
  opération `PAYMENT` correspondante au journal (montant positif, `performed_by = recorded_by`,
  `transaction_id = payment.id`). Selon le partage #33/#34 retenu, cette écriture est faite par le flux
  d'enregistrement (#33) via le **même port** que #34, ou câblée par #34 (voir *Open Questions* §1). Dans
  tous les cas, #34 **fournit et possède** le port/adapter d'écriture du journal.
- **Horodatage fiable et cohérent.** `created_at` est **généré par le serveur** (défaut ORM
  `_created_at()`, `timezone-aware`), jamais fourni par le client ; l'affichage web utilise le fuseau
  `Africa/Abidjan` (UTC+0) comme les autres surfaces (#21).
- **Auteur toujours renseigné (§8.2).** `performed_by` (journal) et `recorded_by` (paiement) sont
  **obligatoires** (NOT NULL au schéma) et **toujours** dérivés du `Principal` authentifié
  (`principal.id`), **jamais** lus du corps de requête.
- **Réutilise les permissions §4.1 sans les élargir.** `CASH_JOURNAL_READ` (lecture) et `PAYMENT_RECORD`
  (écriture d'ajustement) existent déjà et sont détenues par le **seul `MANAGER`**. `ROLE_PERMISSIONS`
  **n'est pas modifiée**.
- **Isolation par salon (§11.2), en profondeur.** Routes imbriquées sous `/salons/{salon_id}/…` (héritent
  de `require_salon_scope`) **et** dépôt refiltrant systématiquement sur `salon_id` (et `(salon_id, id)`
  pour la FK composite). Un accès inter-salons renvoie le **`403` générique et constant** ; une
  transaction d'un autre salon est **indiscernable d'une transaction inexistante** (`404` **après**
  validation de portée). Aucun oracle.
- **Correction journalisée (§11.4), sans PII.** Chaque correction enregistre une `AuditEntry` **neutre**
  (nouvelle action `CASH_ADJUSTED`, entité `cash_journal`/`payment`, `metadata` **sans montant, sans
  motif, sans PII**) dans la **même unité de travail** que l'écriture (atomicité `flush()` sans
  `commit()`).
- **Section « Encaissements » du dashboard gérant.** La page `/gerant/encaissements`
  (`coming-soon` → `available`, en coordination avec #33) affiche le **journal horodaté** (date, heure,
  type d'opération, montant, auteur, référence de transaction) et un point d'entrée de **correction**.
  Le jeton d'accès reste lu **côté serveur** depuis le cookie `httpOnly` (invariant #14).
- **Couverture de tests.** Backend : cas d'usage (append-only, correction → ligne `ADJUSTMENT`, statut
  `ADJUSTED`, audit sans PII, portée), API (`200`/`401`/`403`/`404`/`409`/`422`), e2e PostgreSQL
  (persistance du journal, isolation inter-salons, **impossibilité de supprimer** un paiement validé,
  correction créant une ligne d'ajustement, traçabilité sans PII). Web : gateway HTTP, Route Handler BFF,
  vue du journal.

## Non-Goals

- **Enregistrement d'un paiement (US-5.1 / #33).** #34 **dépend** de #33 et **ne réimplémente pas** la
  création d'un paiement (montant, mode, prestation/RDV liés, cohérence du montant §5.3). #34 se
  concentre sur le **journal** (lecture horodatée + auteur), l'**invariant de non-suppression** et la
  **correction par ajustement**.
- **Historique des transactions filtrable (US-5.2 / #35).** La liste **filtrable** par date, client,
  montant, mode de paiement relève de #35. #34 fournit une lecture **triée + paginée** du journal ; les
  filtres avancés sont hors périmètre (mais #34 doit rester cohérent avec #35 — même source de vérité).
- **Détection des écarts de caisse (US-5.4 / #36).** La comparaison prestations réalisées ↔ paiements
  (RDV terminé sans paiement) dépend de #34 mais est une **issue distincte**.
- **Supervision agrégée admin (US-5.6 / #37)** et **reçu numérique client (US-5.5 / #38)** : hors
  périmètre.
- **Ouverture / clôture de caisse (`CASH_OPENING` / `CASH_CLOSING`).** Ces types d'opération existent
  dans l'enum `CashOperationType` mais **aucune US du MVP ne les demande** ; #34 n'ajoute **pas** de
  fond/solde de caisse ni de session de caisse. Réservé à une évolution ultérieure.
- **Remboursement complet (`REFUND`) comme parcours dédié.** L'enum le prévoit, mais le critère
  d'acceptation de #34 est **« correction = ligne d'ajustement »**. #34 implémente la **correction
  (`ADJUSTMENT`)** ; un parcours de remboursement dédié (et son reçu, #38) est hors périmètre — voir
  *Open Questions* §5.
- **Suppression / droit à l'oubli.** Contraire au critère (« suppression interdite ») et relève du
  durcissement M6 (#52) pour les données personnelles ; le journal de caisse est par nature **conservé**.
- **Modification de la matrice de permissions §4.1.** `PAYMENT_RECORD` et `CASH_JOURNAL_READ` existent
  déjà ; #34 les **met en service** sans les élargir ni en créer.
- **Nouvelle migration de schéma.** Les tables `payments` et `cash_journal` et leurs contraintes
  existent depuis `0001`. #34 **n'ajoute aucune table ni colonne**. La seule exception **optionnelle** :
  un durcissement base (trigger/`REVOKE`) d'append-only — voir *Open Questions* §3.

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Journal d'audit | Table `audit_logs` + port `AuditLog`, entrées **neutres** | [0019](../docs/adr/0019-journalisation-audit-et-prestations.md) |
| Web gérant | Next.js (App Router, TypeScript), cookie `httpOnly` + BFF | [0002](../docs/adr/0002-web-gerant-admin-nextjs.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0026** (fiche client). Aucun ADR n'existe pour l'encaissement.
**#34 (ou #33) devrait produire un ADR « Encaissement & journal de caisse append-only »** (voir *Open
Questions* §7) : l'immuabilité du journal, la correction-par-ajustement et le partage #33/#34 sont des
décisions d'architecture structurantes qui méritent d'être tracées, à l'image d'ADR-0019 (journal
d'audit) et ADR-0026 (fiche client).

### Backend — patrons à réutiliser tels quels

- **Tranche verticale hexagonale salon-scopée (#28 clients, #17 prestations)** : `domain/<x>.py` (pur,
  validation), `application/<x>.py` (cas d'usage dépendant **uniquement** de ports),
  `application/ports/<x>_repository.py` (`Protocol`), `adapters/outbound/persistence/<x>_repository.py`
  (SQLAlchemy, filtre `(salon_id, id)`, `flush()` **sans** `commit()`), `adapters/inbound/<x>.py`
  (router `prefix="/salons"`, gardes, mapping d'erreurs). **Modèle direct** pour la tranche
  `cash_journal` / `payments-adjustments`.
- **Routes imbriquées & protégées** sous `/salons/{salon_id}/…` pour hériter de `require_salon_scope`
  (isolation §11.2, `403` **générique et constant** « Accès refusé. » hors périmètre) ; lectures gardées
  par `require_permission(CASH_JOURNAL_READ)`, écritures par `require_permission(PAYMENT_RECORD)`.
  L'invariant deny-by-default est vérifié mécaniquement par `unprotected_routes(app)`
  (`test_security_guards.py`) — **toute route ajoutée sans garde fait échouer les tests**.
- **Journalisation §11.4** : port `application/ports/audit_log.py`, entrée `domain/audit.py::AuditEntry`
  (`action`, `actor_user_id`, `salon_id`, `entity_type`, `entity_id`, `metadata`), adapter `SqlAuditLog`.
  `get_audit_log` et le dépôt métier partagent la **même** `Session` (FastAPI met `get_session` en cache
  par requête) → commit/rollback atomique. **Patron identique à #17/#20/#28/#32.** `domain/audit.py`
  s'étend en ajoutant des valeurs à `AuditAction` (domaine **fermé**) sans ré-architecturer — c'est le
  point d'extension prévu par ADR-0019 (« paiement, correction de caisse » y sont **explicitement**
  cités comme actions §11.4 futures).
- **Écriture-avec-diff-neutre (`UpdateSalon`, `UpdateService`, `UpdateCustomerNote`)** : validation
  domaine → résolution de l'entité (`404` si absente, portée déjà validée) → écriture → `audit_log.record(...)`
  dans la même Session. La **mutation de statut** du paiement d'origine (`→ ADJUSTED`) suit ce patron.
- **Tests** : fakes en mémoire dans `tests/conftest.py` (`FakeCustomerRepository`, `FakeAuditLog`,
  `FakeSalonScopeRepository`…) ; tests d'API via `TestClient` + `app.dependency_overrides` ; **tests e2e**
  adossés à un vrai PostgreSQL (sautés si `DATABASE_URL` absent), avec données réservées et nettoyage
  avant/après.

### Schéma déjà en place (source de vérité : `models.py`, migration `0001`)

Voir *Problem Statement* pour le détail. Points saillants pour #34 :

- `payments.recorded_by` (auteur, NOT NULL) et `cash_journal.performed_by` (auteur, NOT NULL) satisfont
  déjà l'exigence « utilisateur ayant enregistré l'opération » (§8.2).
- `payments.created_at` et `cash_journal.created_at` (`_created_at()`, `DateTime(timezone=True)`,
  `server_default=now()`) satisfont l'exigence **« horodaté »**.
- `cash_journal.transaction_id → payments(salon_id, id)` (FK composite, `RESTRICT`) permet de relier
  chaque opération de journal à sa transaction, dans le **même salon** (défense en profondeur §11.2).
- `PaymentStatus.ADJUSTED` et `CashOperationType.ADJUSTMENT` existent : le vocabulaire de correction est
  **déjà** au schéma — #34 le met en service, aucune migration n'est requise pour cela.

### Contraintes transverses documentées

- **PRD §5.3** : parcours encaissement — « le système vérifie que le montant correspond à la prestation »
  (cohérence : **#33**), « une transaction est ajoutée au journal de caisse » (**#33/#34**), « le tableau
  de bord est mis à jour » (**M5**).
- **PRD §8.2** : paiement lié à prestation/RDV ; montant + mode + **utilisateur responsable** ;
  **paiement validé jamais supprimé** ; **correction = opération d'ajustement** ; **journal horodaté** ;
  écarts visibles (#36).
- **PRD §11.2** : un gérant ne voit que les données de **son** salon.
- **PRD §11.3** : journalisation des accès sensibles, non-fuite PII, collecte minimale.
- **PRD §11.4** : actions journalisées, dont **« Paiement enregistré »** et **« Correction de caisse »**.
- **PRD §12.1** : réponse API < 3 s.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA** (code, commits, PR).
- **Test gate** : `scripts/test-gate.sh` (pytest + npm test + flutter test) ; CI applicative `ci.yml`
  (ruff, pytest, round-trip Alembic contre PostgreSQL 16, build/lint/test web).

## Proposed Implementation

> Hypothèse de travail : **#33 est livré** (enregistrement d'un paiement). Si l'implémentation de #34 est
> menée **avant** #33, la tranche paiement de base devra être établie d'abord (hors périmètre de cette
> spec, qui décrit #34). Les sections ci-dessous supposent l'existence d'un `SqlPaymentRepository` et d'un
> router `payments` ; #34 les **étend**.

### (A) Backend — domaine

- **`domain/audit.py`** : ajouter
  - `ENTITY_TYPE_PAYMENT = "payment"` et `ENTITY_TYPE_CASH_JOURNAL = "cash_journal"` (types d'entité) ;
  - `AuditAction.PAYMENT_RECORDED = "PAYMENT_RECORDED"` (§11.4 « Paiement enregistré » — posé par #33 ;
    si #33 ne l'a pas ajouté, #34 le fait) ;
  - `AuditAction.CASH_ADJUSTED = "CASH_ADJUSTED"` (§11.4 « Correction de caisse »).
  Commentaires : entrées **neutres** — jamais de montant, de motif, de PII (ADR-0019).
- **`domain/cash_journal.py`** (nouveau, pur) : le **vocabulaire et les invariants** du journal :
  - constantes/validations : `operation_type ∈ CashOperationType`, `amount` borné (`NUMERIC(12,2)`,
    ≤ 2 décimales) — **le montant d'un `ADJUSTMENT` peut être négatif** (delta de correction), à la
    différence d'un `PAYMENT` (≥ 0) ; un helper `validate_adjustment_amount` refuse un delta **nul**
    (une correction doit changer quelque chose) ;
  - une entité/valeur `CashJournalEntry` (lecture) et une commande `AdjustmentCommand` neutres ;
  - `description` optionnelle, bornée (`Text`, borne applicative raisonnable, p. ex. ≤ 500), **trim** ;
    **le motif n'est pas de la PII** mais reste hors du journal d'**audit** (il vit dans `cash_journal`,
    pas dans `audit_logs`).
- **`domain/errors.py`** : ajouter `PaymentNotFound`, `PaymentNotAdjustable` (p. ex. paiement déjà
  `CANCELLED`/`ADJUSTED`, ou non validé), `InvalidAdjustment` (delta nul, montant hors borne). Messages
  **métier et neutres**, sans reprendre de montant.

### (B) Backend — ports de persistance

- **`application/ports/payment_repository.py`** (posé par #33 ; #34 ajoute au besoin) :
  `get(salon_id, payment_id) -> Payment` (filtre `(salon_id, id)`, lève `PaymentNotFound`),
  `mark_adjusted(salon_id, payment_id) -> Payment` (statut `→ ADJUSTED`, **jamais** de delete).
- **`application/ports/cash_journal_repository.py`** (nouveau `Protocol`) :
  - `append(entry) -> CashJournalEntry` — **INSERT seul** (append-only) ; aucune méthode
    `update`/`delete` n'est déclarée (l'absence de verbe destructif **dans le port** est un choix de
    conception).
  - `list_for_salon(salon_id, *, limit, offset) -> Sequence[CashJournalEntry]` (tri
    `created_at DESC, id DESC`) et `count_for_salon(salon_id) -> int` (pagination) ; la projection de
    lecture **résout le nom d'affichage de l'auteur** (`performed_by → users`) pour l'UI, **sans**
    exposer d'autre PII de l'auteur (staff du salon).

### (C) Backend — adapters de persistance

- **`adapters/outbound/persistence/cash_journal_repository.py::SqlCashJournalEntryRepository`** :
  implémente `append`/`list_for_salon`/`count_for_salon`. `append` fait un `INSERT` puis `flush()`
  **sans** `commit()` (atomicité avec l'audit / la mutation du paiement). La lecture joint `users` pour
  le nom d'auteur (sélection **restreinte** aux colonnes non sensibles). **Aucune** méthode
  `update`/`delete` exposée.
- **`adapters/outbound/persistence/payment_repository.py`** : `mark_adjusted` fait un `UPDATE` du seul
  champ `status` (`VALIDATED → ADJUSTED`), filtré `(salon_id, id)`, `flush()` sans `commit()` ; **jamais**
  de `DELETE`.

### (D) Backend — cas d'usage

- **`application/cash_journal.py`** :
  - `ListCashJournal(cash_journal_repo)` : `execute(salon_id, *, limit, offset)` → page d'entrées
    (horodatage + auteur + type + montant signé + devise + `transaction_id` + description). Lecture pure,
    **aucune** écriture, **aucun** audit (une consultation de journal n'est pas une action §11.4 ici — la
    lecture reste bornée par la permission `CASH_JOURNAL_READ`).
  - `AdjustPayment(payment_repo, cash_journal_repo, audit_log)` :
    `execute(salon_id, payment_id, delta, description, *, actor_user_id)` →
    1. `payment = payment_repo.get(salon_id, payment_id)` (`PaymentNotFound` → `404`) ;
    2. **garde métier** : le paiement doit être **`VALIDATED`** ; sinon `PaymentNotAdjustable` (`409`) —
       on ne corrige pas un paiement `PENDING`/`CANCELLED`/déjà `ADJUSTED` ;
    3. `validate_adjustment_amount(delta)` (`InvalidAdjustment` → `422` si nul / hors borne) ;
    4. `cash_journal_repo.append(ADJUSTMENT, amount=delta, performed_by=actor_user_id,
       transaction_id=payment.id, salon_id=salon_id, description=normalize(description))` — **nouvelle
       ligne**, jamais une modification ;
    5. `payment_repo.mark_adjusted(salon_id, payment_id)` (statut `→ ADJUSTED`, **pas** de delete) ;
    6. `audit_log.record(AuditEntry(CASH_ADJUSTED, actor_user_id, salon_id,
       entity_type=ENTITY_TYPE_PAYMENT, entity_id=payment.id, metadata={}))` — **neutre** (ni delta, ni
       motif) ;
    7. toutes les écritures partagent la **même Session** (atomicité).
  - Ajouter les deux à `__all__`.
- **Ligne `PAYMENT` du journal** : le cas d'usage d'enregistrement de #33 (`RecordPayment`) doit, après
  avoir créé le `Payment` (`VALIDATED`), appeler `cash_journal_repo.append(PAYMENT, amount=+montant,
  performed_by=recorded_by, transaction_id=payment.id, …)` **via le même port**. Si #33 ne l'a pas
  câblé, #34 l'ajoute dans le flux d'enregistrement (voir *Open Questions* §1). Objectif de #34 : **tout
  paiement validé a exactement une ligne `PAYMENT` au journal**.

### (E) Backend — adapters entrants (HTTP)

Router `payments`/`cash-journal` (posé par #33 ; #34 ajoute les routes ci-dessous), `prefix="/salons"`,
inclus dans `main.py`.

- **`GET /salons/{salon_id}/cash-journal`** — `require_permission(CASH_JOURNAL_READ)` + `require_salon_scope`.
  Query `limit` (défaut/max cohérents avec `customers`), `offset`. Réponse `200` : page d'opérations
  (voir *API / Interface Changes*). `401`/`403` gérés par les gardes.
- **`POST /salons/{salon_id}/payments/{payment_id}/adjustments`** —
  `require_permission(PAYMENT_RECORD)` + `require_salon_scope`. Corps Pydantic
  `CreateAdjustmentRequest` (`model_config = ConfigDict(extra="ignore")`) : `amount` (delta signé,
  `Decimal`, ≤ 2 décimales, **≠ 0**), `description?` (str, borné). **`performed_by` n'est pas dans le
  corps** — il vient du `Principal`. Réponse `201` : la ligne `ADJUSTMENT` créée (+ nouveau statut du
  paiement). Mapping d'erreurs : `PaymentNotFound → 404`, `PaymentNotAdjustable → 409`,
  `InvalidAdjustment → 422`.
- **Aucune** route `DELETE`/`PUT`/`PATCH` sur `payments` ou `cash_journal`. **Aucun** chemin ajouté à
  `PUBLIC_ROUTE_PATHS` (le journal de caisse n'est jamais public).

### (F) Web gérant — section « Encaissements »

En coordination avec #33 (qui bascule la section `coming-soon → available`). #34 ajoute la **vue journal**
et le **point d'entrée de correction** :

1. **Domaine/types** — `src/domain/cash-journal/cash-journal.ts` : types `CashJournalEntry`
   (`operationType`, `amount`, `currency`, `performedByName`, `createdAt`, `transactionId?`,
   `description?`), helpers de formatage (montant XOF, date/heure `Africa/Abidjan`).
2. **Port & gateway** — `src/application/ports/cash-journal-gateway.ts` (`list`, `createAdjustment`) et
   `src/adapters/api/http-cash-journal-gateway.ts` (union discriminée `{ ok:true, … } | { ok:false,
   reason:"forbidden"|"unauthenticated"|"invalid"|"not-found"|"conflict"|"unavailable" }` ; **jamais**
   d'exception qui remonterait un détail réseau ; **jamais** le jeton dans le résultat).
3. **BFF** — `app/api/salons/[id]/cash-journal/route.ts` (`GET`) et
   `app/api/salons/[id]/payments/[paymentId]/adjustments/route.ts` (`POST`) : lisent le jeton du cookie
   `httpOnly` **côté serveur**, appellent les gateways, renvoient un corps **neutre** en cas d'erreur.
4. **UI** — `app/(gerant)/gerant/encaissements/page.tsx` (Server Component) : tableau du journal (date,
   heure, type, montant signé, auteur, référence de transaction), état **read-only** pour les lignes
   (append-only : **aucun** bouton supprimer/éditer). Un formulaire client-side de **correction**
   (`src/adapters/ui/payment-adjustment-form.tsx`) poste au BFF puis `router.refresh()`.

### (G) Durcissement append-only (option, base)

Optionnel et **à trancher** (voir *Open Questions* §3) : une migration `000X_cash_journal_append_only.py`
(`down_revision` = dernière révision) posant un **trigger** `BEFORE UPDATE OR DELETE ON cash_journal`
levant une exception, ou un `REVOKE UPDATE, DELETE ON cash_journal FROM <role applicatif>`. Défense en
profondeur au-delà de l'absence de route destructive. `downgrade()` réversible. **Non requis** pour
satisfaire le critère d'acceptation (l'invariant est déjà garanti côté application), mais renforce §8.2.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer / modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/audit.py` | `ENTITY_TYPE_PAYMENT`, `ENTITY_TYPE_CASH_JOURNAL`, `AuditAction.PAYMENT_RECORDED` (si absent), `AuditAction.CASH_ADJUSTED` |
| `coiflink_api/domain/cash_journal.py` | **nouveau** — vocabulaire, `validate_adjustment_amount`, entités de lecture/commande |
| `coiflink_api/domain/errors.py` | `PaymentNotFound`, `PaymentNotAdjustable`, `InvalidAdjustment` |
| `coiflink_api/application/ports/cash_journal_repository.py` | **nouveau** `Protocol` (`append`, `list_for_salon`, `count_for_salon`) |
| `coiflink_api/application/ports/payment_repository.py` | `get`, `mark_adjusted` (étend #33) |
| `coiflink_api/application/cash_journal.py` | **nouveau** — `ListCashJournal`, `AdjustPayment` (+ `__all__`) |
| `coiflink_api/adapters/outbound/persistence/cash_journal_repository.py` | **nouveau** `SqlCashJournalEntryRepository` |
| `coiflink_api/adapters/outbound/persistence/payment_repository.py` | `mark_adjusted` (étend #33) |
| `coiflink_api/adapters/inbound/payments.py` | routes `GET …/cash-journal`, `POST …/payments/{id}/adjustments` (étend #33) |
| `coiflink_api/main.py` | inclusion du router si non déjà faite par #33 |
| `tests/conftest.py` | `FakeCashJournalRepository`, `FakePaymentRepository` (append-only, `mark_adjusted`) |
| `tests/test_cash_journal_usecases.py` | **nouveau** — `ListCashJournal`, `AdjustPayment` |
| `tests/test_cash_journal_api.py` | **nouveau** — `200`/`201`/`401`/`403`/`404`/`409`/`422` |
| `tests/test_cash_journal_e2e.py` | **nouveau** — persistance, isolation, non-suppression, correction, audit sans PII |
| `tests/test_domain_audit.py` | `PAYMENT_RECORDED` / `CASH_ADJUSTED` couvertes |
| `tests/test_security_guards.py` | vérifie qu'aucune route caisse n'est publique ni destructive |
| `backend/README.md` | section « Encaissement / Journal de caisse » |

### Backend — à lire (sans modifier) pour rester fidèle aux patrons

`adapters/inbound/customers.py` (routes salon-scopées, mapping d'erreurs), `application/customers.py`
(`GetCustomer`, pagination), `application/salons.py`/`application/services.py` (écriture + audit),
`adapters/outbound/persistence/service_repository.py` (`flush()` sans `commit()`, `_get_row`),
`adapters/inbound/security.py` (`require_permission`/`require_salon_scope`), `domain/audit.py`,
`adapters/outbound/persistence/models.py` (`Payment`, `CashJournal`), et **la tranche livrée par #33**.

### Web (`web-dashboard/`)

À créer : `src/domain/cash-journal/cash-journal.ts`, `src/application/ports/cash-journal-gateway.ts`,
`src/adapters/api/http-cash-journal-gateway.ts`, `app/api/salons/[id]/cash-journal/route.ts`,
`app/api/salons/[id]/payments/[paymentId]/adjustments/route.ts`,
`app/(gerant)/gerant/encaissements/page.tsx` (si non créée par #33),
`src/adapters/ui/payment-adjustment-form.tsx`, tests `vitest` associés.
À modifier : `src/domain/navigation/sections.ts` (`encaissements` → `available`, en coordination avec
#33), `web-dashboard/README.md`.

### Documentation (racine)

`README.md` (statut §6 : M4 journal de caisse #34), éventuellement un **nouvel ADR**
`docs/adr/00XX-encaissement-journal-caisse.md` (voir *Open Questions* §7).

## API / Interface Changes

**Deux nouveaux endpoints REST** (+ éventuellement ceux de #33), tous **protégés** ; aucun n'entre dans
`PUBLIC_ROUTE_PATHS` ; **aucun verbe destructif** (`DELETE`/`PUT`/`PATCH`) n'est exposé sur `payments`
ou `cash_journal`.

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/cash-journal` | `CASH_JOURNAL_READ` + portée | `200` page d'opérations · `401` · `403` |
| `POST` | `/salons/{salon_id}/payments/{payment_id}/adjustments` | `PAYMENT_RECORD` + portée | `201` ligne d'ajustement · `401` · `403` · `404` paiement hors salon/inconnu · `409` paiement non corrigible · `422` delta nul / hors borne |

```jsonc
// GET /salons/{salon_id}/cash-journal?limit=50&offset=0 — réponse 200
{
  "items": [
    {
      "id": "…uuid…",
      "operation_type": "ADJUSTMENT",            // PAYMENT | REFUND | ADJUSTMENT | CASH_OPENING | CASH_CLOSING
      "amount": "-500.00",                        // signé ; delta négatif pour une correction à la baisse
      "currency": "XOF",
      "transaction_id": "…uuid… | null",          // paiement lié
      "performed_by": "…uuid…",                    // auteur (UUID)
      "performed_by_name": "Awa Koné",             // nom d'affichage résolu (staff du salon)
      "description": "Erreur de saisie du montant",
      "created_at": "2026-07-28T10:15:00Z"        // horodatage serveur (affiché en Africa/Abidjan)
    }
  ],
  "total": 128,
  "limit": 50,
  "offset": 0
}

// POST /salons/{salon_id}/payments/{payment_id}/adjustments — corps
{
  "amount": "-500.00",                             // delta signé (≠ 0), ≤ 2 décimales
  "description": "Erreur de saisie du montant"     // optionnel, borné
}

// 201 — réponse : la ligne ADJUSTMENT créée + statut du paiement corrigé
{
  "entry": { "id": "…", "operation_type": "ADJUSTMENT", "amount": "-500.00", "transaction_id": "…",
             "performed_by": "…", "created_at": "…" },
  "payment": { "id": "…", "status": "ADJUSTED" }
}
```

- `performed_by`/`recorded_by` **ne sont jamais** lus du corps : toujours dérivés du `Principal`.
- **Interface web (BFF, interne à Next.js)** : `GET /api/salons/[id]/cash-journal`,
  `POST /api/salons/[id]/payments/[paymentId]/adjustments`. Aucune modification de CLI, de variable
  d'environnement ou de contrat inter-paquet.

## Data Model / Protocol Changes

**Aucune migration de schéma requise pour le critère d'acceptation.** Les tables `payments` et
`cash_journal`, leurs contraintes (`RESTRICT`, `UNIQUE(salon_id, id)`, `CHECK amount >= 0`,
`enum_check`), leurs index (`(salon_id, created_at)`) et les valeurs d'enum `PaymentStatus.ADJUSTED` /
`CashOperationType.ADJUSTMENT` existent depuis la migration `0001`. #34 **écrit** dans ces tables via des
`INSERT` (journal) et un `UPDATE status` (paiement corrigé) ; il ne modifie **ni** la structure **ni** la
sérialisation.

- **`amount` d'un `ADJUSTMENT` peut être négatif** : la colonne `cash_journal.amount` **n'a pas** de
  `CHECK amount >= 0` (contrairement à `payments.amount`), ce qui autorise le delta signé. **À vérifier**
  à l'implémentation (relire `models.CashJournal`/migration `0001`) — c'est un point sensible : si un
  `CHECK` positif existait, un delta négatif serait refusé et il faudrait modéliser la correction
  autrement (deux lignes, ou `REFUND`). *Vérification effectuée pour cette spec : `cash_journal` porte
  bien `enum_check(operation_type)` mais **aucun** `CHECK amount >= 0` — le delta signé est permis.*
- **Option append-only en base** (§7, à trancher) : une migration additive (trigger/`REVOKE`) sans
  changement de colonnes. Réversible.

## Security & Privacy Considerations

**Ce module manipule des données financières et une trace d'audit** ; sa sensibilité tient à
l'**intégrité** (non-répudiation, incorruptibilité) autant qu'à la confidentialité.

- **Incorruptibilité du journal (§8.2, cœur du sujet).** **Aucune** route ne supprime ou ne modifie une
  ligne `cash_journal`, ni ne supprime un `payments` validé. L'API n'expose **aucun** `DELETE`/`PUT`/
  `PATCH` sur ces ressources ; l'écriture est un **append** (`INSERT`) et une **mutation de statut**
  bornée (`VALIDATED → ADJUSTED`, jamais un delete). Un test de sécurité vérifie l'absence de verbe
  destructif. Durcissement base optionnel (trigger/`REVOKE`, §7).
- **Correction = ajustement, jamais réécriture (§8.2).** Corriger un paiement **crée une nouvelle ligne**
  (`ADJUSTMENT`, delta signé, liée à la transaction) et **conserve** la ligne `PAYMENT` d'origine : la
  piste est complète et reconstituable (net = somme des lignes de la transaction). Le paiement d'origine
  n'est jamais effacé.
- **Auteur & horodatage non falsifiables (§8.2).** `performed_by`/`recorded_by` viennent **toujours** du
  `Principal` authentifié (jamais du corps) ; `created_at` est **généré par le serveur** (`server_default`,
  `timezone-aware`), jamais fourni par le client. Non-répudiation : chaque opération porte **qui** et
  **quand**.
- **Isolation par salon (§11.2), en profondeur.** `require_salon_scope` sur les routes (portée **chargée
  en base**) **et** filtres `salon_id` / `(salon_id, id)` en SQL, renforcés par la FK composite
  `cash_journal.(salon_id, transaction_id) → payments`. Un accès inter-salons renvoie le **`403`
  générique et constant** ; une transaction d'un autre salon est **indiscernable d'une transaction
  inexistante** (`404` **après** portée). Aucun oracle.
- **Permissions §4.1 sans élargissement.** `CASH_JOURNAL_READ` (lecture) et `PAYMENT_RECORD` (correction)
  sont détenues par le **seul `MANAGER`** ; `ROLE_PERMISSIONS` **n'est pas modifiée**. Ni `CLIENT`, ni
  `HAIRDRESSER`, ni `ADMIN` n'accèdent au journal ou à la correction (la supervision admin agrégée est
  une **autre** issue, #37, sur des agrégats sans PII).
- **Aucune PII ni montant dans le journal d'audit (§11.4, ADR-0019).** `CASH_ADJUSTED` (et
  `PAYMENT_RECORDED`) portent `actor_user_id` (UUID opaque), `salon_id`, `entity_type`, `entity_id` et
  **`metadata = {}`** — **ni le montant, ni le delta, ni le motif, ni l'identité du client** n'entrent
  dans `audit_logs`. Le détail financier vit dans `payments`/`cash_journal` (accès borné par permission),
  pas dans le journal d'audit. Un test l'exige explicitement.
- **Non-fuite dans les logs / messages d'erreur.** Aucun `print`/`logger` ne reçoit de montant, de motif
  ni de PII client ; les messages `4xx` restent **métier et neutres** (« Paiement introuvable. »,
  « Ce paiement ne peut pas être corrigé. », « Montant d'ajustement invalide. ») sans reprendre de
  valeur. Le BFF/gateway web ne journalisent jamais le jeton ni l'en-tête `Authorization`.
- **Atomicité écriture + audit.** L'`INSERT` de la ligne `ADJUSTMENT`, l'`UPDATE status` du paiement et
  l'`AuditEntry` partagent la **même** `Session` (`flush()` sans `commit()`, commit/rollback piloté par
  `get_session`) : soit tout est committé, soit rien — jamais de correction sans trace, ni d'audit
  fantôme.
- **Jeton jamais exposé côté web (#14).** La page et les Route Handlers BFF lisent le cookie `httpOnly`
  **côté serveur** ; le jeton ne transite jamais vers le navigateur et n'est jamais journalisé.
- **Nom d'auteur en lecture.** La projection du journal résout `performed_by → users` pour afficher un
  **nom** (staff du salon, non sensible dans le périmètre du salon) ; la sélection est **restreinte** aux
  colonnes non sensibles (jamais le mot de passe, le condensat, le téléphone complet si non nécessaire).

Le dépôt **documente** ces contraintes (PRD §8.2/§11.2/§11.3/§11.4, ADR-0015/0019) : #34 les respecte
sans en affaiblir aucune, et **renforce** §8.2 (incorruptibilité, correction par ajustement).

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O, fakes de `conftest.py`)

- **`tests/test_cash_journal_usecases.py`** :
  - `ListCashJournal` : tri `created_at DESC`, pagination `limit`/`offset`, projection (auteur résolu,
    montant signé, `transaction_id`), **aucune** écriture ni audit ;
  - `AdjustPayment` **nominal** : crée **une** ligne `ADJUSTMENT` (delta signé, `transaction_id =
    payment.id`, `performed_by = acteur`), passe le paiement à `ADJUSTED`, enregistre **une**
    `AuditEntry` `CASH_ADJUSTED` avec **`metadata == {}`** (ni delta, ni motif), le tout dans la même
    unité de travail ;
  - **paiement non corrigible** (`PENDING`/`CANCELLED`/déjà `ADJUSTED`) → `PaymentNotAdjustable`,
    **aucune** écriture ni audit ;
  - **delta nul / hors borne** → `InvalidAdjustment`, **aucune** écriture ni audit ;
  - paiement d'un **autre salon** / inconnu → `PaymentNotFound`, **aucun** audit ;
  - **append-only** : le fake `cash_journal` **n'expose pas** `update`/`delete` (l'invariant est
    structurel), et `mark_adjusted` ne supprime jamais la ligne.
- **`tests/test_domain_audit.py`** : `CASH_ADJUSTED` (et `PAYMENT_RECORDED`) présentes, valeurs d'enum
  cohérentes, entités `payment`/`cash_journal`.
- **`tests/test_domain_cash_journal.py`** : `validate_adjustment_amount` (refus du delta nul, borne,
  décimales), normalisation de `description`.

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_cash_journal_api.py`** :
  - `GET …/cash-journal` : `200` + page attendue (auteur, horodatage, montant signé) ; `403` rôle ≠
    `MANAGER` / hors portée (message **constant**) ; `401` sans jeton ;
  - `POST …/adjustments` : `201` + ligne `ADJUSTMENT` + `payment.status == "ADJUSTED"` ; corps portant
    `performed_by`/`recorded_by`/`created_at` → **ignorés** ; `422` delta nul ; `409` paiement non
    corrigible ; `404` paiement d'un autre salon ; `403` hors portée / rôle insuffisant ; `401` sans
    jeton ;
- **`tests/test_security_guards.py`** : `unprotected_routes(app) == []` couvre les nouvelles routes ;
  **aucun** chemin caisse dans `PUBLIC_ROUTE_PATHS` ; assertion qu'**aucune** route `DELETE`/`PUT`/
  `PATCH` n'existe sous `payments`/`cash-journal`.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_cash_journal_e2e.py`** (patron existant, données réservées, nettoyage avant/après) :
  1. parcours : inscription gérant → connexion → salon → (prérequis #33) **enregistrement d'un
     paiement** → le journal contient une ligne `PAYMENT` (auteur = gérant, horodatée) → **correction**
     → une ligne `ADJUSTMENT` (delta) apparaît, le paiement passe `ADJUSTED`, la ligne `PAYMENT`
     d'origine **subsiste** ;
  2. **non-suppression** : aucune route ne permet de supprimer le paiement validé ni une ligne de
     journal (vérifié par l'absence de verbe + une tentative `DELETE` → `404`/`405`) ;
  3. **isolation inter-salons** : le jeton du gérant B est refusé (`403` générique) sur le journal et la
     correction d'une transaction du salon de A ;
  4. **traçabilité** : une ligne `audit_logs` `CASH_ADJUSTED` avec le bon acteur et **aucune PII/montant**
     dans `metadata` (assertion explicite) ;
  5. deny-by-default : sans jeton → `401`.
- **Migration** : si l'option append-only base (§7) est retenue, ajouter un round-trip Alembic
  (upgrade/downgrade) contre PostgreSQL 16 ; sinon **aucune** migration à couvrir.

### Web (`vitest`)

- `test/http-cash-journal-gateway.test.ts` : mapping `list`/`createAdjustment`
  (`200/201 → ok`, `403 → forbidden`, `401 → unauthenticated`, `404 → not-found`, `409 → conflict`,
  `422 → invalid`), en-tête `Authorization` posé, **jeton jamais** dans le résultat.
- `test/cash-journal-bff.test.ts` : `401` sans cookie ; erreurs propagées avec message **neutre** ;
  **aucune PII/montant/jeton** dans les réponses d'erreur.
- `test/payment-adjustment-form.test.tsx` (si le socle le permet) : delta requis ≠ 0, `router.refresh()`
  au succès, affichage read-only des lignes existantes.

### Documentation / non-régression

- `scripts/test-gate.sh` (pytest + npm test + flutter test) au vert ; `ruff check` propre ; `npm run
  lint && npm run build` (sortie standalone) inchangé ; l'application mobile (`flutter test`) reste
  **verte et inchangée** (le journal de caisse n'est **jamais** exposé au client).

## Documentation Updates

- **`backend/README.md`** — nouvelle section « Encaissement / Journal de caisse » : routes `GET
  …/cash-journal` et `POST …/payments/{id}/adjustments` (permissions, portée §11.2, réponses, invariant
  **append-only**, correction = `ADJUSTMENT`, audit `CASH_ADJUSTED`/`PAYMENT_RECORDED` **sans PII**), avec
  exemples `curl` et la règle « un paiement validé n'est jamais supprimé ».
- **`web-dashboard/README.md`** — section « Encaissements » : vue journal horodatée + auteur, correction,
  BFF (`app/api/salons/[id]/cash-journal`, `.../payments/[paymentId]/adjustments`), cookie `httpOnly` +
  `router.refresh()`.
- **`README.md`** (racine) — §6 : phrase de statut « M4 : journal de caisse horodaté (US-5.3, #34) —
  chaque opération horodatée + auteur, suppression interdite, correction = ligne d'ajustement » dans le
  style des paragraphes existants.
- **`docs/adr/`** — **nouvel ADR recommandé** « Encaissement & journal de caisse append-only » (voir
  *Open Questions* §7), tranchant : immuabilité du journal, correction-par-ajustement (delta signé vs
  `REFUND`), partage #33/#34, durcissement base optionnel. Mettre à jour l'index `docs/adr/README.md`.
- **OpenAPI** — `summary`/`responses`/docstrings des routes documentent la nouvelle API (`/docs`), y
  compris `409`/`422`.

## Risks and Open Questions

1. **Partage des responsabilités #33 ↔ #34.** *Recommandation : #33 enregistre le paiement (`VALIDATED`)
   **et** écrit la ligne `PAYMENT` du journal via le port fourni par #34 ; #34 possède le port/adapter
   caisse, la lecture du journal, l'invariant append-only et la correction.* À trancher explicitement (et
   à consigner dans l'ADR) pour éviter une double-écriture ou une ligne `PAYMENT` manquante. Si #33 est
   déjà mergé sans écrire la ligne `PAYMENT`, #34 doit **rétro-câbler** ce writer dans le flux
   d'enregistrement — vérifier l'état réel de #33 **avant** d'implémenter.
2. **Modélisation de la correction : delta `ADJUSTMENT` vs `REFUND` + nouveau `PAYMENT`.**
   *Recommandation : une ligne `ADJUSTMENT` au montant **delta signé** rattachée à la transaction, +
   paiement d'origine `→ ADJUSTED`* — simple, incrémental, conforme à « correction = ligne d'ajustement »,
   et le net d'une transaction = somme de ses lignes. **Alternative** (annulation totale puis re-saisie) :
   `REFUND` (montant négatif complet) + nouveau `PAYMENT` — plus lourd, réservé au remboursement (#38).
   Dépend aussi de l'absence de `CHECK amount >= 0` sur `cash_journal` (**vérifiée** pour cette spec).
3. **Durcissement append-only en base (trigger / `REVOKE UPDATE,DELETE`).** *Recommandation : le faire en
   défense en profondeur* (une migration additive), car §8.2 est une exigence `security`. **Coût** : une
   migration + gestion des privilèges du rôle applicatif (peut interagir avec les migrations Alembic
   elles-mêmes, qui doivent pouvoir écrire). **Alternative** : s'en tenir à l'invariant applicatif
   (absence de route destructive + tests) au MVP, et différer le durcissement base à M6 (#52). À trancher.
4. **Mutation `payments.status → ADJUSTED` : est-ce compatible avec « jamais supprimé » ?** *Recommandation :
   oui* — une mutation de **statut** n'est pas une suppression ; la ligne et son montant d'origine
   subsistent, et l'enum `PaymentStatus.ADJUSTED` est **prévu pour cela**. **Alternative stricte** : ne
   pas toucher le paiement du tout et déduire son état « corrigé » de la présence d'une ligne
   `ADJUSTMENT` liée (immuabilité totale de `payments`). À trancher (l'ADR devrait le figer).
5. **Remboursement (`REFUND`).** Hors périmètre de #34 (le critère est « correction = ajustement »).
   *Recommandation : ne pas l'implémenter ici* ; le laisser à un parcours dédié (avec reçu, #38). Ne pas
   exposer d'endpoint `REFUND` tant qu'une US ne le demande pas.
6. **Nom d'auteur en lecture : join `users` vs enrichissement applicatif.** *Recommandation : join SQL
   restreint aux colonnes non sensibles* (`display_name`), pour un affichage direct. **À confirmer** que
   le champ de nom existe sur `users` et n'expose pas de PII superflue.
7. **Un ADR est-il requis ?** *Recommandation : oui* — l'encaissement introduit des décisions
   structurantes (immuabilité, correction-par-ajustement, partage #33/#34, éventuel durcissement base)
   qui méritent une trace, comme ADR-0019 (audit) et ADR-0026 (client). Idéalement porté par **#33** (ou
   #34 s'il est le premier à toucher la caisse). **À confirmer** avec l'équipe.
8. **`limit`/`offset` par défaut et maximum.** *Recommandation : réutiliser les bornes de pagination de
   `customers`/`appointments`* pour la cohérence. À aligner à l'implémentation.
9. **Devise.** `currency` a un défaut `'XOF'` (FCFA) au schéma ; le MVP est mono-devise. #34 **n'introduit
   pas** de conversion ni de multi-devise (affichage XOF/FCFA). À garder tel quel.
10. **Ordre d'implémentation.** #34 **dépend** de #33. Si #33 n'est pas mergé quand #34 démarre, soit
    attendre #33, soit établir d'abord une base paiement minimale (hors périmètre de cette spec). **À
    clarifier par l'orchestrateur** avant de lancer l'implémentation.

## Implementation Checklist

1. **Vérifier l'état de #33** (mergé ? quel périmètre exact ? écrit-il déjà une ligne `PAYMENT` au
   journal ? router/section web déjà posés ?) et **trancher** les questions ouvertes 1–7 ; consigner la
   décision (idéalement un **ADR** « Encaissement & journal de caisse append-only »).
2. **Lire** `adapters/inbound/customers.py`, `application/customers.py` (pagination, salon-scope),
   `application/salons.py`/`services.py` (écriture + audit), `adapters/inbound/security.py`,
   `domain/audit.py`, `models.py` (`Payment`, `CashJournal`), et la tranche livrée par #33.
3. **Domaine** : créer `domain/cash_journal.py` (validation `validate_adjustment_amount`, entités
   neutres) ; ajouter `ENTITY_TYPE_PAYMENT`/`ENTITY_TYPE_CASH_JOURNAL` + `AuditAction.CASH_ADJUSTED`
   (et `PAYMENT_RECORDED` si absent) à `domain/audit.py` ; ajouter `PaymentNotFound`,
   `PaymentNotAdjustable`, `InvalidAdjustment` à `domain/errors.py`. Compléter `tests/test_domain_audit.py`
   et `tests/test_domain_cash_journal.py`.
4. **Ports** : créer `application/ports/cash_journal_repository.py` (`append`, `list_for_salon`,
   `count_for_salon` — **aucun** `update`/`delete`) ; compléter `payment_repository.py` (`get`,
   `mark_adjusted`).
5. **Cas d'usage** : créer `application/cash_journal.py` (`ListCashJournal`, `AdjustPayment` — validation
   **avant** écriture, `metadata={}`, atomicité) ; ajouter à `__all__`.
6. **Fakes & tests applicatifs** : `FakeCashJournalRepository`/`FakePaymentRepository` dans
   `tests/conftest.py` ; écrire `tests/test_cash_journal_usecases.py` (append-only, correction, statut
   `ADJUSTED`, audit sans PII, non corrigible, delta nul, portée).
7. **Adapters sortants** : `SqlCashJournalEntryRepository` (`INSERT` + `flush()` sans `commit()`, lecture
   triée/paginée + join auteur restreint) ; `mark_adjusted` sur `SqlPaymentRepository` (`UPDATE status`,
   **jamais** de delete).
8. **Adapters entrants** : routes `GET …/cash-journal` (`CASH_JOURNAL_READ`) et `POST
   …/payments/{payment_id}/adjustments` (`PAYMENT_RECORD`), schémas Pydantic (`extra="ignore"`, delta
   `≠ 0`), mapping `404`/`409`/`422` ; **aucune** route destructive ; **ne pas** toucher
   `PUBLIC_ROUTE_PATHS`. Câbler le writer de ligne `PAYMENT` dans le flux d'enregistrement si #33 ne l'a
   pas fait.
9. **Tests API & sécurité & e2e** : `tests/test_cash_journal_api.py`, assertions dans
   `tests/test_security_guards.py` (pas de route publique, pas de verbe destructif),
   `tests/test_cash_journal_e2e.py` (persistance, non-suppression, isolation, correction, audit sans
   PII) ; exécuter `pytest` (+ `DATABASE_URL` pour l'e2e) et `ruff check`.
10. **(Option §7)** migration `append_only` (trigger/`REVOKE`) + round-trip Alembic si retenue.
11. **Web — domaine/port/gateway** : `src/domain/cash-journal/cash-journal.ts`,
    `src/application/ports/cash-journal-gateway.ts`, `src/adapters/api/http-cash-journal-gateway.ts`
    (+ `test/http-cash-journal-gateway.test.ts`).
12. **Web — BFF** : `app/api/salons/[id]/cash-journal/route.ts` (`GET`) et
    `app/api/salons/[id]/payments/[paymentId]/adjustments/route.ts` (`POST`) (+ `test/cash-journal-bff.test.ts`).
13. **Web — UI** : `app/(gerant)/gerant/encaissements/page.tsx` (journal read-only horodaté + auteur) et
    `src/adapters/ui/payment-adjustment-form.tsx` (correction, `router.refresh()`) ; basculer
    `encaissements` en `available` dans `src/domain/navigation/sections.ts` (en coordination avec #33).
14. **Documentation** : sections dédiées `backend/README.md` / `web-dashboard/README.md` ; phrase de
    statut `README.md` racine ; ADR (et index) si retenu.
15. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test + **flutter test
    inchangé**), `ruff check`, `npm run lint && npm run build` ; relire la PR pour garantir qu'**aucun
    montant, motif ou PII** n'apparaît dans les logs, l'audit ou les messages d'erreur, qu'**aucune**
    route ne supprime un paiement validé ou une ligne de journal, que le journal **n'est exposé à aucune
    route publique/mobile**, et qu'**aucune signature IA** n'a été introduite.
