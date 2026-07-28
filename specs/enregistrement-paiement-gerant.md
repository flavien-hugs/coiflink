# Enregistrement d'un paiement (gérant) (US-5.1)

> Spécification de planification pour l'issue GitHub **#33 — US-5.1 : Enregistrement d'un paiement**
> (`feature` `payments` · **Must** · Effort **M** · PRD §6 Épic 5 / §5.3 « Parcours encaissement » /
> §8.2 « Encaissement » / §11.4 « Journalisation »). **Dépend de #25** (cycle de statuts RDV gérant,
> livré — M3 achevé). **Cette spec ne produit pas de code** : elle décrit l'approche à implémenter dans
> une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 5, US-5.1) pose le besoin : **« en tant que gérant, je veux enregistrer un paiement
pour encaisser une prestation »**. Le critère d'acceptation de l'issue #33 est :

- **Paiement enregistré et lié au RDV/prestation ; montant cohérent ; opération journalisée (§11.4).**

Ces exigences reprennent des **règles métier explicites** du PRD :

- §8.2 (« Encaissement ») : « Chaque paiement doit être lié à une prestation ou un rendez-vous », «
  montant + mode de paiement + **utilisateur responsable** », « le système vérifie que **le montant
  correspond à la prestation** ».
- §5.3 (« Parcours encaissement ») : « le système **vérifie que le montant correspond à la
  prestation** », « une transaction est ajoutée au **journal de caisse** », « l'opération est
  **journalisée** ».
- §11.4 (« Journalisation ») : **« Paiement enregistré »** figure parmi les actions à journaliser.

### État actuel du dépôt (vérifié pour cette spec) — point critique

⚠️ **La tranche verticale backend d'« enregistrement d'un paiement » existe déjà.** Elle a été livrée
comme **socle de #34** (US-5.3 — journal de caisse, commits `5f1f50c` et `22f86ab`), qui **dépendait**
de #33 mais a été implémenté en premier. Concrètement, **le code suivant est déjà présent et testé** :

- **`POST /salons/{salon_id}/payments`** (`adapters/inbound/payments.py::record_payment`) — garde
  `PAYMENT_RECORD` + `require_salon_scope`, corps `CreatePaymentRequest` (`extra="ignore"`), réponse
  `201 PaymentResponse`, mapping des erreurs de validation → `422`.
- **`application/payments.py::RecordPayment`** — cas d'usage : validation domaine → création du
  `Payment` (`VALIDATED`) → **ligne `PAYMENT`** au journal de caisse (`transaction_id = payment.id`,
  `performed_by = recorded_by`) → **audit `PAYMENT_RECORDED`** (`metadata` **vide**, §11.4), le tout
  dans la **même unité de travail** (atomicité).
