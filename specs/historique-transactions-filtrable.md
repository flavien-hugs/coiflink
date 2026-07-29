# Historique des transactions filtrable (gérant) (US-5.2)

> Spécification de planification pour l'issue GitHub **#35 — US-5.2 : Historique des transactions
> (filtrable)** (`feature` `payments` · **Must** · Effort **S** · PRD §6 Épic 5 / §5.3 « Parcours
> encaissement » / §8.2 « Encaissement » / §11.2-11.4). **Dépend de #33** (US-5.1 — enregistrement
> d'un paiement), et s'articule avec **#34** (US-5.3 — journal de caisse horodaté). **Cette spec ne
> produit pas de code** : elle décrit l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 5, US-5.2) pose le besoin : **« en tant que gérant, je veux consulter l'historique des
transactions pour suivre mon activité »**, avec pour spécification fonctionnelle une **liste filtrable
par date, client, montant, mode de paiement**. Le critère d'acceptation de l'issue #35 est :

- **Filtres fonctionnels ; cohérence avec le journal de caisse.**

Aujourd'hui, le gérant peut **enregistrer** un paiement (#33, `POST /salons/{salon_id}/payments`) et
**consulter le journal de caisse** horodaté (#34, `GET /salons/{salon_id}/cash-journal`), mais il n'a
**aucun moyen de retrouver une transaction précise** : le journal de caisse est trié du plus récent au
plus ancien et **paginé**, sans **aucun filtre**. Retrouver « les paiements en Mobile Money du 15 mars »
ou « les transactions de tel client au-dessus de 10 000 FCFA » impose de parcourir toutes les pages à
l'œil. US-5.2 comble ce manque en exposant une **liste de transactions filtrable côté serveur**.

### État actuel du dépôt (vérifié pour cette spec)

La **tranche verticale encaissement est livrée** (#33 + #34, backend), avec les artefacts suivants :

- **Table `payments`** (`models.Payment`, migration `0001`, PRD §9.6) — porte **déjà toutes les
  colonnes filtrables** demandées par US-5.2 :
  - `created_at` (`DateTime(timezone=True)`, `server_default=now()`) → filtre **date** ;
  - `client_id` (FK `→ users.id`, **nullable**, `RESTRICT`) → filtre **client** ;
  - `amount` (`NUMERIC(12,2)`, `CHECK amount >= 0`) → filtre **montant** ;
  - `payment_method` (`String(32)`, `enum_check` sur `PaymentMethod`) → filtre **mode de paiement** ;
  - plus `salon_id`, `status` (`PaymentStatus` : `PENDING`/`VALIDATED`/`CANCELLED`/`ADJUSTED`),
    `appointment_id?`, `service_id?`, `recorded_by` (NOT NULL), `reference?`, `currency` (défaut `XOF`).
  - Index `ix_payments_salon_id (salon_id, created_at)` (support natif du tri/filtre par date
    salon-scopé) et `ix_payments_appointment_id (appointment_id)`. `UNIQUE(salon_id, id)`.
- **`SqlPaymentRepository`** (`adapters/outbound/persistence/payment_repository.py`) : expose
  `create`, `get(salon_id, payment_id)`, `mark_adjusted(...)`. **Aucune** méthode de **liste** :
  c'est le manque principal côté persistance que #35 doit combler.
- **`PaymentRepository`** (port `Protocol`, `application/ports/payment_repository.py`) : `create`,
  `get`, `mark_adjusted` — **pas** de `list`.
- **Router `payments`** (`adapters/inbound/payments.py`, `prefix="/salons"`) : `POST …/payments`,
  `GET …/cash-journal`, `POST …/payments/{payment_id}/adjustments`. **Aucune** route de liste de
  transactions. Tous les chemins sont **protégés** (aucun dans `PUBLIC_ROUTE_PATHS`) et **aucun** verbe
  destructif (`DELETE`/`PUT`/`PATCH`) n'est exposé.
- **`domain/payment.py`** : `Payment`, `PaymentToCreate`, bornes du montant, `PAYMENT_METHOD_VALUES`,
  `DEFAULT_CURRENCY = "XOF"`, `REFERENCE_MAX_LENGTH`, validations pures.
- **`domain/cash_journal.py`** + **`SqlCashJournalEntryRepository`** : le journal de caisse
  (`cash_journal`) est **append-only** ; ses lignes portent `operation_type` (`PAYMENT`/`ADJUSTMENT`/…),
  `amount` **signé**, `performed_by` (+ `full_name` résolu), `transaction_id` (FK composite
  `(salon_id, transaction_id) → payments(salon_id, id)`), `description`, `created_at`. Le journal
  **ne porte ni `client_id` ni `payment_method`** : il **ne peut donc pas** servir de source aux filtres
  « client » et « mode de paiement ».
- **Permissions** (`domain/permissions.py`, §4.1) : `PAYMENT_RECORD` (écriture) et **`CASH_JOURNAL_READ`
  (lecture caisse)** existent, détenues par le **seul `MANAGER`** ; aucune n'est ajoutée par #35.
- **Web gérant** : la section **`encaissements`** (`/gerant/encaissements`) est **`available`** (#33) et
  ne contient **que** le formulaire d'enregistrement d'un paiement (`RecordPaymentForm`). Il existe un
  domaine/port/gateway web `payment` (`src/domain/payments/payment.ts`,
  `src/application/ports/payment-gateway.ts`, `src/adapters/api/http-payment-gateway.ts`) et un BFF
  `app/api/salons/[id]/payments/route.ts` (POST). **La vue journal de caisse (#34) n'a pas encore de
  web** (cf. ADR-0027, « frontière #33 ↔ #34 ») : aucune liste de caisse n'est affichée côté web à ce
  jour. Le domaine `payment.ts` fournit déjà `PAYMENT_METHOD_OPTIONS`, `paymentMethodLabel`, `formatXof`
  — réutilisables tels quels par la liste filtrable.

### Le gap que #35 comble

Sur la base de #33/#34, #35 rend les **transactions retrouvables** :

1. **Liste filtrable** des transactions d'un salon par **date** (plage), **client**, **montant** (plage)
   et **mode de paiement**, appliquée **côté serveur** (jamais un filtrage navigateur sur un jeu complet).
2. **Cohérence avec le journal de caisse** : la même **source de vérité** (`payments`) alimente la liste
   et la ligne `PAYMENT` du journal ; montants, horodatages et auteurs **concordent**, et un paiement
   corrigé (statut `ADJUSTED`) est **reconnaissable** dans la liste comme dans le journal.

## Goals

- **Endpoint de liste filtrable, protégé et salon-scopé.** Nouvel endpoint **`GET
  /salons/{salon_id}/payments`** (permission **`CASH_JOURNAL_READ`** + portée `require_salon_scope`)
  listant les transactions (paiements) du salon **du plus récent au plus ancien**, paginé
  (`limit`/`offset`, mêmes bornes que `cash-journal`/`customers`), avec les **filtres optionnels** :
  - `date_from` / `date_to` — plage de dates **inclusive** ;
  - `client_id` — UUID du client lié à la transaction ;
  - `amount_min` / `amount_max` — plage de montants (`Decimal`, ≤ 2 décimales) ;
  - `payment_method` — valeur **de l'enum fermé** `PaymentMethod`.
  Les filtres se **combinent en `ET`** ; absents, ils n'imposent aucune contrainte.
- **Filtrage côté serveur, jamais côté client.** Les critères deviennent des clauses `WHERE` SQL
  (garde de coût §12.1 + pas de fuite d'un jeu complet au navigateur). La pagination et le tri restent
  **déterministes** (`created_at DESC, id DESC`).
- **Cohérence avec le journal de caisse (critère d'acceptation).** La liste et le journal partagent la
  **même** table source `payments` : le montant, l'horodatage (`created_at`) et l'auteur (`recorded_by`)
  d'une transaction **concordent** avec sa ligne `PAYMENT` au journal (`cash_journal.transaction_id =
  payment.id`). Un paiement corrigé apparaît **`ADJUSTED`** dans la liste **et** possède une ligne
  `ADJUSTMENT` au journal — la même réalité, deux vues. Un test e2e **verrouille** cette réconciliation.
- **Validation stricte et neutre des filtres.** Une valeur de filtre invalide (mode hors enum, plage
  incohérente `date_from > date_to` ou `amount_min > amount_max`, montant mal formé) renvoie **`422`**
  avec un message **métier et neutre**, sans reprendre la valeur saisie (§11.3).
- **Isolation par salon (§11.2), en profondeur.** Route imbriquée sous `/salons/{salon_id}/…`
  (héritant de `require_salon_scope`) **et** dépôt refiltrant **toujours** sur `salon_id`. Aucune
  transaction d'un autre salon n'apparaît, quel que soit le filtre ; un `client_id` étranger au salon
  **ne provoque aucun oracle** — il produit simplement une **liste vide** (jamais une erreur qui
  révélerait son existence ailleurs).
- **Lecture seule, sans effet de bord.** La consultation n'écrit rien et **ne journalise pas** d'action
  §11.4 (comme `GET …/cash-journal`) — elle reste bornée par la permission `CASH_JOURNAL_READ`.
- **Réutilise les permissions §4.1 sans les élargir.** `CASH_JOURNAL_READ` est détenue par le **seul
  `MANAGER`** ; `ROLE_PERMISSIONS` **n'est pas modifiée**, aucune permission n'est créée.
- **Aucune migration de schéma.** Toutes les colonnes filtrables et l'index `(salon_id, created_at)`
  existent depuis `0001`. #35 **lit** `payments` ; il n'ajoute **ni table ni colonne** (index
  additionnel **optionnel** — voir *Open Questions*).
- **Section « Encaissements » enrichie d'un onglet/vue « Historique ».** La page
  `/gerant/encaissements` affiche, en plus du formulaire d'enregistrement, une **liste filtrable** des
  transactions (date/heure `Africa/Abidjan`, client, montant `formatXof`, mode `paymentMethodLabel`,
  statut). Le jeton reste lu **côté serveur** depuis le cookie `httpOnly` (invariant #14).
- **Couverture de tests.** Backend : domaine (validation du filtre), cas d'usage (combinaisons de
  filtres, `ET`, tri, pagination), API (`200`/`401`/`403`/`422`), e2e PostgreSQL (persistance,
  isolation inter-salons, exactitude des filtres, **cohérence avec le journal**). Web : gateway HTTP,
  Route Handler BFF, vue liste + contrôles de filtre.

## Non-Goals

- **Enregistrement d'un paiement (US-5.1 / #33)** et **journal de caisse / correction (US-5.3 / #34)** :
  livrés ; #35 **ne les modifie pas** (au plus, il ajoute une méthode de **lecture** au port/adapter
  `payment` et une **route GET**). Aucune modification de l'écriture, de la correction ni de
  l'invariant append-only.
- **Détection des écarts de caisse (US-5.4 / #36).** Rapprochement prestations réalisées ↔ paiements :
  issue distincte.
- **Supervision agrégée admin (US-5.6 / #37)** et **reçu numérique client (US-5.5 / #38)** : hors
  périmètre.
- **Agrégats / totaux / export.** #35 livre une **liste** filtrable paginée ; les totaux par période, le
  CA cumulé (tableau de bord M5) et l'export CSV/PDF ne sont **pas** demandés par le critère
  d'acceptation. À ne pas ajouter sans US dédiée.
- **Montant « net » recalculé (paiement − ajustements).** La liste affiche la transaction **telle
  qu'enregistrée** avec son **statut** (`VALIDATED`/`ADJUSTED`) ; le net d'un paiement corrigé (somme
  des lignes du journal) reste **du ressort du journal de caisse** (#34). #35 n'introduit **pas** de
  calcul de solde (voir *Open Questions* §3).
- **Nouvelle permission ou modification de la matrice §4.1.** `CASH_JOURNAL_READ` existe et couvre le
  besoin ; #35 la **réutilise** sans l'élargir.
- **Recherche plein-texte / filtre par référence libre.** Le critère cite **date, client, montant,
  mode** — s'y tenir. Un filtre `reference` (recherche libre) est une extension possible mais **hors
  périmètre** (voir *Open Questions* §5).
- **Migration / index dédié obligatoire.** Aucune migration n'est requise pour le critère
  d'acceptation ; un index composite additionnel est une **option** de performance (voir *Open
  Questions* §4).

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Encaissement | Cohérence du montant, journal append-only, correction par ajustement | [0027](../docs/adr/0027-encaissement-coherence-montant.md) |
| Web gérant | Next.js (App Router, TypeScript), cookie `httpOnly` + BFF | [0002](../docs/adr/0002-web-gerant-admin-nextjs.md) |

**ADR-0027** (encaissement) est l'ADR le plus pertinent : il fige la source des montants, la mono-devise
XOF, la portée salon en profondeur et la frontière #33/#34. #35 s'y inscrit sans nouvelle décision
structurante ; un ADR n'est **probablement pas** requis (voir *Documentation Updates* / *Open
Questions* §7).

### Backend — patrons à réutiliser tels quels

- **Liste salon-scopée paginée (#28 clients, #34 journal)** : `list_for_salon(salon_id, *, limit,
  offset)` + `count_for_salon(salon_id)` dans le dépôt, tri `created_at DESC, id DESC`, bornes en SQL ;
  cas d'usage de lecture pure (`ListCashJournal`, `list_customers`) **sans** audit ; route `GET` gardée
  par `require_permission(...) + require_salon_scope`, `limit`/`offset` en `Query(...)` avec `ge`/`le`.
  **Modèle direct** pour `GET …/payments` : #35 = `ListCashJournal` **+ un filtre**.
- **Résolution du nom d'auteur en lecture, sans PII superflue** (`SqlCashJournalEntryRepository` joint
  `users.full_name`) : patron applicable si la liste doit afficher un **nom de client** (join
  `payments.client_id → users.full_name`, colonne non sensible uniquement) — voir *Open Questions* §2.
- **Validation de domaine pure** (`domain/payment.py`, `domain/cash_journal.py`) : un objet-valeur de
  **filtre** validé (plages cohérentes, mode dans l'enum, montants bornés en `Decimal`) suit ce patron,
  testable sans I/O.
- **Mapping d'erreurs de l'adapter entrant** (`payments.py`) : `_VALIDATION_ERRORS → 422`. Un filtre
  invalide rejoint ce jeu (`InvalidTransactionFilter → 422`).
- **Tests** : fakes en mémoire (`conftest.py`), `TestClient` + `app.dependency_overrides`, e2e adossés
  à un PostgreSQL réel (sautés si `DATABASE_URL` absent), `test_security_guards.py`
  (`unprotected_routes(app) == []`, pas de verbe destructif).

### Web — patrons à réutiliser tels quels

- **Server Component + composition root** (`encaissements/page.tsx`) : lecture du jeton via
  `createCookieSessionStore().read()` **côté serveur** (invariant #14), appel des gateways HTTP.
- **Gateway à union discriminée** (`http-payment-gateway.ts`, `http-customer-gateway.ts`) : `{ ok:true,
  … } | { ok:false, reason: "forbidden"|"unauthenticated"|"invalid"|"unavailable"|… }`, **jamais**
  d'exception réseau ni de jeton dans le résultat.
- **BFF Route Handler** (`app/api/salons/[id]/payments/route.ts`, `.../customers/route.ts`) : lit le
  cookie `httpOnly`, relaie au backend, renvoie un corps **neutre** en erreur, propage les query params.
- **Domaine `payment.ts`** : `PAYMENT_METHOD_OPTIONS`, `paymentMethodLabel`, `formatXof`, `Payment` —
  **déjà** présents et réutilisables par la vue liste et le sélecteur de filtre « mode de paiement ».

### Contraintes transverses documentées

- **PRD §5.3 / §8.2** : encaissement lié à prestation/RDV, montant + mode + **utilisateur responsable**,
  transaction au journal de caisse, journal horodaté.
- **PRD §11.2** : un gérant ne voit que les données de **son** salon.
- **PRD §11.3** : non-fuite PII, collecte minimale, journalisation des accès sensibles sans PII.
- **PRD §12.1** : réponse API < 3 s (⇒ pagination + filtrage SQL, jamais en mémoire).
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA** (code, commits, PR).
- **Test gate** : `scripts/test-gate.sh` (pytest + npm test + flutter test) ; CI `ci.yml` (ruff, pytest,
  round-trip Alembic PostgreSQL 16, build/lint/test web).

## Proposed Implementation

### Décision de conception centrale — source de vérité = `payments`

La liste filtrable s'appuie sur la table **`payments`** (les *transactions*), **pas** sur `cash_journal`.
Raison : seule `payments` porte `client_id` **et** `payment_method` (le journal ne les a pas). La
**cohérence avec le journal** est garantie *parce que* les deux vues dérivent des **mêmes** paiements
(`cash_journal.transaction_id = payments.id`, ligne `PAYMENT` par paiement, même `amount`/`created_at`/
auteur) — pas parce qu'elles partageraient la même requête. Le journal reste la vue **caisse
chronologique complète** (paiements *et* ajustements) ; l'historique #35 est la vue **transactions
filtrable**.

### (A) Backend — domaine

- **`domain/transaction.py`** (nouveau, pur — ou section dédiée de `domain/payment.py`) :
  - un objet-valeur **`TransactionFilter`** neutre : `date_from: date | None`, `date_to: date | None`,
    `client_id: uuid | None`, `amount_min: Decimal | None`, `amount_max: Decimal | None`,
    `payment_method: str | None` ;
  - une fonction pure **`validate_transaction_filter(...) -> TransactionFilter`** qui :
    - refuse une **plage incohérente** (`date_from > date_to`, `amount_min > amount_max`) →
      `InvalidTransactionFilter` ;
    - refuse un **mode hors enum** `PaymentMethod` → `InvalidTransactionFilter` ;
    - normalise/quantifie les montants en `Decimal` au centime (`0.01`, miroir `NUMERIC(12,2)`), refuse
      un montant **négatif** ou hors borne (`AMOUNT_MAX`), refuse > 2 décimales — **jamais** un flottant ;
    - laisse `None` = « pas de contrainte ».
  - **Interprétation temporelle** : `date_from`/`date_to` sont des **dates** (jour civil) interprétées
    dans le fuseau **`Africa/Abidjan`** (UTC+0, convention #21) et converties en **bornes UTC**
    `[date_from 00:00, date_to 23:59:59.999999]` inclusives pour comparer à `created_at`
    (`timezone-aware`). Le domaine expose la conversion (ou la délègue à un helper partagé) ; l'adapter
    **ne réinvente pas** de fuseau.
- **`domain/errors.py`** : ajouter **`InvalidTransactionFilter`** (message métier et neutre, sans
  reprendre la valeur — p. ex. « Filtre de transactions invalide. »).

### (B) Backend — port de persistance

- **`application/ports/payment_repository.py`** : ajouter deux lectures (le port ne gagne **aucun** verbe
  destructif) :
  - `list_for_salon(salon_id, *, filter, limit, offset) -> tuple[Payment, ...]` — page filtrée, tri
    `created_at DESC, id DESC` ;
  - `count_for_salon(salon_id, *, filter) -> int` — total **sous le même filtre** (pagination correcte).
  - Constantes de pagination `PAYMENTS_LIMIT_DEFAULT/MIN/MAX` (aligner sur `CASH_JOURNAL_LIMIT_*` = 50/1/
    200 pour la cohérence des surfaces caisse).
  - Si l'affichage d'un **nom de client** est retenu (*Open Questions* §2), la projection de lecture
    résout `client_id → users.full_name` (colonne non sensible **uniquement**) ; sinon, `client_id`
    brut suffit.

### (C) Backend — adapter de persistance

- **`adapters/outbound/persistence/payment_repository.py::SqlPaymentRepository`** : implémenter
  `list_for_salon`/`count_for_salon`. Construire la requête `select(models.Payment)` (éventuellement
  join `users.full_name` sur `client_id`), appliquer **inconditionnellement** `where(salon_id == …)`,
  puis **conditionnellement** les clauses de filtre présentes :
  - `created_at >= borne_utc(date_from)` / `created_at <= borne_utc(date_to)` ;
  - `client_id == filter.client_id` ;
  - `amount >= filter.amount_min` / `amount <= filter.amount_max` ;
  - `payment_method == filter.payment_method`.
  Tri `created_at DESC, id DESC`, `limit`/`offset` en SQL. `count_for_salon` applique **exactement** les
  mêmes clauses. **Lecture seule** : aucune écriture, aucun `flush`. L'index `ix_payments_salon_id
  (salon_id, created_at)` couvre le cas dominant (salon + tri/plage de date).

### (D) Backend — cas d'usage

- **`application/transactions.py`** (nouveau) — `ListTransactions(payment_repo)` :
  `execute(salon_id, *, filter, limit, offset) -> (page, total)`. **Lecture pure**, **aucun** audit
  (comme `ListCashJournal`). Ajouter à `__all__`. (Alternative : ajouter la classe à
  `application/payments.py` à côté de `RecordPayment` ; un fichier dédié isole mieux la lecture — à
  trancher, cohérence avec `cash_journal.py` qui regroupe lecture + écriture.)

### (E) Backend — adapter entrant (HTTP)

Étendre le router `payments` (`adapters/inbound/payments.py`) avec **`GET /salons/{salon_id}/payments`**,
`require_permission(CASH_JOURNAL_READ)` + `require_salon_scope`. Query params typés (FastAPI `Query`) :
`date_from`/`date_to` (`date | None`), `client_id` (`uuid | None`), `amount_min`/`amount_max` (`Decimal
| None`, ≥ 0), `payment_method` (`str | None`), `limit`/`offset` (bornés). Le handler :

1. construit `TransactionFilter` via `validate_transaction_filter(...)` (le seul endroit qui décide de la
   cohérence des plages/enum) ;
2. appelle `ListTransactions(...).execute(...)` ;
3. mappe `InvalidTransactionFilter → 422` (rejoint `_VALIDATION_ERRORS`) ;
4. renvoie une **page** (`items` + `total` + `limit` + `offset` + éventuellement les filtres appliqués,
   écho pour l'UI).

Réutiliser `PaymentResponse` pour chaque item (id, montant, devise, mode, statut, `recorded_by`,
références, `created_at`) ; ajouter `client_name` **si** l'affichage du nom est retenu (§2). **Aucune**
route destructive ajoutée ; **aucun** chemin dans `PUBLIC_ROUTE_PATHS` (données financières jamais
publiques).

### (F) Web gérant — vue « Historique » dans « Encaissements »

1. **Domaine/types** — `src/domain/payments/transaction.ts` (ou extension de `payment.ts`) : type
   `TransactionFilter` (chaînes de formulaire), helpers de sérialisation vers query params ; réutiliser
   `Payment`, `PAYMENT_METHOD_OPTIONS`, `paymentMethodLabel`, `formatXof`, et un format date/heure
   `Africa/Abidjan`.
2. **Port & gateway** — étendre `src/application/ports/payment-gateway.ts` (`listTransactions(salonId,
   filter, page)`) et `src/adapters/api/http-payment-gateway.ts` (union discriminée `{ ok:true, items,
   total, limit, offset } | { ok:false, reason: "forbidden"|"unauthenticated"|"invalid"|"unavailable" }`,
   **jamais** de jeton dans le résultat).
3. **BFF** — `app/api/salons/[id]/payments/route.ts` : ajouter le **handler `GET`** (le `POST` existe) qui
   lit le cookie `httpOnly` **côté serveur**, propage les query params de filtre au backend, renvoie un
   corps **neutre** en erreur.
4. **UI** — enrichir `app/(gerant)/gerant/encaissements/page.tsx` (Server Component) d'une **vue liste**
   (onglet ou section « Historique des transactions ») : tableau **read-only** (date/heure, client,
   montant `formatXof`, mode `paymentMethodLabel`, statut) + une **barre de filtres**
   (`src/adapters/ui/transaction-filters.tsx`, client-side) dont la soumission met à jour les
   `searchParams` de la page (filtrage **serveur** au re-render, pas de filtrage en mémoire). État vide
   explicite (« Aucune transaction ne correspond à ces filtres. »).

### (G) Cohérence avec le journal de caisse — vérification

La cohérence est **structurelle** (même table `payments`), mais doit être **testée** : un test e2e
enregistre un paiement, le retrouve **à la fois** dans `GET …/payments` (avec les bons montant/mode/
client/date) **et** comme ligne `PAYMENT` dans `GET …/cash-journal` (même `transaction_id`, même
montant, même auteur, même `created_at`) ; après une **correction**, le paiement apparaît `ADJUSTED`
dans la liste **et** une ligne `ADJUSTMENT` existe au journal.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer / modifier

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/transaction.py` | **nouveau** — `TransactionFilter`, `validate_transaction_filter`, bornes temporelles `Africa/Abidjan` (ou section dédiée de `domain/payment.py`) |
| `coiflink_api/domain/errors.py` | `InvalidTransactionFilter` |
| `coiflink_api/application/ports/payment_repository.py` | `list_for_salon(..., filter, limit, offset)`, `count_for_salon(..., filter)`, constantes de pagination |
| `coiflink_api/application/transactions.py` | **nouveau** — `ListTransactions` (+ `__all__`) |
| `coiflink_api/adapters/outbound/persistence/payment_repository.py` | `list_for_salon` / `count_for_salon` (clauses `WHERE` conditionnelles, tri, join `full_name` optionnel) |
| `coiflink_api/adapters/inbound/payments.py` | route `GET …/payments` (query de filtres, mapping `422`), schéma de page |
| `tests/conftest.py` | `FakePaymentRepository` : ajouter `list_for_salon`/`count_for_salon` (filtrage en mémoire miroir du SQL) |
| `tests/test_domain_transaction.py` | **nouveau** — `validate_transaction_filter` (plages, enum, bornes, décimales, fuseau) |
| `tests/test_transactions_usecases.py` | **nouveau** — `ListTransactions` (filtres `ET`, tri, pagination, aucune écriture/audit) |
| `tests/test_transactions_api.py` | **nouveau** — `200` + filtres, `401`, `403`, `422` (filtre invalide) |
| `tests/test_payments_e2e.py` | **étendre** — persistance filtrée, isolation inter-salons, exactitude des filtres, **cohérence avec le journal** |
| `tests/test_security_guards.py` | la nouvelle route est protégée (pas dans `PUBLIC_ROUTE_PATHS`), pas de verbe destructif |
| `backend/README.md` | section encaissement : documenter `GET …/payments` + filtres |

### Backend — à lire (sans modifier) pour rester fidèle aux patrons

`adapters/inbound/payments.py` (routes salon-scopées, `_VALIDATION_ERRORS`, `PaymentResponse`),
`application/cash_journal.py` (`ListCashJournal` : lecture pure sans audit),
`adapters/outbound/persistence/cash_journal_repository.py` (liste triée/paginée + join auteur restreint),
`application/customers.py` + `adapters/inbound/customers.py` (pagination `limit`/`offset`),
`adapters/inbound/security.py` (`require_permission`/`require_salon_scope`),
`domain/payment.py`/`domain/enums.py` (`PaymentMethod`, bornes), `models.py` (`Payment`, index).

### Web (`web-dashboard/`)

À créer : `src/domain/payments/transaction.ts` (ou extension `payment.ts`),
`src/adapters/ui/transaction-filters.tsx`, `src/adapters/ui/transaction-list.tsx`, tests `vitest`
associés.
À modifier : `src/application/ports/payment-gateway.ts` (`listTransactions`),
`src/adapters/api/http-payment-gateway.ts` (mapping + parsing de page),
`app/api/salons/[id]/payments/route.ts` (handler `GET`),
`app/(gerant)/gerant/encaissements/page.tsx` (vue liste + filtres), `web-dashboard/README.md`.

### Documentation (racine)

`README.md` (statut §6 : M4 historique des transactions #35). ADR : **optionnel** (voir *Open
Questions* §7).

## API / Interface Changes

**Un nouvel endpoint REST** (lecture), **protégé** ; il n'entre **pas** dans `PUBLIC_ROUTE_PATHS` ;
**aucun verbe destructif** ajouté.

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `GET` | `/salons/{salon_id}/payments` | `CASH_JOURNAL_READ` + portée | `200` page filtrée · `401` · `403` · `422` filtre invalide |

Query params (tous **optionnels** sauf pagination par défaut) :

| Param | Type | Sémantique |
| --- | --- | --- |
| `date_from` | `date` (`YYYY-MM-DD`) | borne basse **inclusive** (jour civil `Africa/Abidjan`) |
| `date_to` | `date` (`YYYY-MM-DD`) | borne haute **inclusive** |
| `client_id` | `uuid` | client lié à la transaction (`payments.client_id`) |
| `amount_min` | `Decimal` (≥ 0, ≤ 2 déc.) | montant minimum |
| `amount_max` | `Decimal` (≥ 0, ≤ 2 déc.) | montant maximum |
| `payment_method` | `str` ∈ `PaymentMethod` | `CASH`/`MOBILE_MONEY_MANUAL`/`CARD_MANUAL`/`OTHER` |
| `limit` | `int` (1..200, défaut 50) | pagination |
| `offset` | `int` (≥ 0, défaut 0) | pagination |

```jsonc
// GET /salons/{salon_id}/payments?date_from=2026-03-01&date_to=2026-03-31&payment_method=MOBILE_MONEY_MANUAL&amount_min=10000.00 — réponse 200
{
  "items": [
    {
      "id": "…uuid…",
      "salon_id": "…uuid…",
      "amount": "15000.00",
      "currency": "XOF",
      "payment_method": "MOBILE_MONEY_MANUAL",
      "status": "VALIDATED",              // VALIDATED | ADJUSTED | (PENDING | CANCELLED)
      "recorded_by": "…uuid…",
      "client_id": "…uuid… | null",
      "client_name": "Awa Koné",          // OPTIONNEL — seulement si l'affichage du nom est retenu (§2)
      "appointment_id": "…uuid… | null",
      "service_id": "…uuid… | null",
      "reference": "REC-2026-0001",
      "created_at": "2026-03-15T10:15:00Z" // horodatage serveur (affiché en Africa/Abidjan)
    }
  ],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

- Filtres invalides → **`422`** (`InvalidTransactionFilter`), message métier neutre (« Filtre de
  transactions invalide. ») **sans** reprendre la valeur.
- **Interface web (BFF, interne à Next.js)** : `GET /api/salons/[id]/payments?…` (mêmes query params).
  Aucune modification de CLI, de variable d'environnement ou de contrat inter-paquet.

## Data Model / Protocol Changes

**Aucune migration de schéma requise.** La table `payments`, ses colonnes filtrables (`created_at`,
`client_id`, `amount`, `payment_method`), son index `ix_payments_salon_id (salon_id, created_at)` et
l'enum `PaymentMethod` existent depuis la migration `0001`. #35 **lit** ces données via des `SELECT`
filtrés ; il ne modifie **ni** la structure **ni** la sérialisation.

- **Option** (non requise) : un **index composite** additionnel (p. ex. `(salon_id, payment_method,
  created_at)` ou `(salon_id, client_id, created_at)`) si le volume salon le justifie. Au MVP, le volume
  par salon est faible et `(salon_id, created_at)` + le filtrage résiduel suffisent (< 3 s §12.1). Une
  telle migration serait **additive** et réversible — voir *Open Questions* §4.

## Security & Privacy Considerations

Ce module expose des **données financières** salon-scopées ; sa sensibilité tient à la
**confidentialité** (isolation §11.2, pas de fuite inter-salons) et à la **collecte minimale** (§11.3).

- **Isolation par salon (§11.2), en profondeur.** `require_salon_scope` sur la route (portée **chargée
  en base**) **et** filtre `salon_id` **inconditionnel** dans le dépôt. Aucun filtre client ne peut
  faire fuir une transaction d'un autre salon ; un `client_id` étranger au salon **ne renvoie aucune
  erreur** — juste une **liste vide** (pas d'oracle d'existence inter-salons, cohérent avec ADR-0027 §4).
- **Permission §4.1 sans élargissement.** `CASH_JOURNAL_READ` (lecture caisse) est détenue par le
  **seul `MANAGER`** ; `ROLE_PERMISSIONS` **n'est pas modifiée**. Ni `CLIENT`, ni `HAIRDRESSER`, ni
  `ADMIN` n'accèdent à l'historique des transactions d'un salon (la supervision admin agrégée est une
  **autre** issue, #37, sur des agrégats).
- **Lecture seule, sans effet de bord ni journalisation d'action.** La consultation n'écrit rien et **ne
  journalise pas** une action §11.4 (comme `GET …/cash-journal`). La permission **est** le contrôle
  d'accès ; aucune `AuditEntry` n'est requise pour une lecture.
- **Collecte minimale / pas de PII superflue (§11.3).** La réponse porte `client_id` (UUID opaque) et,
  **si** l'affichage du nom est retenu (§2), **uniquement** `users.full_name` du client (jamais
  téléphone, e-mail ni condensat). La projection SQL **sélectionne les seules colonnes nécessaires**.
- **Non-fuite dans les logs / messages d'erreur.** Aucun `print`/`logger` ne reçoit de montant, de
  `client_id`, de `reference` ni de PII ; les messages `4xx` restent **métier et neutres** (« Filtre de
  transactions invalide. ») sans reprendre la valeur du filtre. Le BFF/gateway web ne journalisent
  **jamais** le jeton ni l'en-tête `Authorization`.
- **Validation stricte des entrées.** Les filtres sont **validés** (mode dans l'enum fermé, plages
  cohérentes, montants bornés `NUMERIC(12,2)`) avant toute requête ; un `Decimal` (jamais un flottant)
  pour les montants (parité avec ADR-0027). Cela évite les requêtes malformées et borne le coût.
- **Garde de coût (§12.1).** Pagination **obligatoire** (`limit ≤ 200`), filtrage **en SQL** (jamais en
  mémoire sur un jeu complet), `count` sous le même filtre. Réponse < 3 s.
- **Jeton jamais exposé côté web (#14).** La page et le Route Handler BFF lisent le cookie `httpOnly`
  **côté serveur** ; le jeton ne transite jamais vers le navigateur et n'est jamais journalisé.

Le dépôt **documente** ces contraintes (PRD §8.2/§11.2/§11.3/§12.1, ADR-0015/0027) : #35 les respecte
sans en affaiblir aucune.

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O, fakes de `conftest.py`)

- **`tests/test_domain_transaction.py`** : `validate_transaction_filter` — plages incohérentes
  (`date_from > date_to`, `amount_min > amount_max`) → `InvalidTransactionFilter` ; mode hors enum →
  erreur ; montant négatif / > 2 décimales / hors borne → erreur ; `None` = pas de contrainte ;
  conversion `Africa/Abidjan` → bornes UTC inclusives (jour civil complet).
- **`tests/test_transactions_usecases.py`** : `ListTransactions` — combinaison de filtres en **`ET`**,
  tri `created_at DESC, id DESC`, pagination `limit`/`offset`, `total` **sous filtre**, **aucune**
  écriture ni audit ; liste vide pour un filtre sans correspondance.
- Compléter `FakePaymentRepository` (miroir du SQL : filtrage en mémoire déterministe).

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_transactions_api.py`** :
  - `GET …/payments` : `200` + page attendue (sans filtre) ; `200` + sous-ensemble correct pour chaque
    filtre et pour une combinaison ; `422` mode hors enum / plage incohérente / montant mal formé ;
    `403` rôle ≠ `MANAGER` / hors portée (message **constant**) ; `401` sans jeton ;
  - pagination : `limit`/`offset` respectés, `total` cohérent.
- **`tests/test_security_guards.py`** : `unprotected_routes(app) == []` couvre la nouvelle route ; **pas**
  de chemin `payments` (GET) dans `PUBLIC_ROUTE_PATHS` ; **aucune** route destructive ajoutée.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_payments_e2e.py`** (étendre — données réservées, nettoyage avant/après) :
  1. enregistrer plusieurs paiements (dates, modes, montants, clients variés) puis vérifier chaque
     **filtre** (date, client, montant, mode) et une **combinaison** → sous-ensembles exacts ;
  2. **isolation inter-salons** : le gérant B ne voit **aucune** transaction du salon A (`403` sur la
     route hors portée ; un `client_id` du salon A depuis le salon B → **liste vide**, pas d'oracle) ;
  3. **cohérence avec le journal** : chaque paiement listé possède **une** ligne `PAYMENT` au journal
     (même `transaction_id`, montant, auteur, `created_at`) ; après **correction**, le paiement est
     `ADJUSTED` dans la liste **et** une ligne `ADJUSTMENT` existe au journal ;
  4. deny-by-default : sans jeton → `401`.

### Web (`vitest`)

- `test/http-payment-gateway.test.ts` : `listTransactions` — `200 → ok` (parsing items/total/bornes),
  `403 → forbidden`, `401 → unauthenticated`, `422 → invalid`, `5xx → unavailable` ; en-tête
  `Authorization` posé ; **jeton jamais** dans le résultat ; propagation des query params de filtre.
- `test/payments-bff.test.ts` : `GET` sans cookie → `401` ; erreurs propagées avec message **neutre** ;
  **aucune PII/montant/jeton** dans les réponses d'erreur ; query params relayés.
- `test/transaction-filters.test.tsx` / `test/transaction-list.test.tsx` (si le socle le permet) :
  sérialisation des filtres en `searchParams`, rendu read-only, état vide, libellés
  `paymentMethodLabel`/`formatXof`, format date `Africa/Abidjan`.

### Documentation / non-régression

- `scripts/test-gate.sh` (pytest + npm test + flutter test) au vert ; `ruff check` propre ; `npm run
  lint && npm run build` (sortie standalone) inchangé ; l'application mobile (`flutter test`) reste
  **verte et inchangée** (l'historique des transactions n'est **jamais** exposé au client).

## Documentation Updates

- **`backend/README.md`** — compléter la section encaissement : route `GET …/payments` (permission
  `CASH_JOURNAL_READ`, portée §11.2, **filtres** date/client/montant/mode, pagination, `422` filtre
  invalide, cohérence avec le journal), avec exemples `curl`.
- **`web-dashboard/README.md`** — section « Encaissements » : vue **Historique des transactions**
  (filtres, liste read-only, BFF `GET /api/salons/[id]/payments`, cookie `httpOnly`, filtrage serveur).
- **`README.md`** (racine) — §6 : phrase de statut « M4 : historique des transactions filtrable
  (US-5.2, #35) — liste par date, client, montant, mode de paiement, cohérente avec le journal de
  caisse », dans le style des paragraphes existants.
- **OpenAPI** — `summary`/`responses`/docstrings de la route documentent la nouvelle API (`/docs`), y
  compris les query params et le `422`.
- **`docs/adr/`** — **optionnel** : #35 réutilise ADR-0027 (encaissement) sans nouvelle décision
  structurante forte. Si l'équipe estime que « source de vérité = `payments` pour l'historique
  filtrable + réutilisation de `CASH_JOURNAL_READ` » mérite une trace, un ADR léger peut être ajouté
  (voir *Open Questions* §7) ; sinon, la note dans les README suffit.

## Risks and Open Questions

1. **Signification exacte de « filtre par client ».** `payments.client_id → users.id` (compte client),
   **nullable** — beaucoup de paiements enregistrés depuis l'écran gérant peuvent avoir `client_id =
   null` (le formulaire actuel ne l'impose pas). Or le gérant raisonne en **fiches client**
   (`CustomerProfile`, salon-scopé), **pas** en comptes `users`. *Recommandation MVP : filtrer sur
   `payments.client_id` tel qu'enregistré* (simple, fidèle à la donnée), et exposer le filtre côté UI
   comme la sélection d'un client **présent dans les transactions**. La corrélation
   `CustomerProfile ↔ users`/le rattachement systématique du client à l'encaissement est un sujet plus
   large (lié à #33 et à la fiche client #28/#29) — **à clarifier** avant l'implémentation. À défaut, le
   filtre « client » n'aura d'effet que sur les paiements portant un `client_id`.
2. **Affichage d'un nom de client dans la liste.** Résoudre `client_id → users.full_name` (join
   restreint, patron `SqlCashJournalEntryRepository`) améliore l'UX mais ajoute une jointure et expose
   un nom. *Recommandation : afficher `full_name` (colonne non sensible) si `client_id` présent, sinon
   « — ».* **À confirmer** que `users.full_name` existe et ne fait pas fuir d'autre PII.
3. **Montant affiché : brut vs net (après ajustements).** *Recommandation : afficher le montant **tel
   qu'enregistré** + le **statut** (`ADJUSTED` signale une correction).* Le net (paiement − ajustements)
   relève du **journal de caisse** (#34), pas de l'historique des transactions. Recalculer un net dans
   #35 dupliquerait la logique caisse — **hors périmètre** sauf décision contraire.
4. **Index dédié.** *Recommandation : s'en tenir à `(salon_id, created_at)` au MVP* (volume salon
   faible, filtrage résiduel peu coûteux, < 3 s §12.1). Ajouter un index composite seulement si un profil
   de charge le justifie (migration additive réversible). À trancher selon le volume réel attendu.
5. **Filtre par référence / recherche libre.** Le critère cite **date, client, montant, mode**. *Un
   filtre `reference` (recherche libre) est hors périmètre* ; ne l'ajouter que si une US le demande.
6. **Statuts inclus dans la liste.** En pratique, seuls `VALIDATED` et `ADJUSTED` existent (les
   paiements naissent `VALIDATED`, `PENDING`/`CANCELLED` ne sont produits par aucun flux MVP).
   *Recommandation : lister **tous** les statuts (historique complet), sans filtre `status` dédié* ; un
   filtre par statut est une extension possible mais non demandée.
7. **Un ADR est-il requis ?** *Recommandation : non, un enrichissement des README suffit* — #35 réutilise
   ADR-0027 et n'introduit pas de décision d'architecture forte (pas de nouvelle table, pas de nouvelle
   permission, pas de nouvel invariant de sécurité). **À confirmer** : si l'équipe veut tracer « source
   de vérité = `payments` pour l'historique filtrable », un ADR léger reste possible.
8. **Emplacement du cas d'usage / du domaine.** `application/transactions.py` + `domain/transaction.py`
   (dédié) vs extension de `application/payments.py` + `domain/payment.py`. *Recommandation : fichiers
   dédiés* (lisibilité, isolation de la lecture filtrée), en cohérence avec `cash_journal.py`. Sans
   enjeu fonctionnel — à aligner avec les préférences du dépôt.
9. **Bornes de pagination.** *Recommandation : réutiliser `CASH_JOURNAL_LIMIT_*` (50/1/200)* pour la
   cohérence des surfaces caisse.
10. **Fuseau des bornes de date.** `date_from`/`date_to` sont des **jours civils** interprétés en
    `Africa/Abidjan` (UTC+0, convention #21) → bornes UTC inclusives `[00:00, 23:59:59.999999]`.
    *Recommandation : centraliser cette conversion dans le domaine (ou un helper partagé)* pour que
    l'adapter ne réinvente pas de fuseau. À vérifier vis-à-vis des helpers temporels existants (#21).

## Implementation Checklist

1. **Lire** `adapters/inbound/payments.py` (routes, `_VALIDATION_ERRORS`, `PaymentResponse`),
   `application/cash_journal.py` (`ListCashJournal`), `cash_journal_repository.py` (liste/pagination/
   join auteur), `application/customers.py`/`adapters/inbound/customers.py` (pagination),
   `domain/payment.py`/`domain/enums.py`, `models.py` (`Payment`, index) ; **trancher** les questions
   ouvertes 1–8 (surtout §1 « sens du filtre client » et §2 « nom de client »).
2. **Domaine** : créer `domain/transaction.py` (`TransactionFilter`, `validate_transaction_filter`,
   conversion `Africa/Abidjan → UTC`) ; ajouter `InvalidTransactionFilter` à `domain/errors.py`. Écrire
   `tests/test_domain_transaction.py`.
3. **Port** : ajouter `list_for_salon(salon_id, *, filter, limit, offset)` et `count_for_salon(salon_id,
   *, filter)` (+ constantes de pagination) à `application/ports/payment_repository.py` — **aucun** verbe
   destructif.
4. **Cas d'usage** : créer `application/transactions.py` (`ListTransactions`, lecture pure sans audit) ;
   ajouter à `__all__`. Compléter `FakePaymentRepository` (filtrage en mémoire miroir) et écrire
   `tests/test_transactions_usecases.py`.
5. **Adapter sortant** : implémenter `list_for_salon`/`count_for_salon` dans `SqlPaymentRepository`
   (filtre `salon_id` inconditionnel + clauses conditionnelles, tri `created_at DESC, id DESC`, bornes en
   SQL, join `full_name` optionnel §2) — **lecture seule**.
6. **Adapter entrant** : ajouter `GET /salons/{salon_id}/payments` (`CASH_JOURNAL_READ` + portée), query
   de filtres typée, construction de `TransactionFilter`, mapping `InvalidTransactionFilter → 422`,
   schéma de page ; **aucune** route destructive, **ne pas** toucher `PUBLIC_ROUTE_PATHS`.
7. **Tests API & sécurité & e2e** : `tests/test_transactions_api.py` (`200`/filtres/`401`/`403`/`422`),
   assertions dans `tests/test_security_guards.py` (route protégée, pas de verbe destructif), étendre
   `tests/test_payments_e2e.py` (persistance filtrée, isolation, exactitude, **cohérence avec le
   journal**) ; exécuter `pytest` (+ `DATABASE_URL` pour l'e2e) et `ruff check`.
8. **Web — domaine/port/gateway** : `src/domain/payments/transaction.ts` (types + sérialisation
   filtres), étendre `payment-gateway.ts` (`listTransactions`) et `http-payment-gateway.ts` (mapping +
   parsing page) (+ `test/http-payment-gateway.test.ts`).
9. **Web — BFF** : handler `GET` dans `app/api/salons/[id]/payments/route.ts` (cookie `httpOnly` côté
   serveur, propagation des filtres, corps neutre en erreur) (+ `test/payments-bff.test.ts`).
10. **Web — UI** : enrichir `app/(gerant)/gerant/encaissements/page.tsx` d'une vue **Historique**
    (`transaction-list.tsx` read-only + `transaction-filters.tsx` → `searchParams`, filtrage **serveur**),
    en réutilisant `paymentMethodLabel`/`formatXof` et un format date `Africa/Abidjan` ; état vide
    explicite (+ tests `vitest`).
11. **Documentation** : sections `backend/README.md` / `web-dashboard/README.md` ; phrase de statut
    `README.md` racine ; ADR léger **si** retenu (§7).
12. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test + **flutter test
    inchangé**), `ruff check`, `npm run lint && npm run build` ; relire la PR pour garantir qu'**aucun
    montant, `client_id`, référence ou PII** n'apparaît dans les logs ou les messages d'erreur, que le
    filtrage est **toujours** salon-scopé (aucune fuite inter-salons, aucun oracle sur `client_id`),
    que la route est **protégée** et **en lecture seule**, que l'historique **n'est exposé à aucune
    route publique/mobile**, et qu'**aucune signature IA** n'a été introduite.
</content>
</invoke>