- **`domain/payment.py`** — entités `PaymentToCreate`/`Payment` et validations : `validate_amount`
  (`Decimal`, `>= 0`, ≤ `NUMERIC(12,2)`, ≤ 2 décimales), `validate_payment_method` (valeur exacte de
  l'enum `PaymentMethod`), `validate_currency` (mono-devise XOF), `normalize_reference`,
  **`require_reference_present`** (impose une prestation **OU** un RDV, §8.2).
- **`adapters/outbound/persistence/payment_repository.py::SqlPaymentRepository.create`** —
  `INSERT` + `flush()` sans `commit()`, filtre/rattachement `salon_id`.
- **Permission `PAYMENT_RECORD`** (§4.1) : détenue par le **seul `MANAGER`**, câblée sur la route.
- **Audit** : `AuditAction.PAYMENT_RECORDED` + `ENTITY_TYPE_PAYMENT` dans `domain/audit.py`.
- **Schéma** : tables `payments`/`cash_journal` et enums (`PaymentMethod`, `PaymentStatus`,
  `CashOperationType`) présents depuis la migration `0001`. Contraintes `payments` : `CHECK amount >= 0`,
  `CHECK (appointment_id IS NOT NULL OR service_id IS NOT NULL)`, `enum_check`, FK composites `RESTRICT`
  vers salon/RDV/prestation/client/utilisateur, `UNIQUE(salon_id, id)`.
- **Tests** : `tests/test_domain_payment.py` (validations), plus la couverture cas d'usage/API/e2e de
  #34 qui exerce déjà `RecordPayment` en amont du journal.

### Le gap que #33 comble réellement

Puisque le **cœur de l'enregistrement** est livré, la valeur restante de #33 tient à **deux** manques
précis, tous deux **explicitement** dans le critère d'acceptation et le PRD :

1. **La cohérence du montant (« montant cohérent » / « le montant correspond à la prestation », §5.3 /
   §8.2) N'EST PAS vérifiée.** Aujourd'hui `validate_amount` ne contrôle que les **bornes** (`>= 0`,
   ≤ max, ≤ 2 décimales) ; **aucune** comparaison n'est faite entre le montant saisi et le prix de la
   prestation/RDV lié. Le cas d'usage `RecordPayment` **n'injecte aucun** dépôt de prestation ni de RDV,
   donc il ne connaît pas le « prix attendu ». **C'est le manque backend substantiel de #33.**
2. **Il n'existe aucune interface gérant pour enregistrer un paiement.** La section
   **« Encaissements »** du dashboard (`/gerant/encaissements`) est en **`coming-soon`**
   (`web-dashboard/src/domain/navigation/sections.ts:67`) ; il n'y a **ni page, ni formulaire, ni
   gateway, ni Route Handler BFF** de paiement côté web. Un gérant ne peut donc pas encaisser depuis le
   produit, alors que c'est précisément l'US.

#33 se concentre donc sur **(1) rendre le montant cohérent avec la prestation liée** et **(2) livrer
l'écran gérant d'enregistrement d'un paiement**, sans réimplémenter la tranche déjà en place.

## Goals

- **Cohérence du montant avec la prestation liée (§5.3/§8.2) — objectif central de #33.** Étendre
  `RecordPayment` pour **calculer un « montant attendu »** à partir de la référence du paiement, puis
  refuser (`422`) tout paiement dont le montant ne correspond pas :
  - paiement lié à un **RDV** (`appointment_id`) → montant attendu = **somme des `price_at_booking`**
    des lignes `appointment_services` du RDV (prix figés à la réservation, source de vérité déjà
    utilisée par #29/#30/#31) ;
  - paiement lié à une **prestation** seule (`service_id`, sans RDV) → montant attendu = **`Service.price`**
    de la prestation **active** du salon ;
  - si les deux sont fournis, la **cohérence porte sur le RDV** (référence la plus spécifique), le
    `service_id` devant appartenir au RDV (cohérence de référence — voir *Open Questions* §2).
  La comparaison se fait en `Decimal` (jamais de flottant), à la précision `NUMERIC(12,2)`.
- **Règle de tolérance explicite et testée.** Par défaut, **égalité stricte** au centime près
  (`montant == attendu`). Décision à figer (voir *Open Questions* §3) : autoriser un
  **acompte / paiement partiel** (`0 < montant <= attendu`) est une évolution possible mais **le MVP
  applique l'égalité stricte** sauf décision contraire consignée dans l'ADR.
- **Résolution du prix attendu via des ports, sans coupler le domaine à l'ORM.** `RecordPayment`
  injecte `AppointmentRepository` (déjà : `get_in_salon(appointment_id, salon_id)` renvoie l'`Appointment`
  et ses `BookedService` avec `price_at_booking`) et `ServiceRepository` (déjà :
  `find_by_id(salon_id, service_id)` renvoie le `Service` et son `price`). **Aucun nouveau port** n'est
  requis ; au plus, une méthode de lecture additive si une projection dédiée est préférable.
- **Références inexistantes / hors salon refusées proprement.** Un `appointment_id` ou `service_id`
  qui n'appartient pas au salon de la portée (ou n'existe pas) est **indiscernable** (pas d'oracle) et
  produit une erreur métier neutre (`422` « Prestation ou rendez-vous introuvable pour ce salon. » —
  voir *Open Questions* §4 sur le code HTTP). L'isolation §11.2 est déjà garantie par les filtres
  `salon_id` des dépôts.
- **Aucune régression sur l'existant.** Les invariants déjà livrés restent intacts : `recorded_by`
  vient **toujours** du `Principal` (jamais du corps), `status` imposé `VALIDATED`, **une** ligne
  `PAYMENT` au journal par paiement, audit `PAYMENT_RECORDED` **neutre** (`metadata = {}`, ni montant,
  ni mode, ni client), atomicité `flush()` sans `commit()`.
- **Écran gérant « Enregistrer un paiement ».** Basculer la section `encaissements` en `available` et
  livrer le parcours web : sélection de la prestation/du RDV à encaisser, montant **pré-rempli** avec le
  prix attendu (guidage de la cohérence côté client, la source de vérité restant le backend), mode de
  paiement, référence optionnelle ; soumission au BFF puis retour d'état. Jeton lu **côté serveur**
  depuis le cookie `httpOnly` (invariant #14).
- **Journalisation §11.4 sans PII.** Réutilise l'audit `PAYMENT_RECORDED` déjà en place : entrée
  **neutre**, jamais de montant/mode/identité client dans `audit_logs`.
- **Couverture de tests étendue.** Backend : cas d'usage de cohérence (RDV, prestation seule, montant
  incohérent, référence hors salon/inconnue), API (`201`/`401`/`403`/`422`), e2e PostgreSQL (paiement
  d'un RDV terminé avec montant = somme des `price_at_booking` → `201` + ligne `PAYMENT` ; montant
  incohérent → `422`, aucune écriture, aucun audit). Web : gateway HTTP, Route Handler BFF, formulaire.

## Non-Goals

- **Ré-implémenter la tranche d'enregistrement déjà livrée.** `POST …/payments`, `RecordPayment`,
  `domain/payment.py`, `SqlPaymentRepository.create`, l'audit `PAYMENT_RECORDED` et la ligne `PAYMENT`
  du journal **existent** (socle de #34). #33 les **étend** (cohérence du montant) et les **expose** au
  gérant (web) ; il ne les récrit pas.
- **Journal de caisse, non-suppression, correction par ajustement (US-5.3 / #34).** Déjà livrés :
  `GET …/cash-journal`, `POST …/payments/{id}/adjustments`, invariant append-only. #33 ne touche pas ces
  routes (mais l'écran web #33 peut cohabiter avec la future vue journal — voir *Risks*).
- **Historique/liste filtrable des transactions (US-5.2 / #35).** La recherche par date, client, mode,
  montant relève de #35. #33 ne fournit pas de liste de paiements.
- **Détection des écarts de caisse (US-5.4 / #36).** Comparaison RDV terminés ↔ paiements : issue
  distincte.
- **Reçu numérique client (US-5.5 / #38)** et **supervision admin agrégée (US-5.6 / #37)** : hors
  périmètre.
- **Statut `PENDING` / flux de paiement en attente.** #33 crée un paiement **directement `VALIDATED`**
  (encaissement immédiat au comptoir). Aucun cycle de validation différée n'est ajouté.
- **Mobile Money / carte automatisés.** Hors MVP (PRD §16). Les modes `MOBILE_MONEY_MANUAL` /
  `CARD_MANUAL` restent des **saisies manuelles** (une `reference` libre optionnelle) ; aucune
  intégration PSP.
- **Multi-devise.** Le MVP est mono-devise (XOF/FCFA) ; `validate_currency` le garantit déjà. Aucune
  conversion.
- **Nouvelle migration de schéma.** Les tables/contraintes/enums existent depuis `0001`. #33 n'ajoute
  **aucune** table ni colonne.
- **Modification de la matrice de permissions §4.1.** `PAYMENT_RECORD` existe et est détenue par le
  **seul `MANAGER`** ; #33 ne l'élargit pas.

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

`docs/adr/` s'arrête aujourd'hui à **ADR-0026** (fiche client). **Aucun ADR n'existe pour
l'encaissement** alors que #34 a introduit des décisions structurantes (immuabilité du journal,
correction par ajustement) et que #33 en ajoute une (**règle de cohérence du montant** : égalité stricte
vs acompte). Un **ADR « Encaissement — cohérence du montant & enregistrement d'un paiement »** est
recommandé (voir *Documentation Updates* et *Open Questions* §7).

### Backend — patrons à réutiliser tels quels

- **Tranche verticale hexagonale salon-scopée déjà en place** (`domain/payment.py`,
  `application/payments.py`, `adapters/inbound/payments.py`, `payment_repository.py`) : #33 **édite**
  ces fichiers plutôt que d'en créer.
- **Résolution de prix par port** : `application/ports/appointment_repository.py::get_in_salon`
  (renvoie l'`Appointment` avec ses `BookedService` — chacun portant `price_at_booking`) et
  `application/ports/service_repository.py::find_by_id(salon_id, service_id)` (renvoie le `Service`,
  champ `price`, filtre `salon_id`, prestation active). **Patron déjà utilisé par #29/#30/#31** pour
  agréger les montants figés.
- **Écriture + audit dans la même Session** : `get_session` mis en cache par requête (FastAPI) → dépôts
  métier et `SqlAuditLog` partagent la même `Session` → commit/rollback atomique. **Patron identique à
  #17/#20/#28/#32** et déjà appliqué dans `RecordPayment`.
- **Isolation §11.2 en profondeur** : routes imbriquées sous `/salons/{salon_id}/…`
  (`require_salon_scope`), dépôts refiltrant sur `salon_id` ; `403` **générique et constant** hors
  périmètre ; référence d'un autre salon **indiscernable** d'une référence inexistante. L'invariant
  deny-by-default est vérifié par `unprotected_routes(app)` dans `tests/test_security_guards.py`.
- **Tests** : fakes en mémoire dans `tests/conftest.py` ; tests d'API via `TestClient` +
  `app.dependency_overrides` ; e2e adossés à un vrai PostgreSQL (sautés si `DATABASE_URL` absent),
  données réservées et nettoyage avant/après.

### Web gérant — patrons à réutiliser (fiche client #28/#32)

- **Domaine/types** `src/domain/<x>/<x>.ts`, **port** `src/application/ports/<x>-gateway.ts`,
  **gateway HTTP** `src/adapters/api/http-<x>-gateway.ts` renvoyant une **union discriminée**
  (`{ ok:true, … } | { ok:false, reason:… }`, **jamais** d'exception réseau brute, **jamais** le jeton
  dans le résultat), **BFF** `app/api/salons/[id]/…/route.ts` (lecture du cookie `httpOnly` **côté
  serveur**), **UI** sous `app/(gerant)/gerant/…` + formulaire client-side `src/adapters/ui/…` avec
  `router.refresh()` au succès. **Modèle direct** pour l'écran d'enregistrement d'un paiement.
- **Navigation** : `src/domain/navigation/sections.ts` — basculer `encaissements` de `coming-soon` à
  `available`.

### Schéma déjà en place (source de vérité : `models.py`, migration `0001`)

- `payments` : `amount NUMERIC(12,2)` (`CHECK amount >= 0`), `payment_method` (`enum_check`), `status`
  (défaut `PENDING`, imposé `VALIDATED` par le cas d'usage), `recorded_by` **NOT NULL**, FK composites
  `(salon_id, appointment_id) → appointments` et `(salon_id, service_id) → services` (`RESTRICT`),
  `CHECK (appointment_id IS NOT NULL OR service_id IS NOT NULL)`, `UNIQUE(salon_id, id)`.
- `services.price NUMERIC(12,2)` (`CHECK price >= 0`) — prix courant de la prestation.
- `appointment_services.price_at_booking NUMERIC(12,2)` (`CHECK price_at_booking >= 0`) — **prix figé**
  à la réservation, base du « montant attendu » d'un RDV.

### Contraintes transverses documentées

- **PRD §5.3** : vérifier que le montant correspond à la prestation ; transaction au journal ; tableau
  de bord mis à jour (M5).
- **PRD §8.2** : paiement lié à prestation/RDV ; montant + mode + **utilisateur responsable** ;
  cohérence du montant.
- **PRD §11.2** : un gérant ne voit que **son** salon. **§11.3** : non-fuite PII, collecte minimale.
  **§11.4** : « Paiement enregistré » journalisé. **§12.1** : réponse API < 3 s.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA**. **Test gate** :
  `scripts/test-gate.sh` (pytest + npm test + flutter test) ; CI `ci.yml` (ruff, pytest, round-trip
  Alembic PostgreSQL 16, lint/test/build web).

## Proposed Implementation

### (A) Backend — domaine : règle de cohérence du montant

- **`domain/payment.py`** : ajouter une fonction pure **`validate_amount_matches`** (nom indicatif) :
  `validate_amount_matches(amount: Decimal, expected: Decimal) -> None` qui **compare** le montant validé
  au montant attendu (égalité stricte au centime, en `Decimal` quantifié à `0.01`) et lève
  **`PaymentAmountMismatch`** (nouvelle erreur) si différent. Message **neutre**, sans reprendre les
  valeurs (§11.3) : « Le montant ne correspond pas à la prestation. »
  - Optionnellement, un helper **`expected_amount_for_appointment(booked_services) -> Decimal`** qui
    somme les `price_at_booking` (le calcul reste **pur**, l'entité `Appointment`/`BookedService` du
    domaine étant déjà fournie par le port).
- **`domain/errors.py`** : ajouter **`PaymentAmountMismatch`** (et, si l'on choisit un `422` distinct
  pour référence introuvable, **`PaymentReferenceNotFound`** — voir *Open Questions* §4). Messages
  métier et neutres.

### (B) Backend — cas d'usage : `RecordPayment` étendu

- **`application/payments.py::RecordPayment`** : injecter deux dépôts supplémentaires —
  `appointment_repo: AppointmentRepository` et `service_repo: ServiceRepository` — et, **après** la
  validation domaine de base (montant borné, mode, référence présente) mais **avant** l'écriture :
  1. **résoudre le montant attendu** :
     - si `appointment_id` fourni : `appt = appointment_repo.get_in_salon(appointment_id, salon_id)` ;
       `None` → `PaymentReferenceNotFound` (aucune écriture, aucun audit) ; sinon `expected =
       somme(price_at_booking des BookedService)` ;
     - sinon (`service_id` seul) : `svc = service_repo.find_by_id(salon_id, service_id)` ; `None` (ou
       inactive) → `PaymentReferenceNotFound` ; sinon `expected = svc.price` ;
  2. **`validate_amount_matches(amount, expected)`** → `PaymentAmountMismatch` si incohérent (aucune
     écriture, aucun audit) ;
  3. poursuivre **exactement** le flux existant : `payment_repo.create(...)` (`VALIDATED`) →
     `cash_journal_repo.append(PAYMENT, +montant, …)` → `audit.record(PAYMENT_RECORDED, metadata={})`,
     même Session.
- **Ordonnancement** : toute la résolution/validation précède la première écriture — un paiement
  incohérent ne laisse **aucune** trace (ni `payments`, ni `cash_journal`, ni `audit_logs`).
- **`__all__`** inchangé (mêmes symboles publics `PaymentCommand`, `RecordPayment`).

### (C) Backend — adapter entrant (HTTP)

- **`adapters/inbound/payments.py::record_payment`** : injecter les nouveaux dépôts
  (`get_appointment_repository`, `get_service_repository` — providers analogues aux existants, adossés à
  `get_session`) et étendre le `try/except` : `PaymentAmountMismatch → 422` (ajouté à
  `_VALIDATION_ERRORS` **ou** mappé explicitement), `PaymentReferenceNotFound → 422` (ou `404`, voir
  *Open Questions* §4). **Aucun** changement de contrat de la route (`CreatePaymentRequest`,
  `PaymentResponse` inchangés) ; documentation `responses` mise à jour (motifs `422`).
- **Aucune** route destructive ; **aucun** ajout à `PUBLIC_ROUTE_PATHS`.

### (D) Web gérant — écran « Enregistrer un paiement »

1. **Domaine/types** — `src/domain/payments/payment.ts` : type `PaymentDraft` (`amount`,
   `paymentMethod`, `appointmentId?`, `serviceId?`, `clientId?`, `reference?`), type `Payment` (réponse),
   enum des modes de paiement (miroir de `PaymentMethod`), helpers de formatage XOF.
2. **Port & gateway** — `src/application/ports/payment-gateway.ts` (`record(draft)`), et
   `src/adapters/api/http-payment-gateway.ts` : union discriminée `{ ok:true, payment } | { ok:false,
   reason:"forbidden"|"unauthenticated"|"invalid"|"amount-mismatch"|"reference-not-found"|"unavailable" }`
   (mappe `201`/`401`/`403`/`422`) ; **jamais** le jeton dans le résultat, **jamais** d'exception réseau
   brute.
3. **BFF** — `app/api/salons/[id]/payments/route.ts` (`POST`) : lit le cookie `httpOnly` **côté
   serveur**, appelle la gateway, renvoie un corps **neutre** en cas d'erreur (jamais le jeton, jamais
   de détail réseau).
4. **UI** — `app/(gerant)/gerant/encaissements/page.tsx` (Server Component) : point d'entrée
   « Encaissements » ; **formulaire** client-side `src/adapters/ui/record-payment-form.tsx` : choix du
   RDV/prestation à encaisser, **montant pré-rempli** au prix attendu (aide à la cohérence ; la source
   de vérité reste le backend, qui rejette tout écart), mode de paiement, référence optionnelle ;
   `POST` au BFF, message d'erreur clair sur `amount-mismatch`/`reference-not-found`, `router.refresh()`
   au succès.
5. **Navigation** — `src/domain/navigation/sections.ts` : `encaissements` `coming-soon → available`.

> **Coordination avec #34 (déjà livré backend, web non fait).** L'écran `encaissements` accueille
> naturellement **et** l'enregistrement (#33) **et** la future vue journal + correction (#34, dont le
> backend existe déjà). #33 crée la page ; si #34 (web) reste à faire, #33 peut y laisser un point
> d'entrée « Journal de caisse » ou le déléguer à #34 — à trancher (voir *Open Questions* §6). #33 ne
> doit **pas** dupliquer la logique journal/correction déjà présente côté backend.

### (E) ADR — cohérence du montant

Ajouter `docs/adr/00XX-encaissement-coherence-montant.md` : figer la **règle de cohérence** (égalité
stricte au MVP ; acompte/partiel différé), la **source du montant attendu** (somme des
`price_at_booking` pour un RDV ; `Service.price` pour une prestation seule), le **code HTTP** de
référence introuvable (`422` recommandé), et le rappel que la tranche d'enregistrement a été **livrée
comme socle de #34**. Mettre à jour `docs/adr/README.md`.

## Affected Files / Packages / Modules

### Backend (`backend/`) — à modifier / créer

| Fichier | Modification |
| --- | --- |
| `coiflink_api/domain/payment.py` | **+** `validate_amount_matches` (+ helper somme `price_at_booking`) |
| `coiflink_api/domain/errors.py` | **+** `PaymentAmountMismatch` (+ `PaymentReferenceNotFound` selon §4) |
| `coiflink_api/application/payments.py` | `RecordPayment` : injecter `AppointmentRepository`/`ServiceRepository`, résoudre le montant attendu, valider la cohérence **avant** écriture |
| `coiflink_api/adapters/inbound/payments.py` | providers `get_appointment_repository`/`get_service_repository`, mapping `PaymentAmountMismatch`/`PaymentReferenceNotFound` → `422` (ou `404`), `responses` OpenAPI |
| `tests/conftest.py` | fakes `FakeAppointmentRepository`/`FakeServiceRepository` réutilisés ou complétés (renvoyer prix figés / `Service.price`) |
| `tests/test_domain_payment.py` | **+** cas `validate_amount_matches` (égal, différent, quantification centime) |
| `tests/test_payments_usecases.py` | **nouveau** — `RecordPayment` : RDV cohérent/incohérent, prestation seule cohérente/incohérente, référence hors salon/inconnue, aucune écriture/audit sur échec |
| `tests/test_payments_api.py` | **nouveau** — `201`/`401`/`403`/`422` (montant incohérent, référence introuvable, `recorded_by` du corps ignoré) |
| `tests/test_payments_e2e.py` | **nouveau** — parcours PostgreSQL : RDV terminé + montant = somme `price_at_booking` → `201` + ligne `PAYMENT` ; montant faux → `422` sans trace ; isolation inter-salons |
| `tests/test_security_guards.py` | vérifier que `POST …/payments` reste protégée et non publique (déjà couvert ; réaffirmer) |
| `backend/README.md` | section « Encaissement » : règle de cohérence du montant, `curl` d'exemple |

### Backend — à lire (sans modifier) pour rester fidèle aux patrons

`application/customers.py`/`application/appointments.py` (résolution salon-scopée), `domain/appointment.py`
(`BookedService`, `price_at_booking`), `domain/service.py`, `adapters/outbound/persistence/{appointment,service}_repository.py`,
`adapters/inbound/security.py`, `models.py` (`Payment`, `Service`, `AppointmentService`).

### Web (`web-dashboard/`)

À créer : `src/domain/payments/payment.ts`, `src/application/ports/payment-gateway.ts`,
`src/adapters/api/http-payment-gateway.ts`, `app/api/salons/[id]/payments/route.ts`,
`app/(gerant)/gerant/encaissements/page.tsx`, `src/adapters/ui/record-payment-form.tsx`, tests `vitest`
associés. À modifier : `src/domain/navigation/sections.ts` (`encaissements → available`),
`web-dashboard/README.md`.

### Documentation (racine)

`README.md` (§6 : statut « M4 : enregistrement d'un paiement (US-5.1, #33) »), nouvel ADR
`docs/adr/00XX-encaissement-coherence-montant.md` + index `docs/adr/README.md`.

## API / Interface Changes

**Aucun nouvel endpoint.** La route `POST /salons/{salon_id}/payments` **existe déjà** (livrée avec
#34) ; #33 **renforce sa validation** (cohérence du montant) sans changer son contrat de requête/réponse.

| Méthode | Chemin | Garde | Réponses |
| --- | --- | --- | --- |
| `POST` | `/salons/{salon_id}/payments` | `PAYMENT_RECORD` + portée | `201` paiement · `401` · `403` · `422` **montant borné invalide, mode/devise invalides, référence absente, _montant incohérent (nouveau)_, référence introuvable (nouveau)** |

```jsonc
// POST /salons/{salon_id}/payments — corps (inchangé)
{
  "amount": "5000.00",              // doit correspondre au prix de la prestation/RDV (nouveau contrôle)
  "payment_method": "CASH",         // PaymentMethod : CASH | MOBILE_MONEY_MANUAL | CARD_MANUAL | OTHER
  "appointment_id": "…uuid… | null",// prestation OU rdv requis (§8.2)
  "service_id": "…uuid… | null",
  "client_id": "…uuid… | null",     // optionnel
  "reference": "REC-2026-0001",     // optionnel, borné
  "currency": "XOF"                 // optionnel, mono-devise
}

// 422 — nouveau motif d'incohérence de montant (message neutre, sans valeur)
{ "detail": "Le montant ne correspond pas à la prestation." }
```

- `recorded_by`/`status`/`id`/`created_at` **ne sont jamais** lus du corps (déjà en place).
- **Interface web (BFF, interne à Next.js)** : `POST /api/salons/[id]/payments`. Aucune modification de
  CLI, de variable d'environnement ou de contrat inter-paquet.

## Data Model / Protocol Changes

**Aucune.** Les tables `payments`/`cash_journal`, leurs contraintes (`CHECK amount >= 0`,
`CHECK ref_present`, `enum_check`, FK `RESTRICT`, `UNIQUE(salon_id, id)`) et les enums existent depuis la
migration `0001`. #33 **lit** `services.price` et `appointment_services.price_at_booking` (déjà en base)
pour dériver le montant attendu, et **écrit** dans `payments`/`cash_journal`/`audit_logs` par le chemin
existant. Aucune colonne, table, index ni sérialisation nouvelle.

## Security & Privacy Considerations

- **Intégrité du montant (§5.3/§8.2), cœur de #33.** Le montant est désormais **borné au prix réel** de
  la prestation/RDV : on ne peut plus enregistrer un montant arbitraire décorrélé de la prestation. La
  source du montant attendu est le **prix figé** (`price_at_booking`) ou le `Service.price` **du salon**
  — jamais une valeur soumise par le client de l'API.
- **Auteur & horodatage non falsifiables (déjà en place).** `recorded_by` vient **toujours** du
  `Principal` ; `created_at` est **serveur** (`server_default`, timezone-aware). Non-répudiation
  préservée.
- **Isolation par salon (§11.2), en profondeur.** `require_salon_scope` sur la route **et** filtres
  `salon_id` des dépôts (`get_in_salon`, `find_by_id`, `create`) ; une prestation/un RDV d'un autre
  salon est **indiscernable** d'un identifiant inexistant (pas d'oracle) et produit une erreur métier
  neutre. Aucun montant d'un autre salon n'est jamais lu.
- **Permissions §4.1 sans élargissement.** `PAYMENT_RECORD` reste détenue par le **seul `MANAGER`** ;
  `ROLE_PERMISSIONS` n'est pas modifiée. Ni `CLIENT`, ni `HAIRDRESSER`, ni `ADMIN` n'encaissent.
- **Audit neutre, sans PII ni montant (§11.3/§11.4, ADR-0019).** `PAYMENT_RECORDED` porte
  `actor_user_id`, `salon_id`, `entity_type`, `entity_id` et **`metadata = {}`** — **ni** montant,
  **ni** mode, **ni** identité client. Le détail financier vit dans `payments` (accès borné par
  permission), pas dans `audit_logs`. Un test l'exige explicitement.
- **Non-fuite dans logs / messages.** Aucun `print`/`logger` ne reçoit de montant, de mode ni de PII
  client ; les messages `4xx` restent **métier et neutres** (jamais la valeur du montant ni le prix
  attendu). Le BFF/gateway web ne journalisent jamais le jeton ni l'en-tête `Authorization`.
- **Atomicité écriture + audit (déjà en place).** `INSERT payments`, `INSERT cash_journal` (`PAYMENT`)
  et `AuditEntry` partagent la **même** Session (`flush()` sans `commit()`) : tout ou rien. Un paiement
  incohérent est rejeté **avant** toute écriture — aucune trace partielle.
- **Jeton jamais exposé côté web (#14).** Page et Route Handler BFF lisent le cookie `httpOnly` **côté
  serveur** ; le jeton ne transite jamais vers le navigateur et n'est jamais journalisé.

Le dépôt **documente** ces contraintes (PRD §5.3/§8.2/§11.2/§11.3/§11.4, ADR-0015/0019) : #33 les
respecte sans en affaiblir aucune et **renforce** §8.2 (cohérence du montant).

## Testing Plan

### Backend — unitaires (`pytest`, sans I/O, fakes de `conftest.py`)

- **`tests/test_domain_payment.py`** (étendre) : `validate_amount_matches` — montants égaux → OK ;
  différents → `PaymentAmountMismatch` ; quantification au centime (p. ex. `100.00` vs `100.001`
  déjà exclu par `validate_amount`, mais vérifier l'égalité `Decimal` stricte) ; message neutre.
- **`tests/test_payments_usecases.py`** (nouveau) : `RecordPayment` —
  - **RDV cohérent** : montant = somme des `price_at_booking` → crée `Payment` (`VALIDATED`), **une**
    ligne `PAYMENT` (`transaction_id = payment.id`, `performed_by = acteur`), **une** `AuditEntry`
    `PAYMENT_RECORDED` (`metadata == {}`), même unité de travail ;
  - **RDV incohérent** : montant ≠ somme → `PaymentAmountMismatch`, **aucune** écriture ni audit ;
  - **prestation seule cohérente/incohérente** : montant vs `Service.price` ;
  - **référence hors salon / inconnue** (`get_in_salon`/`find_by_id` renvoient `None`) →
    `PaymentReferenceNotFound`, **aucun** audit ;
  - **`recorded_by` toujours = acteur** (jamais dérivé d'un champ) ; `status == VALIDATED`.
- **`tests/test_domain_audit.py`** (si besoin) : `PAYMENT_RECORDED` / `ENTITY_TYPE_PAYMENT` déjà
  couverts par #34 — réaffirmer.

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_payments_api.py`** (nouveau) : `POST …/payments` —
  - `201` + `PaymentResponse` (montant cohérent) ;
  - `422` montant incohérent (message **neutre**, **sans** valeur) ; `422` référence introuvable ;
    `422` référence absente (les deux `null`) ; `422` mode/devise invalides ;
  - corps portant `recorded_by`/`status`/`id`/`created_at` → **ignorés** ;
  - `403` rôle ≠ `MANAGER` / hors portée (message **constant**) ; `401` sans jeton.
- **`tests/test_security_guards.py`** : `unprotected_routes(app)` couvre `POST …/payments` ; **aucun**
  chemin paiement dans `PUBLIC_ROUTE_PATHS`.

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_payments_e2e.py`** (nouveau, patron existant : données réservées, nettoyage
  avant/après) :
  1. inscription gérant → connexion → salon → prestation → RDV (avec `price_at_booking`) →
     **enregistrement d'un paiement** au montant = somme des `price_at_booking` → `201` ; le journal
     contient **une** ligne `PAYMENT` (auteur = gérant, horodatée) ; `audit_logs` porte
     `PAYMENT_RECORDED` avec `metadata` **vide** ;
  2. **montant incohérent** → `422`, **aucune** ligne `payments`/`cash_journal`/`audit_logs` créée ;
  3. **isolation inter-salons** : le jeton du gérant B est refusé (`403` générique) et ne peut
     référencer un RDV/prestation du salon de A (`422` référence introuvable, sans oracle) ;
  4. deny-by-default : sans jeton → `401`.

### Web (`vitest`)

- `test/http-payment-gateway.test.ts` : mapping `record` (`201 → ok`, `403 → forbidden`,
  `401 → unauthenticated`, `422 → invalid/amount-mismatch/reference-not-found`), en-tête `Authorization`
  posé, **jeton jamais** dans le résultat.
- `test/payments-bff.test.ts` : `401` sans cookie ; erreurs propagées avec message **neutre** ;
  **aucune PII/montant/jeton** dans les réponses.
- `test/record-payment-form.test.tsx` : montant pré-rempli, soumission, message d'erreur sur
  `amount-mismatch`, `router.refresh()` au succès.

### Documentation / non-régression

`scripts/test-gate.sh` (pytest + npm test + **flutter test inchangé** — l'encaissement n'est jamais
exposé au client mobile) au vert ; `ruff check` propre ; `npm run lint && npm run build` (standalone)
inchangé.

## Documentation Updates

- **`backend/README.md`** — section « Encaissement » : `POST …/payments` (permission `PAYMENT_RECORD`,
  portée §11.2), **règle de cohérence du montant** (somme des `price_at_booking` pour un RDV ;
  `Service.price` pour une prestation seule ; égalité stricte au MVP), ligne `PAYMENT` au journal,
  audit `PAYMENT_RECORDED` **sans PII**, exemples `curl` (cas cohérent → `201`, incohérent → `422`).
- **`web-dashboard/README.md`** — section « Encaissements » : écran d'enregistrement (montant
  pré-rempli, mode, référence), BFF (`app/api/salons/[id]/payments`), cookie `httpOnly` +
  `router.refresh()`.
- **`README.md`** (racine) — §6 : phrase de statut « M4 : enregistrement d'un paiement (US-5.1, #33) —
  paiement `VALIDATED` lié à un RDV/prestation, **montant vérifié cohérent** avec la prestation, inscrit
  au journal de caisse et journalisé (`PAYMENT_RECORDED`) » dans le style existant. Corriger la mention
  « L'encaissement (#33+) reste à venir » (obsolète).
- **`docs/adr/`** — **nouvel ADR** « Encaissement — cohérence du montant & enregistrement d'un
  paiement » (règle d'égalité stricte vs acompte, source du montant attendu, code HTTP de référence
  introuvable, rappel du socle livré avec #34). Mettre à jour `docs/adr/README.md`.
- **OpenAPI** — `responses`/docstrings de `record_payment` documentent les nouveaux motifs `422`.

## Risks and Open Questions

1. **La tranche d'enregistrement est déjà livrée (socle de #34).** *Recommandation : #33 se limite au
   **manque réel** — cohérence du montant (backend) + écran gérant (web) — sans réécrire l'existant.*
   Vérifier, **avant** d'implémenter, que `POST …/payments`, `RecordPayment` et les tests associés sont
   toujours en place et que #34 (web) n'a pas déjà créé la page `encaissements`.
2. **Cohérence quand `appointment_id` **et** `service_id` sont fournis.** *Recommandation : privilégier
   le **RDV** (référence la plus complète) et exiger que `service_id` fasse partie des prestations du
   RDV ; sinon `422`.* À figer (l'ADR devrait trancher). Alternative : refuser la double référence.
3. **Égalité stricte vs paiement partiel/acompte.** *Recommandation MVP : **égalité stricte** au
   centime* (simple, conforme à « le montant correspond à la prestation »). Autoriser `0 < montant <=
   attendu` (acompte) est une évolution ; ne pas l'implémenter sans décision consignée. Impacte aussi
   #36 (écarts) et #38 (reçu).
4. **Code HTTP pour une référence introuvable.** *Recommandation : `422`* (donnée de requête invalide,
   cohérent avec les autres refus de validation du paiement et **sans oracle** d'existence inter-salons).
   Alternative : `404`. À trancher et documenter.
5. **Prestation inactive / prix modifié depuis la réservation.** Pour un **RDV**, utiliser
   `price_at_booking` (prix **figé**) évite l'ambiguïté d'un `Service.price` modifié entre-temps. Pour
   une **prestation seule** (sans RDV), le prix courant `Service.price` s'applique — exiger la
   prestation **active** (`find_by_id` filtre déjà l'actif). À confirmer.
6. **Frontière web #33 ↔ #34.** Le backend #34 (journal + correction) est livré mais **son web ne l'est
   pas**. *Recommandation : #33 crée la page `encaissements` avec l'enregistrement ; la vue journal +
   correction (web) revient à #34* (ou est ajoutée ici si l'orchestrateur préfère grouper). Éviter de
   dupliquer la logique journal/correction déjà présente côté backend.
7. **ADR d'encaissement.** *Recommandation : oui* — figer la règle de cohérence, la source du montant
   attendu et le partage #33/#34, comme ADR-0019/0026. **À confirmer** avec l'équipe.
8. **Dérivation du `client_id`.** Optionnel au schéma. *Recommandation : le pré-remplir depuis le
   `client_id` du RDV lié quand il existe* (traçabilité), sans jamais l'imposer ni le lire d'un champ
   privilégié. À aligner à l'implémentation.
9. **Devise.** Mono-devise XOF déjà garantie par `validate_currency`. #33 n'introduit pas de
   multi-devise ; la cohérence de montant se fait dans la même devise.

## Implementation Checklist

1. **Vérifier l'état livré** : relire `adapters/inbound/payments.py`, `application/payments.py`,
   `domain/payment.py`, `payment_repository.py`, `tests/test_domain_payment.py` (socle #34) et confirmer
   que le seul manque backend est la **cohérence du montant** ; vérifier que `web-dashboard`
   `encaissements` est bien `coming-soon` et sans page. **Trancher** les questions ouvertes 2–7 ;
   consigner dans un **ADR**.
2. **Lire** `domain/appointment.py` (`BookedService`, `price_at_booking`), `domain/service.py`,
   `application/ports/{appointment,service}_repository.py`, `adapters/outbound/persistence/{appointment,service}_repository.py`,
   `adapters/inbound/security.py`, `models.py` (`Payment`, `Service`, `AppointmentService`).
3. **Domaine** : ajouter `validate_amount_matches` (+ helper somme `price_at_booking`) à
   `domain/payment.py` ; ajouter `PaymentAmountMismatch` (et `PaymentReferenceNotFound` selon §4) à
   `domain/errors.py` ; étendre `tests/test_domain_payment.py`.
4. **Cas d'usage** : injecter `AppointmentRepository`/`ServiceRepository` dans `RecordPayment` ;
   résoudre le montant attendu (RDV = somme `price_at_booking` ; prestation = `Service.price`) et valider
   la cohérence **avant** toute écriture ; conserver le flux existant (création → ligne `PAYMENT` →
   audit `PAYMENT_RECORDED` `metadata={}`, même Session).
5. **Fakes & tests applicatifs** : compléter `FakeAppointmentRepository`/`FakeServiceRepository` dans
   `tests/conftest.py` ; écrire `tests/test_payments_usecases.py` (cohérent/incohérent, prestation
   seule, référence hors salon/inconnue, aucune trace sur échec).
6. **Adapter entrant** : providers `get_appointment_repository`/`get_service_repository` ; mapper
   `PaymentAmountMismatch`/`PaymentReferenceNotFound` → `422` (ou `404`) ; enrichir `responses` OpenAPI.
   Écrire `tests/test_payments_api.py` et réaffirmer `tests/test_security_guards.py`.
7. **e2e** : `tests/test_payments_e2e.py` (RDV cohérent → `201` + ligne `PAYMENT` + audit sans PII ;
   incohérent → `422` sans trace ; isolation inter-salons ; `401`). Exécuter `pytest` (+ `DATABASE_URL`)
   et `ruff check`.
8. **Web — domaine/port/gateway** : `src/domain/payments/payment.ts`,
   `src/application/ports/payment-gateway.ts`, `src/adapters/api/http-payment-gateway.ts`
   (+ `test/http-payment-gateway.test.ts`).
9. **Web — BFF** : `app/api/salons/[id]/payments/route.ts` (`POST`, cookie `httpOnly` côté serveur)
   (+ `test/payments-bff.test.ts`).
10. **Web — UI** : `app/(gerant)/gerant/encaissements/page.tsx` +
    `src/adapters/ui/record-payment-form.tsx` (montant pré-rempli, message `amount-mismatch`,
    `router.refresh()`) ; basculer `encaissements` en `available` dans `src/domain/navigation/sections.ts`.
11. **Documentation** : sections `backend/README.md` / `web-dashboard/README.md` ; phrase de statut
    `README.md` racine (corriger « #33+ reste à venir ») ; ADR + index.
12. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test + **flutter test
    inchangé**), `ruff check`, `npm run lint && npm run build` ; relire la PR pour garantir qu'**aucun
    montant, prix attendu ou PII** n'apparaît dans les logs, l'audit ou les messages d'erreur,
    qu'**aucune** route destructive n'est ajoutée, que le paiement n'est **jamais** exposé au client
    mobile, et qu'**aucune signature IA** n'a été introduite.
