# Dashboard Manager — Activité du salon (extension/consolidation Épic 6) (#148)

> Spécification de planification pour l'issue GitHub **#148 — Dashboard Manager · Activité du salon**
> (`feature` · **Must** · Effort **L** · PRD §6 Épic 6 (extension) / §7.2 « Dashboard principal » /
> §8.1 / §8.4 / §11.2 / §11.3 / §11.4 / §12.1 / §12.2).
> **Dépend de #39** (RDV du jour, livré), **#40** (chiffre d'affaires jour/semaine/mois, livré) et
> **#42** (clients actifs, livré) selon le backlog. **Consolide/étend** la base dashboard déjà livrée
> (#39/#40/#41/#42/#43) — elle **ne repart pas de zéro** : elle réutilise le router `stats`
> (`adapters/inbound/stats.py`), les patrons d'agrégat salon-scopé « en base », le `http-stats-gateway`
> et les composants `daily-summary-tiles.tsx` / `revenue-tiles.tsx` / `active-clients-panel.tsx`.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW), identifiants
> techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés. **Aucune signature
> IA** dans le code, les commits ou la PR. **Cette spec ne produit pas de code** : elle décrit
> l'approche à implémenter dans une phase ultérieure et **lève** les ambiguïtés signalées par l'issue
> **avant** le code (aucun mock en implémentation).

## Problem Statement

Le PRD pose deux besoins distincts que #148 réunit :

- **§6 Épic 6 (« Tableau de bord »)** — vue **analytique** du gérant : RDV du jour (US-6.1),
  chiffre d'affaires (US-6.2), prestations demandées (US-6.3), clients actifs (US-6.4), performance
  coiffeurs (US-6.5). Ces cinq briques sont **livrées** (#39–#43).
- **§7.2 (« Dashboard principal »)** — l'**écran** gérant, qui liste comme indicateurs :
  « Rendez-vous du jour. / Chiffre d'affaires du jour. / Nombre de clients. / Prestations populaires. /
  **Transactions récentes.** / **Alertes importantes.** »

L'issue #148 demande un **Dashboard Manager d'activité du salon** consolidé, « en temps réel », avec :
quatre **cartes KPI** (clients en attente, prestations en cours, chiffre d'affaires, nombre de clientes
— chacune avec **évolution**), un **filtre de période** (aujourd'hui / semaine / mois / personnalisée),
deux **graphiques** (évolution du CA, fréquentation), une **liste des prestations en cours**, une
**timeline des dernières activités**, des **alertes importantes**, et une **actualisation automatique**.

### Écart entre la demande et le socle réel (établi par lecture du code et du PRD)

Plusieurs notions demandées **n'existent pas** dans le modèle MVP et doivent être **définies avant le
code** — c'est l'objet central de cette spec :

1. **Aucun statut `IN_PROGRESS`.** `domain/enums.py::AppointmentStatus` a exactement cinq valeurs :
   `PENDING / CONFIRMED / CANCELLED / COMPLETED / NO_SHOW` (PRD §9.4). La table `appointments`
   **n'a aucune** colonne d'horodatage d'arrivée / de début / de fin (`arrived_at`, `started_at`,
   `finished_at` **n'existent pas**). « Prestations en cours » n'a donc **aucune** représentation
   stockée — elle doit être **dérivée** ou nécessiterait une nouvelle valeur d'énum + une mécanique de
   pointage (migration + machine à états + action). Le seul endroit du PRD qui définit un statut
   « en cours » est la **Borne Intelligente §17** (`en attente / appelé / en cours / terminé`),
   **explicitement hors MVP** (§21) ; « Gestion d'attente simple » est **Could Have** (§22).
2. **Aucune notion de file d'attente / salle d'attente / walk-in en salle.** « Clients en attente »
   n'a pas de source dédiée. Les concepts « file d'attente » du PRD relèvent tous du **QR code de
   présence §16.7** et de la **Borne §17** — hors MVP.
3. **Aucune librairie de graphiques.** `web-dashboard/package.json` ne contient que
   `next` / `react` / `react-dom` (aucune dépendance de charting). L'ajout d'une librairie serait une
   **décision de dépendance à justifier**.
4. **Aucun mécanisme de rafraîchissement automatique.** Une recherche exhaustive du backend
   (`websocket|SSE|EventSource|StreamingResponse|poll|BackgroundTasks`) renvoie **zéro** occurrence :
   le backend est un service **requête/réponse** pur. Le web `/gerant` est **rendu serveur uniquement**
   (Server Component, pas de rafraîchissement). Polling/SWR/websocket sont **greenfield**.
5. **Le filtre de période « aujourd'hui / semaine / mois / personnalisée » n'existe pas.** Les endpoints
   stats ont des paramètres hétérogènes : #40 (`date` → dérive jour/semaine/mois côté serveur), #41/#42/
   #43 (`date_from`/`date_to` optionnels). Le filtre `date_from`/`date_to` unifié n'existe que sur
   `/encaissements` (#35).
6. **La liste des RDV du salon ne porte aucun nom.** `GET /salons/{id}/appointments` (#26) renvoie des
   **UUID nus** (`client_id`, `hairdresser_id`, `service_id`) — jamais de nom de cliente, de prestation
   ni de professionnelle. La « liste des prestations en cours » (qui demande *cliente · prestation ·
   professionnelle · heure de début · statut*) exige une **nouvelle lecture résolvant les noms**
   (jointures `users` ×2 + `services`), sur le patron déjà présent de `performance_by_hairdresser` (#43)
   et de `payment_repository.list_for_salon` (#35).
7. **Il n'existe aucun journal d'évènements applicatifs unifié.** Les ports `AuditLog` et
   `NotificationRepository` sont **en écriture seule** (`record()` / `enqueue()` — aucune méthode de
   lecture). Les seules sources **réellement horodatées** exploitables pour une « timeline » sont :
   `payments.created_at` (avec nom de client résolu), `appointments.created_at` (nouvelle réservation),
   `notifications.created_at` (`NEW_BOOKING`/`CANCELLATION`/`APPOINTMENT_UPDATE`, texte **neutre** sans
   PII, ADR-0006) et `cash_journal.created_at`. **« Arrivée cliente », « début » et « fin » de
   prestation n'ont AUCUNE source** (pas d'horodatage de transition ni de pointage).

Le gap que #148 comble : un **écran d'activité consolidé** au-dessus du socle KPI existant, dont chaque
donnée est **définie sur des faits réels** (aucun mock), avec un filtre de période unifié, des
graphiques, des vues opérationnelles (prestations en cours, activités récentes, alertes) **bornées à ce
que le modèle sait produire**, et une actualisation automatique **cohérente avec le budget §12.1**.

## Goals

- **Lever les ambiguïtés #1–#7 avant le code**, avec des définitions dérivées de faits réels (voir
  *Proposed Implementation* et l'**ADR-0039** recommandé). En particulier :
  - **« Prestations en cours »** = RDV `CONFIRMED` dont le créneau `[appointment_date+start_time,
    appointment_date+end_time]` **contient l'instant présent** (`Africa/Abidjan`, UTC+0), **sans**
    nouveau statut ni migration.
  - **« Clients en attente »** = RDV `PENDING` (demandes **non encore confirmées** par le gérant) sur
    la période — la source « queue » la plus proche existante ; **aucune** salle d'attente walk-in
    (hors MVP §17).
  - **Filtre de période** = `Aujourd'hui | Semaine | Mois | Personnalisée`, résolu **côté serveur** en
    bornes de jour civil `[date_from, date_to]` (réutilise `day_bounds`/`week_bounds`/`month_bounds` de
    `domain/revenue.py`) ; **évolution** = comparaison à la **période précédente de même longueur**.
- **Afficher les 4 cartes KPI** (critère d'acceptation), chacune sur données réelles : clients en
  attente (+ évolution), prestations en cours (instantané), chiffre d'affaires (+ évolution), nombre de
  clientes (+ évolution). Les KPI de comptage/montant sont **agrégés en base** (`COUNT`/`SUM`) et
  **counts-only** (sans PII), sur le patron #39/#40/#42.
- **Rendre les données filtrables par période** (critère d'acceptation) via un sélecteur unifié qui
  pilote `date_from`/`date_to` côté serveur ; les endpoints existants (#40/#41/#42/#43) restent
  compatibles.
- **Ajouter deux graphiques** dérivés d'agrégats en base : **évolution du CA** (série temporelle du net
  `cash_journal`) et **fréquentation** (série temporelle du nombre de visites/RDV) — counts-only, sans
  PII. **Sans nouvelle dépendance** : rendu en **SVG inline** (Server Component), voir *Open Questions §4*.
- **Ajouter une liste des prestations en cours** (cliente · prestation · professionnelle · heure de
  début · statut), via une **nouvelle lecture résolvant les noms d'affichage** (`users.full_name`,
  `services.name`) — patron d'émission **maîtrisée** de #43 (nom d'affichage **uniquement**, jamais un
  contact ni une donnée client sensible).
- **Ajouter une timeline des dernières activités** (§7.2 « Transactions récentes ») **bornée aux faits
  réellement horodatés** : nouvelles réservations, paiements, annulations/modifications. **Documenter
  explicitement** que « arrivée cliente / début / fin de prestation » **ne sont pas** représentables
  au MVP (aucune source) et relèvent d'un pointage/borne différé (§17).
- **Ajouter des alertes importantes** (§7.2 « Alertes importantes ») **dérivées** de faits réels :
  **anomalie de paiement** = écart de caisse (#36, RDV `COMPLETED` sans paiement), **retard** = RDV
  `CONFIRMED` dont `start_time` est **dépassé** sans clôture (`COMPLETED`/`NO_SHOW`), **attente
  prolongée** = RDV `PENDING` du jour non confirmé au-delà d'un seuil. Aucune alerte inventée.
- **Actualiser automatiquement** les panneaux sensibles au temps (KPI, prestations en cours, timeline,
  alertes) par **polling client visibility-aware** (re-rendu serveur via `router.refresh()`), **sans**
  exposer le jeton (invariant #14) ni multiplier les appels superflus (§12.1) — voir *Open Questions §5*.
- **Gérer les états loading / empty / error** (critère d'acceptation) : skeletons au chargement, états
  vides explicites par panneau, **dégradation locale** d'un panneau en panne (patron #41 :
  `demand.ok ? … : null`) sans casser le reste du tableau de bord.
- **Réutiliser strictement `STATS_READ_SALON`** (déjà réservée au `MANAGER`, cinq consommateurs #39–#43)
  **+** `require_salon_scope` (isolation §11.2), **sans** modifier `ROLE_PERMISSIONS`. Toutes les
  nouvelles routes sont **protégées** (deny-by-default #12), **jamais** publiques.
- **Additif et rétro-compatible** : aucune signature existante modifiée, **aucune migration** de schéma
  (tout est dérivé en lecture des tables existantes ; le rejet du statut `IN_PROGRESS` évite toute
  migration).
- **Couverture de tests** : domaine (période/évolution, dérivation « en cours », dérivation alertes),
  cas d'usage, API (`200`/`401`/`403`/`422`, absence de PII sur les endpoints counts-only), e2e
  PostgreSQL ; web (filtre de période, cartes, graphiques SVG, listes, auto-refresh, états
  loading/empty/error, gateways).

## Non-Goals

- **Aucun statut `IN_PROGRESS` / `ARRIVED` ni pointage d'arrivée.** #148 **dérive** « en cours »
  (`CONFIRMED` ∩ créneau contient l'instant présent) — il n'ajoute **aucune** valeur d'énum, aucune
  colonne d'horodatage de transition, aucune migration, aucune machine à états. Un vrai suivi
  arrivée/début/fin (pointage, borne, QR §16.7/§17) est **hors MVP** (§21) — décision *Open Questions §1*.
- **Aucune file d'attente / salle d'attente / walk-in en salle.** « Clients en attente » = RDV
  `PENDING` ; aucune position dans une file, aucun temps d'attente estimé, aucun appel de client
  (concepts §17 borne, hors MVP).
- **Aucun horodatage de transition de statut ni event-sourcing.** La timeline se dérive des faits
  **déjà horodatés** (`payments`, `appointments.created_at`, `notifications`) — pas de nouvelle table
  d'évènements, pas de trigger, pas de journal d'activité persisté.
- **Aucune remise de notification.** #148 **lit** les faits ; il n'envoie rien (la remise push/SMS
  reste différée M5+, ADR-0006/0033–0037). L'actualisation « temps réel » est un **polling de lecture**,
  pas une file d'évènements poussés.
- **Aucun websocket / SSE / streaming serveur.** L'infrastructure temps-réel push est **greenfield**
  et hors périmètre (le backend reste requête/réponse). Le « temps réel » de #148 = **polling borné**
  côté client — *Open Questions §5*.
- **Aucune vue admin / inter-salons.** #148 est **salon-scopé** (`MANAGER`, son salon). Les KPI
  plateforme relèvent de l'admin (#37/#44).
- **Aucune modification de `ROLE_PERMISSIONS`** ni des droits `CLIENT`/`HAIRDRESSER`/`ADMIN`. Réutilise
  `STATS_READ_SALON`.
- **Aucune écriture / aucun audit §11.4.** Lecture pure (parité #39–#43) : consulter un KPI/une activité
  n'est pas une action journalisée.
- **Aucune statistique côté mobile.** `app-mobile/` **n'est pas** touché — #148 est un parcours gérant
  (web) uniquement.
- **Aucune régression des endpoints #39–#43** : ils restent en place et compatibles ; #148 **compose**
  au-dessus.

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Performance coiffeurs | Émission **maîtrisée** de `users.full_name` (nom d'affichage seul) | [0031](../docs/adr/0031-performance-des-coiffeurs.md) |
| Détection écarts de caisse | Lecture RDV `COMPLETED` sans paiement, `CASH_JOURNAL_READ` | [0028](../docs/adr/0028-detection-ecarts-de-caisse.md) |
| Web gérant | Next.js 16 (App Router, TS), cookie `httpOnly` + BFF, Server Components | [0002](../docs/adr/0002-web-gerant-admin-nextjs.md) |

`docs/adr/` s'arrête à **ADR-0038**. #39–#42 ont plié leurs décisions dans les README ; #43/#44 ont un
ADR (0031/0032). #148 introduit **plusieurs** décisions transverses (statut « en cours » dérivé,
définition « en attente », modèle de période, graphiques sans dépendance, mécanisme d'auto-refresh) et
**étend le périmètre au-delà de l'Épic 6 analytique** — un **ADR-0039** est **recommandé** (*Open
Questions §8*). Prochain numéro libre : **0039**.

### Backend — patrons à réutiliser tels quels

- **Router `stats` salon-scopé** — `adapters/inbound/stats.py`
  (`APIRouter(prefix="/salons", tags=["stats"])`) porte `revenue/summary` (#40), `service-demand`
  (#41), `active-clients` (#42), `hairdresser-performance` (#43), tous sous
  `require_salon_scope` + `require_permission(STATS_READ_SALON)`, avec DI `get_appointment_repository`
  / `get_cash_journal_repository` surchargeables en test. #148 **y ajoute des routes** (sixième+
  consommateur de `STATS_READ_SALON`) — **sans** créer de router (déjà monté dans `main.py`).
- **Agrégats salon-scopés « en base »** — `SqlAppointmentRepository` :
  `count_by_status_for_day` (#39, `GROUP BY status`), `demand_by_service` (#41), `segment_active_clients`
  (#42, `GROUP BY client_id` **jamais émis**), `performance_by_hairdresser` (#43, **join** `users` pour
  `full_name`). `list_for_salon(salon_id, date_from, date_to, statuses=None)` liste les RDV du salon sur
  une plage (planning #26) — **isolation §11.2 en SQL** (`WHERE salon_id`), index
  `ix_appointments_salon_id (salon_id, appointment_date)` — mais renvoie des `Appointment` **sans noms**.
- **CA net du journal de caisse** — `domain/revenue.py` (`day_bounds`/`week_bounds`/`month_bounds`,
  `RevenueSummary`) + `CashJournalRepository` : le CA = **somme signée** des lignes `cash_journal`
  `PAYMENT`/`ADJUSTMENT` (net des corrections #34) sur un intervalle. #148 réutilise ces bornes pour le
  filtre de période et la **série** temporelle du CA.
- **Écarts de caisse (#36)** — `PaymentRepository.list_completed_without_payment(...)` /
  `count_completed_without_payment(...)` (résout `client_id → users.full_name`) + `domain/discrepancy.py`
  (`CashDiscrepancy`, `DiscrepancyFilter`). Source directe de l'alerte « anomalie de paiement ».
- **Émission maîtrisée d'un nom d'affichage** — #43 (`performance_by_hairdresser`) et #36
  (discrepancies) émettent `users.full_name` **et rien d'autre** (jamais `phone`/`email`/`role`). Patron
  direct pour la « liste des prestations en cours » (cliente/professionnelle) — voir *Security*.
- **Gardes de sécurité** — `adapters/inbound/security.py` : `require_permission(Permission.X)` +
  `require_salon_scope` ; `403` **générique** ; l'invariant deny-by-default est vérifié
  mécaniquement par `unprotected_routes(app)` (`test_security_guards.py`) — **une route ajoutée sans
  garde fait échouer les tests**.
- **Tests** : fakes en mémoire (`tests/conftest.py`) + `TestClient` + `app.dependency_overrides` ;
  **e2e** sur PostgreSQL réel (`coiflink-e2e-pg`, port 55433 — cf. mémoire projet), patron
  `test_daily_summary_e2e.py`. Fichiers unitaires nommés par sujet (`test_domain_revenue.py`,
  `test_stats_api.py`, …).

### Modèle de données pertinent (schéma #3, **aucun changement**)

```
appointments (id, salon_id, client_id→users.id, hairdresser_id→users.id NULL, appointment_date,
              start_time, end_time, status, cancellation_reason, client_note, slot TSRANGE, created_at,
              updated_at)   -- PAS de arrived_at/started_at/finished_at
appointment_services (appointment_id, service_id, salon_id, price_at_booking)  -- durée sur services
services (id, salon_id, name, price, duration_minutes, is_active, …)
payments (id, salon_id, appointment_id NULL, service_id NULL, client_id NULL, amount, currency,
          payment_method, status, recorded_by, reference, created_at)
cash_journal (id, salon_id, transaction_id NULL, operation_type, amount, performed_by, description,
              created_at)
notifications (id, user_id NULL, salon_id NULL, appointment_id NULL, type, channel, title, message,
               status, sent_at, scheduled_for, created_at)   -- ix_notifications_salon_id (salon_id, created_at)
audit_logs (id, action, actor_user_id, salon_id NULL, entity_type, entity_id, event_metadata, created_at)
```

- Index couvrants **déjà présents** : `ix_appointments_salon_id (salon_id, appointment_date)`,
  `ix_appointments_client_id (client_id)`, `ix_payments_salon_id (salon_id, created_at)`,
  `ix_cash_journal_salon_id (salon_id, created_at)`, `ix_notifications_salon_id (salon_id, created_at)`,
  `ix_audit_logs_salon_id_created_at (salon_id, created_at DESC)`. **Aucune migration** requise par #148.
- `AppointmentStatus` = `PENDING/CONFIRMED/CANCELLED/COMPLETED/NO_SHOW` ; `NotificationType` =
  `CONFIRMATION/REMINDER/CANCELLATION/NEW_BOOKING/APPOINTMENT_UPDATE` ; `PaymentStatus` =
  `PENDING/VALIDATED/CANCELLED/ADJUSTED` ; `CashOperationType` =
  `PAYMENT/REFUND/ADJUSTMENT/CASH_OPENING/CASH_CLOSING`.

### Web gérant — patrons à réutiliser (#39–#43)

- `app/(gerant)/gerant/page.tsx` — Server Component + composition root : lit le cookie `httpOnly`
  (jamais exposé, invariant #14), appelle les gateways **côté serveur**, rend
  `DailySummaryTiles`/`RevenueTiles`/`ServiceDemandPanel`/`ActiveClientsPanel`/
  `HairdresserPerformancePanel`, **dégrade localement** un panneau en panne.
- `src/application/ports/stats-gateway.ts` + `src/adapters/api/http-stats-gateway.ts` — port + adapter
  HTTP en **union discriminée** (`{ ok: true, … } | { ok: false, reason }`), jeton jamais dans le
  résultat, mapping `200/401/403/422/503`, `cache: "no-store"`. #148 **étend** ce port des nouvelles
  lectures (KPI, séries, en-cours, activités, alertes).
- Composants UI existants réutilisables : tuiles KPI (`daily-summary-tiles`/`revenue-tiles`/
  `active-clients-panel`), `Tabs` (`service-demand-panel`), `EmptyState`, jetons de statut
  (`STATUS_LABELS_FR`/`STATUS_STYLES` de `src/domain/appointment/appointment.ts`), helpers de format
  (`formatXof`, `formatPeriodRange`), calculs de plage (`rangeForView`/`todayIso`/`weekRange`
  de `src/domain/appointment/planning-view.ts`, en **UTC** pour parité `Africa/Abidjan`).
- **Aucun** composant skeleton ni de charting n'existe encore (à créer). Tests Vitest **par sujet** dans
  `web-dashboard/test/` ; la page a déjà `test/gerant-dashboard-page.test.ts`.

### Contraintes transverses documentées

- **PRD §11.2** : un gérant ne voit que son salon. **§11.3** : collecte minimale, pas de PII superflue
  ni en logs ; « journalisation des accès sensibles » (les lectures stats n'y sont **pas** soumises —
  parité #39–#43). **§11.4** : audit des **actions** (aucune ici — lecture pure). **§12.1** : réponse
  API < 3 s, **chargement dashboard < 3 s**. **§12.2** : disponibilité ≥ 99 %.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA**.
- **Test gate** : `scripts/test-gate.sh` (`pytest` + `npm test` + `flutter test`) ; CI `ci.yml` (ruff,
  pytest, round-trip Alembic contre PostgreSQL 16, build, lint/test/build web **sortie standalone**).

## Proposed Implementation

**Approche recommandée : consolidation web au-dessus d'extensions backend minimales et additives,
livrée en deux couches de priorité.** Les KPI/graphiques sont des **agrégats counts-only en base**
(patron #39/#40/#42) ; les vues opérationnelles (en-cours, activités, alertes) sont des **lectures
salon-scopées** émettant un **nom d'affichage maîtrisé** (patron #43/#36). Tout est **dérivé en
lecture** : **aucune migration**, aucun statut nouveau, aucun event-sourcing.

> **Staging (priorité de livraison).** Le **cœur** qui satisfait les critères d'acceptation
> (« 4 KPI affichés et filtrables par période, données réelles, mise à jour automatique, états
> loading/empty/error, tests ») = **Parts A–C + G (auto-refresh) + H (états)**. Les **extensions**
> (graphiques Part D, prestations en cours Part E, timeline/alertes Part F) enrichissent l'écran §7.2
> sur données réelles ; leur profondeur peut être ajustée sans compromettre les critères d'acceptation.
> Si l'effort doit être borné, **livrer A–C+G+H d'abord**, puis D, E, F dans cet ordre.

### (A) Domaine — période & évolution (pur)

**`domain/dashboard.py`** — **créer** (module pur, sans I/O) :

- `DashboardPeriodKind` = `"today" | "week" | "month" | "custom"` (littéraux).
- `resolve_period(kind, *, reference, date_from=None, date_to=None) -> tuple[date, date]` :
  - `today` → `day_bounds(reference)` ; `week` → `week_bounds(reference)` (lundi→dimanche) ;
    `month` → `month_bounds(reference)` ; `custom` → `(date_from, date_to)` (les deux requis, sinon
    erreur de domaine → `422` côté route). Réutilise `domain/revenue.py`.
- `previous_period(date_from, date_to) -> tuple[date, date]` : période **immédiatement précédente de
  même longueur** (`length = date_to - date_from + 1` jours ; `prev_to = date_from - 1j`,
  `prev_from = prev_to - (length-1)j`). Base de l'**évolution**.
- `Evolution` (`frozen`) : `current: int|Decimal`, `previous: int|Decimal`, `delta` (dérivé),
  `direction: "up"|"down"|"flat"` (dérivé) ; helper pur `compute_evolution(current, previous)`.
  L'évolution est **calculée côté serveur** (autorité), le front ne recalcule rien.
- `is_in_progress(now, appointment_date, start_time, end_time) -> bool` : vrai si
  `datetime(appointment_date, start_time) <= now < datetime(appointment_date, end_time)`
  (naïf, fuseau salon `Africa/Abidjan`). Fonction **pure** — la dérivation « en cours » est décidée
  ici, testable sans base.
- Exporter dans `__all__`. Tests unitaires purs (bornes, évolution, « en cours » aux bords du créneau).

### (B) Backend — endpoint KPI consolidé (counts-only)

**`adapters/inbound/stats.py`** — **ajouter** `GET /salons/{salon_id}/dashboard/kpis` (garde
`require_salon_scope` + `require_permission(STATS_READ_SALON)`), paramètres
`period` (`today|week|month|custom`, défaut `today`), `date_from`/`date_to` (requis si `custom`),
`reference` optionnel (défaut `_today()`). Résout la période via `resolve_period`, calcule les **4 KPI +
évolution** et renvoie un `DashboardKpisResponse` **explicite** (patron Pydantic #40/#42, aucune PII) :

```json
{
  "period": { "kind": "today", "date_from": "2026-08-07", "date_to": "2026-08-07" },
  "waiting_clients":     { "current": 3,        "previous": 5,        "direction": "down" },
  "in_progress":         { "current": 2 },
  "revenue":             { "current": "125000.00", "previous": "98000.00", "direction": "up", "currency": "XOF" },
  "clients_count":       { "current": 18,       "previous": 15,       "direction": "up" }
}
```

- **`waiting_clients`** = nombre de RDV `PENDING` sur la période (nouveau agrégat
  `count_by_status_in_range(salon_id, statuses=("PENDING",), date_from, date_to)` ou réutilisation d'un
  `GROUP BY status` sur plage) ; **évolution** vs `previous_period`.
- **`in_progress`** = **instantané** dérivé : le use case charge
  `list_for_salon(salon_id, today, today, statuses=("CONFIRMED",))` puis filtre `is_in_progress(now, …)`
  et **compte**. C'est un « maintenant » (indépendant du filtre de période) — **pas** d'évolution
  (l'issue ne liste que « nombre actuel »). *Option perf* : un `COUNT` en base avec prédicat sur
  `slot @> now::timestamp` (le `slot` TSRANGE existe déjà) — voir *Open Questions §7*.
- **`revenue`** = net `cash_journal` (`PAYMENT`+`ADJUSTMENT`) sur `[date_from, date_to]` (réutilise le
  chemin #40 généralisé à une plage arbitraire) ; **évolution** vs période précédente ; montant en
  **chaîne décimale** (`NUMERIC(12,2)`), jamais un flottant.
- **`clients_count`** = « nombre de clientes » sur la période = nombre de **comptes distincts** ayant un
  RDV `COMPLETED` (une « visite » §8.1, patron #42) ; réutilisable via
  `segment_active_clients(...).active` (`new + recurring`) **ou** un `COUNT(DISTINCT client_id)` dédié —
  voir *Open Questions §2* ; **évolution** vs période précédente.
- **DI** : réutiliser `get_appointment_repository` / `get_cash_journal_repository` de `stats.py`.
- **Ports/dépôts** : ajouter au `Protocol AppointmentRepository` les agrégats de plage manquants
  (`count_by_status_in_range`, `count_in_progress` ou réutilisation, `count_distinct_completed_clients`)
  — foyer naturel des agrégats salon-scopés sur `appointments`. Implémenter en SQL avec **isolation
  §11.2 inconditionnelle** (`WHERE salon_id`), `client_id` **jamais émis**.
- **Use case** : `application/dashboard.py::SummarizeDashboardKpis` (dépend des ports
  `AppointmentRepository` + `CashJournalRepository`), impose les statuts côté serveur, assemble les 4
  KPI + évolution ; **aucune écriture/audit**.

*(Alternative : quatre endpoints séparés au lieu d'un consolidé — voir Open Questions §3. Recommandation :
**un endpoint consolidé** pour tenir le budget « chargement dashboard < 3 s » §12.1 et **borner le coût
du polling** — un aller-retour au lieu de quatre à chaque tick.)*

### (C) Backend — filtre de période (unifié)

Le filtre `Aujourd'hui | Semaine | Mois | Personnalisée` est **résolu côté serveur** par `resolve_period`
et **partagé** par toutes les nouvelles routes (KPI, séries, en-cours n/a, alertes). Garde explicite
`date_to < date_from → 422` (patron `get_service_demand`), date mal formée → `422` (FastAPI),
`custom` sans bornes → `422`. Les endpoints existants #40/#41/#42/#43 **restent inchangés** ; le web
mappe le sélecteur de période sur leurs paramètres respectifs (le CA #40 reste par « date de
référence » pour les tuiles historiques si conservées, ou bascule sur la plage via le nouvel endpoint).

### (D) Backend — séries temporelles pour les graphiques (counts-only)

**`adapters/inbound/stats.py`** — **ajouter** deux lectures agrégées en base, sur `[date_from, date_to]`
résolu, renvoyant une **liste de buckets** `{ bucket_start, bucket_end, value }` (jour pour
`today`/`week`/`custom` court ; jour ou semaine pour `month`/plage longue — granularité **choisie
serveur**, autorité) :

- `GET /salons/{salon_id}/dashboard/revenue-series` → série du **net `cash_journal`** par bucket
  (`GROUP BY date_trunc`), pour le **graphique d'évolution du CA**. Montants en chaîne décimale.
- `GET /salons/{salon_id}/dashboard/attendance-series` → série du **nombre de RDV/visites** par bucket
  (`GROUP BY appointment_date`), pour le **graphique de fréquentation**. Compteurs entiers.

Counts-only, aucune PII ; ports/dépôts étendus (`revenue_series`, `attendance_series`) avec isolation
§11.2 en SQL. Buckets **vides = 0** (jamais absents) pour un axe temporel continu, complétés par une
fonction **pure** du domaine (patron `build_daily_summary` #39).

### (E) Backend — liste des prestations en cours (avec noms d'affichage)

**`adapters/inbound/stats.py`** — **ajouter** `GET /salons/{salon_id}/dashboard/in-progress`
(mêmes gardes) renvoyant la liste des RDV `CONFIRMED` **en cours maintenant**, **enrichie des noms** :

```json
{
  "as_of": "2026-08-07T14:32:00+00:00",
  "items": [
    { "appointment_id": "…", "client_name": "Awa Koné", "service_names": ["Coupe femme","Coloration"],
      "hairdresser_name": "Fatou D.", "start_time": "14:00:00", "end_time": "15:30:00", "status": "CONFIRMED" }
  ]
}
```

- **Nouvelle lecture résolvant les noms** — `SqlAppointmentRepository.list_in_progress_details(salon_id,
  *, now)` : `SELECT` sur `appointments` **join** `users` (client) **join** `users` (hairdresser, LEFT)
  **join** `appointment_services`+`services` (noms de prestation), filtre `salon_id`,
  `status='CONFIRMED'`, `slot @> now::timestamp` (le TSRANGE existe). Émet **uniquement** les **noms
  d'affichage** (`users.full_name`, `services.name`) — **jamais** `client_id`/`user_id`/contact
  (patron #43/#36).
- **Use case** `application/dashboard.py::ListInProgressServices` : impose `CONFIRMED` + le prédicat
  temporel serveur (ou le confie au SQL) ; **aucun** audit.
- **Statut** : au MVP toujours `CONFIRMED` (« en cours » est **dérivé**, pas stocké) — la colonne
  `status` de la ligne est renvoyée pour transparence, et le libellé UI « En cours » est **calculé**
  côté serveur/domaine, pas un statut base.

### (F) Backend — timeline des activités & alertes (dérivées, bornées aux faits réels)

**Timeline (`GET /salons/{salon_id}/dashboard/activity`)** — flux **fusionné, trié par horodatage
décroissant, borné (top N)** des faits **réellement horodatés** :

- **paiements** — `payment_repository.list_for_salon(...)` (résout `client_name`), `created_at` ;
- **nouvelles réservations / annulations / modifications** — via une **lecture salon-scopée des
  `notifications`** (nouveau `NotificationRepository.list_for_salon(salon_id, *, limit)` — les rows
  `NEW_BOOKING`/`CANCELLATION`/`APPOINTMENT_UPDATE` portent `created_at`, `type`, `appointment_id`, et
  un `title`/`message` **neutres** sans PII, ADR-0006). Ceci **matérialise enfin la lecture salon**
  différée par #47/#48 (parité, sans remise).

Chaque entrée = `{ occurred_at, kind, label }` (+ `amount`/`client_name` **uniquement** pour les
paiements, patron #43/#36). **Documenter explicitement** (README + réponse OpenAPI) que « **arrivée
cliente / début / fin de prestation** » **ne figurent pas** au MVP : aucune source ne les horodate
(pas de pointage). Cette timeline correspond fidèlement à « Transactions récentes » (§7.2).

**Alertes (`GET /salons/{salon_id}/dashboard/alerts`)** — liste **dérivée** de faits réels, chaque
alerte `{ kind, severity, count, sample? }` :

- **`payment_anomaly`** — écarts de caisse #36 : `payment_repository.count_completed_without_payment(...)`
  (RDV `COMPLETED` sans paiement) ; réutilise `domain/discrepancy.py`. Garde `CASH_JOURNAL_READ`
  **ou** `STATS_READ_SALON` selon *Open Questions §6*.
- **`late`** (retard) — RDV `CONFIRMED` du jour dont `start_time` est **dépassé** (`< now`) sans clôture
  (`COMPLETED`/`NO_SHOW`) : dérivé de `list_for_salon(salon_id, today, today, statuses=("CONFIRMED",))`
  + prédicat pur `end_time <= now` (ou `start_time < now`). Aucune donnée nouvelle.
- **`prolonged_wait`** (attente prolongée) — RDV `PENDING` du jour non confirmé au-delà d'un **seuil**
  (constante de domaine, ex. `created_at` ancien ou `start_time` proche/dépassé). Seuil documenté,
  ajustable — *Open Questions §1*.

Alertes **counts-first** (compteurs + éventuel échantillon de noms d'affichage) ; aucune alerte
inventée, aucune PII au-delà du nom d'affichage maîtrisé.

### (G) Web — filtre de période, cartes, graphiques, listes, auto-refresh

1. **Domaine TS** — `src/domain/dashboard/period.ts` (`DashboardPeriodKind`, résolution en
   `date_from`/`date_to` **en UTC** parité `Africa/Abidjan`, réutilise `weekRange`/`monthRange`/`todayIso`
   de `planning-view.ts`) ; `src/domain/dashboard/kpi.ts` / `activity.ts` / `alerts.ts` (types +
   formatage, `formatXof` réutilisé ; évolution **affichée** telle que reçue, jamais recalculée).
2. **Port & gateway** — étendre `src/application/ports/stats-gateway.ts` et
   `src/adapters/api/http-stats-gateway.ts` : `dashboardKpis`, `revenueSeries`, `attendanceSeries`,
   `inProgress`, `activity`, `alerts` (unions discriminées, jeton **serveur** jamais exposé,
   `cache: "no-store"`, mapping `200/401/403/422/503`, mapping **défensif** des tableaux).
3. **Sélecteur de période** — `src/adapters/ui/period-filter.tsx` (client component) : boutons
   `Aujourd'hui | Semaine | Mois` + saisie de plage **Personnalisée** ; il met à jour les
   `searchParams` de `/gerant` (nouveau rendu **serveur**, relecture de la source de vérité — patron des
   filtres #35), **jamais** un filtrage en mémoire.
4. **Cartes KPI** — `src/adapters/ui/dashboard-kpi-cards.tsx` : 4 tuiles (réutiliser le style
   `revenue-tiles`/`active-clients-panel`) avec valeur + **badge d'évolution** (↑/↓/→, couleur
   sémantique) ; « prestations en cours » sans badge (instantané).
5. **Graphiques** — `src/adapters/ui/revenue-chart.tsx` & `attendance-chart.tsx` : **SVG inline** rendu
   **côté serveur** (barres/aire, axes, libellés, `aria-label` + table de secours accessible), **sans
   nouvelle dépendance** (*Open Questions §4*). État vide si série tout-à-zéro. S'appuyer sur le skill
   `dataviz` pour la palette/lisibilité.
6. **Listes** — `src/adapters/ui/in-progress-list.tsx` (cliente · prestation · professionnelle · heure
   de début · statut), `activity-timeline.tsx` (icône par `kind`, horodatage relatif),
   `alerts-panel.tsx` (badge de sévérité, compteur, message actionnable). États vides explicites.
7. **États loading** — `src/adapters/ui/dashboard-skeleton.tsx` (nouveau composant skeleton réutilisable,
   `animate-pulse` Tailwind) rendu pendant le chargement via **`loading.tsx`** de segment (App Router)
   et/ou `<Suspense>` autour des panneaux.
8. **Auto-refresh** — `src/adapters/ui/auto-refresh.tsx` (client component minimal) : `setInterval`
   déclenchant `router.refresh()` (re-exécute le Server Component `/gerant`, qui relit le cookie
   `httpOnly` côté serveur — **le jeton n'est jamais exposé au client**, invariant #14) ; **pause quand
   l'onglet est masqué** (`document.visibilityState`, Page Visibility API) pour ne **pas** émettre
   d'appel superflu (§12.1) ; intervalle **par défaut 30–60 s** (constante justifiée, ajustable).
   En panne d'un tick, l'écran conserve la dernière donnée (dégradation locale, patron #41) et peut
   afficher un indicateur discret « données du HH:MM ». Voir *Open Questions §5*.
9. **Page** — étendre `app/(gerant)/gerant/page.tsx` : lire `searchParams` (période), charger
   **côté serveur** les nouvelles lectures en parallèle (`Promise.all`), rendre le sélecteur de période,
   les 4 cartes, les graphiques, les listes, enrober d'`<AutoRefresh>`. **Dégrader localement** chaque
   panneau en panne. Conserver la rétro-compatibilité des panneaux #41/#42/#43 (ou les réorganiser sous
   l'écran d'activité — décision UX à documenter).

### (H) États loading / empty / error (critère d'acceptation)

- **loading** : skeletons (Part G7) au premier rendu et pendant un changement de période.
- **empty** : chaque panneau a un état vide explicite sur données réelles (« Aucun client en attente »,
  « Aucune prestation en cours actuellement », « Aucune activité récente », « Aucune alerte »).
- **error** : erreur backend d'un panneau → **dégradation locale** (message neutre, patron #41) sans
  casser le reste ; erreur globale (pas de salon / `list` KO) → invite/panneau d'erreur maîtrisé
  (patron actuel de `page.tsx`).

### (I) Documentation & ADR

- **ADR-0039** (recommandé, *Open Questions §8*) : acter les décisions transverses (statut « en cours »
  **dérivé** vs migration ; « en attente » = `PENDING` ; modèle de période + évolution ; graphiques
  **SVG sans dépendance** ; auto-refresh **polling visibility-aware** ; timeline/alertes dérivées &
  arrivée/début/fin **différés** ; extension au-delà de l'Épic 6 analytique vers §7.2/§17 borné MVP).
  Entrée dans `docs/adr/README.md`.
- `backend/README.md` : nouvelles routes `dashboard/*`, permission (**sixième+** usage de
  `STATS_READ_SALON`), définitions dérivées, note « arrivée/début/fin non représentés ».
- `web-dashboard/README.md` : écran d'activité `/gerant`, filtre de période, graphiques SVG,
  auto-refresh, extension du `http-stats-gateway`.
- `README.md` racine §6 : phrase de statut « Dashboard Manager activité (#148) livré » (style M5).

## Affected Files / Packages / Modules

**Backend (`backend/coiflink_api/`)**
- `domain/dashboard.py` — **créer** (`DashboardPeriodKind`, `resolve_period`, `previous_period`,
  `Evolution`/`compute_evolution`, `is_in_progress`, `__all__`).
- `application/dashboard.py` — **créer** (`SummarizeDashboardKpis`, `ListInProgressServices`,
  séries, `activity`, `alerts` — use cases de lecture pure).
- `application/ports/appointment_repository.py` — **modifier** (agrégats de plage
  `count_by_status_in_range`, `count_distinct_completed_clients`, `revenue`/`attendance` séries si
  portées ici, `list_in_progress_details`, `count_in_progress`).
- `application/ports/notification_repository.py` — **modifier** (ajouter `list_for_salon(salon_id, *,
  limit)` — lecture salon différée #47/#48).
- `application/ports/payment_repository.py`, `application/ports/cash_journal_repository.py` — **lire**
  (réutilisation `list_for_salon` / `count_completed_without_payment` / net par plage ; étendre si série
  CA portée côté cash journal).
- `adapters/outbound/persistence/appointment_repository.py` — **modifier** (implémenter les nouveaux
  agrégats + `list_in_progress_details` avec joins `users`×2 + `services`, `slot @> now`).
- `adapters/outbound/persistence/notification_repository.py` — **modifier** (`list_for_salon`).
- `adapters/inbound/stats.py` — **modifier** (schémas Pydantic explicites + routes
  `dashboard/kpis`, `dashboard/revenue-series`, `dashboard/attendance-series`, `dashboard/in-progress`,
  `dashboard/activity`, `dashboard/alerts` ; garde `date_to < date_from → 422` ; DI réutilisée).
- `main.py` — **modifier** (commentaire d'assemblage / en-tête router `stats` : nouveaux endpoints /
  usages de `STATS_READ_SALON`). *Router déjà monté (#40).*
- `domain/revenue.py` (`*_bounds`), `domain/discrepancy.py`, `domain/appointment.py`
  (`REVENUE_STATUSES`), `adapters/inbound/security.py`, `domain/permissions.py` — **lire** (réutilisation).
- `backend/README.md` — **modifier**.

**Backend — tests**
- `tests/test_domain_dashboard.py` — **créer** (période/évolution/`is_in_progress`, bornes).
- `tests/test_dashboard_usecase.py` — **créer** (statuts imposés serveur, assemblage KPI, séries, alertes ;
  fakes).
- `tests/test_stats_api.py` — **étendre** (ou `test_dashboard_api.py` **créer**) : `200/401/403/422`,
  **non-PII** des endpoints counts-only, isolation, défaut de période, non-collision de routage,
  `unprotected_routes == []`.
- `tests/conftest.py` — **modifier** (fakes : nouveaux agrégats + `list_in_progress_details` +
  `notification_repository.list_for_salon`).
- `tests/test_dashboard_e2e.py` — **créer** (agrégats SQL réels, `slot @> now`, joins de noms, séries,
  isolation inter-salons, absence de PII sur les endpoints counts-only).

**Web (`web-dashboard/`)**
- `src/application/ports/stats-gateway.ts` — **modifier** (nouveaux résultats + méthodes).
- `src/adapters/api/http-stats-gateway.ts` — **modifier** (implémentations).
- `src/domain/dashboard/period.ts`, `kpi.ts`, `activity.ts`, `alerts.ts` — **créer** (types + formatage).
- `src/adapters/ui/period-filter.tsx`, `dashboard-kpi-cards.tsx`, `revenue-chart.tsx`,
  `attendance-chart.tsx`, `in-progress-list.tsx`, `activity-timeline.tsx`, `alerts-panel.tsx`,
  `dashboard-skeleton.tsx`, `auto-refresh.tsx` — **créer**.
- `app/(gerant)/gerant/page.tsx` — **modifier** (searchParams période, chargements parallèles, rendu,
  auto-refresh, dégradation locale) ; `app/(gerant)/gerant/loading.tsx` — **créer** (skeleton).
- `web-dashboard/README.md` — **modifier**.
- `web-dashboard/test/*.test.ts` — **créer** (période domaine, gateways, cartes, charts SVG, listes,
  auto-refresh, états ; étendre `gerant-dashboard-page.test.ts`).

**Documentation (racine)** : `README.md` ; `docs/adr/0039-*.md` + `docs/adr/README.md` (recommandé).

**À lire (sans modifier)** : `adapters/inbound/stats.py`, `adapters/outbound/persistence/
appointment_repository.py` (`count_by_status_for_day`, `demand_by_service`, `segment_active_clients`,
`performance_by_hairdresser`, `list_for_salon`), `application/ports/payment_repository.py`
(`list_for_salon`, `list_completed_without_payment`, `count_completed_without_payment`),
`domain/revenue.py`, `domain/discrepancy.py`, `web-dashboard/app/(gerant)/gerant/page.tsx`,
`src/adapters/api/http-stats-gateway.ts`, `src/adapters/ui/revenue-tiles.tsx` /
`service-demand-panel.tsx` / `active-clients-panel.tsx`, `src/domain/appointment/planning-view.ts`.

## API / Interface Changes

**Nouvelles routes HTTP (backend), toutes protégées** (`STATS_READ_SALON` + `require_salon_scope`,
`MANAGER` seul) ; **aucune** route existante modifiée ; **aucun** chemin ajouté à `PUBLIC_ROUTE_PATHS`.
Toutes sous le préfixe `/salons/{salon_id}/dashboard/` (segment **distinct** des routes `customers`/
`services`/`payments`/`appointments` — vérifier la non-collision par test de routage) :

| Route | Réponse | PII |
| --- | --- | --- |
| `GET …/dashboard/kpis?period&date_from&date_to&reference` | 4 KPI + évolution (counts/montants) | **Non** |
| `GET …/dashboard/revenue-series?…` | série de buckets `{start,end,total}` | **Non** |
| `GET …/dashboard/attendance-series?…` | série de buckets `{start,end,count}` | **Non** |
| `GET …/dashboard/in-progress` | liste `{client_name, service_names, hairdresser_name, start_time, status}` | **Nom d'affichage** (maîtrisé) |
| `GET …/dashboard/activity?limit` | flux fusionné `{occurred_at, kind, label, amount?, client_name?}` | **Nom d'affichage** (paiements) |
| `GET …/dashboard/alerts` | `{kind, severity, count, sample?}` | **Nom d'affichage** (échantillon) |

- **Auth** : `Principal` requis (deny-by-default). **401** jeton absent/invalide · **403** rôle
  insuffisant **ou** salon hors périmètre (générique, aucun oracle) · **422** `period`/`date_from`/
  `date_to` mal formé ou incohérent (`date_to < date_from`, `custom` sans bornes).
- **OpenAPI** : chaque route documentée via schéma Pydantic **explicite** + `responses` (200/401/403/422)
  + docstring (visible sur `/docs`).
- **Web** : nouveau **contenu** de `/gerant` (mêmes URL) + `searchParams` de période ; **aucun** Route
  Handler BFF requis si le fetch serveur direct + `router.refresh()` sont retenus (patron #40/#41).
  Si le polling ciblé est préféré au `router.refresh()` global, un ou plusieurs Route Handlers BFF
  `/api/salons/[id]/dashboard/*` proxifieraient les lectures (jeton lu du cookie **côté serveur**) —
  *Open Questions §5*.
- **Aucune** autre surface (CLI, variable d'environnement autre que l'intervalle de polling éventuel).

## Data Model / Protocol Changes

**None.** Aucune table, colonne, contrainte, valeur d'énum ni migration Alembic. #148 est **entièrement
dérivé en lecture** des tables existantes :

- « Prestations en cours » = `CONFIRMED` + `slot @> now` (le `slot` TSRANGE **existe déjà**) — **aucun**
  statut `IN_PROGRESS`, **aucune** colonne d'horodatage.
- « Clients en attente » = `PENDING` ; « nombre de clientes » = `COUNT(DISTINCT client_id)` /
  `COMPLETED` ; CA = net `cash_journal` ; séries = `GROUP BY date_trunc`/`appointment_date`.
- Timeline/alertes = lectures de `payments`, `notifications`, `appointments`, `cash_journal` existants.

Les index couvrants nécessaires **existent déjà** (voir *Relevant Repository Context*). Un éventuel
index de couverture pour `slot @> now` ou pour les séries reste une **optimisation future** (mesure
d'abord, §12.1 tenu au volume salon MVP) — *Open Questions §7*. `AppointmentStatus`/`ROLE_PERMISSIONS`
réutilisés tels quels.

## Security & Privacy Considerations

- **Isolation §11.2 (multi-tenant).** Toutes les routes sont salon-scopées (`require_salon_scope`) **+**
  re-filtrage `WHERE …salon_id = :salon_id` **inconditionnel** en SQL (défense en profondeur). Un salon
  hors périmètre est un **403 générique** indiscernable (aucun oracle). Les jointures de noms (`users`,
  `services`) sont **contraintes au salon** (RDV du salon uniquement).
- **Minimisation & émission maîtrisée de PII (§11.3).**
  - Endpoints **counts-only** (`kpis`, `revenue-series`, `attendance-series`) : **aucune** PII —
    `client_id` **groupé mais jamais sélectionné** (patron #42), réponses = compteurs/montants/dates.
    Schémas Pydantic **explicites** figés par un test qui échoue si un champ interdit apparaît (patron
    #37/#40/#42).
  - Endpoints **opérationnels** (`in-progress`, `activity`, `alerts`) : émettent **uniquement** le
    **nom d'affichage** (`users.full_name`, `services.name`) — **jamais** `client_id`/`user_id`,
    téléphone, e-mail, rôle, ni note interne. C'est le patron **déjà accepté** de #43
    (performance coiffeurs, ADR-0031) et #36 (écarts de caisse, ADR-0028) : le gérant est **habilité**
    à voir l'identité d'affichage de **son** salon (§11.2). Les messages de `notifications` sont
    **neutres** (ADR-0006). Documenter ce périmètre d'émission dans l'ADR-0039.
- **Anti-oracle (§11.1/ADR-0026).** Les compteurs agrégés ne révèlent ni existence ni identité d'un
  compte. Les listes opérationnelles ne portent que des RDV du **propre** salon (aucune fuite
  inter-salons, aucun oracle d'existence de compte tiers).
- **Deny-by-default (#12 / ADR-0015).** Chaque route porte `require_permission(STATS_READ_SALON)` ;
  **jamais** ajoutée à `PUBLIC_ROUTE_PATHS` ; l'invariant `unprotected_routes(app) == []` reste vert.
  `CLIENT`/`HAIRDRESSER`/`ADMIN` → `403`. **Ne pas** modifier `ROLE_PERMISSIONS`.
- **Aucune PII ni secret dans les logs.** Ni `logger`/`print` ni messages `4xx` ne portent de nom, de
  téléphone, de `client_id` ni de jeton. Le nom d'affichage (exposé au gérant légitime) n'est **jamais
  journalisé**.
- **Jeton jamais exposé au client (invariant #14).** Les lectures se font **côté serveur Next** (jeton
  du cookie `httpOnly`). L'auto-refresh recommandé (`router.refresh()`) **re-exécute le Server
  Component** — le jeton reste côté serveur, **jamais** dans le JS client ni en query. Si des BFF de
  polling ciblé sont retenus, ils lisent le cookie **côté serveur** (patron #35).
- **Lecture pure — aucun effet de bord.** Aucune écriture, **aucun** audit §11.4 (parité #39–#43) : la
  consultation d'un KPI/d'une activité n'est pas une action journalisée.
- **Coût / latence (§12.1/§12.2).** Endpoint KPI **consolidé** = un aller-retour (borne le coût du
  polling). Séries et listes agrégées **en base**, bornées par le volume du salon (petit au MVP) et
  **top-N** pour la timeline. Auto-refresh **visibility-aware** (pause onglet masqué) + intervalle
  ≥ 30 s : pas d'appel superflu. Chargement dashboard **< 3 s** visé (chargements parallèles). Un
  dépassement se **mesure** (#52 perf) et se traite en optimisation dédiée (index §7).

Le dépôt ne documente **aucune** contrainte supplémentaire (résidence, chiffrement applicatif) au-delà
de celles ci-dessus pour ces lectures. Le chiffrement au repos est « si nécessaire » (§11.3) — non
requis ici.

## Testing Plan

**Backend — domaine (pur) — `tests/test_domain_dashboard.py`**
- `resolve_period` : `today`/`week` (lundi→dimanche)/`month`/`custom` → bornes correctes ; `custom` sans
  bornes → erreur ; `previous_period` (longueur préservée, contiguïté). `compute_evolution`
  (up/down/flat, division par zéro previous=0). `is_in_progress` : instant **avant** début → faux ;
  **au** début → vrai ; **entre** début et fin → vrai ; **à** la fin (exclusif) → faux ; **après** →
  faux ; jour différent → faux.

**Backend — application — `tests/test_dashboard_usecase.py` (fakes)**
- `SummarizeDashboardKpis` : impose `PENDING`/`CONFIRMED`/`COMPLETED` **côté serveur** (jamais soumis) ;
  assemble 4 KPI + évolution (passe la période **et** la période précédente au port) ; `in_progress`
  dérivé de `CONFIRMED` ∩ `is_in_progress` ; **aucune** écriture/audit. Cas « salon vide » → tout à `0`.
- `ListInProgressServices` : filtre `CONFIRMED` + prédicat temporel ; mappe les noms d'affichage.
- Séries : buckets complétés à `0` (axe continu). Alertes : dérivation `payment_anomaly`/`late`/
  `prolonged_wait` sur des jeux contrôlés.

**Backend — inbound (`TestClient` + `app.dependency_overrides`) — `tests/test_dashboard_api.py`**
- `200` : KPI corrects par période ; séries non vides ; en-cours avec noms ; activité triée ; alertes.
- **Filtre de période** : `today`/`week`/`month`/`custom` ; défaut = `today` ; `custom` sans bornes ou
  `date_to < date_from` → `422` ; date mal formée → `422`.
- **Non-PII (counts-only)** : `kpis`/`revenue-series`/`attendance-series` ne contiennent **aucune** clé
  interdite (`client_id`, nom, téléphone, `appointment_id`) — test qui **échoue** sinon.
- **Émission maîtrisée** : `in-progress`/`activity`/`alerts` ne portent **que** le nom d'affichage
  (jamais contact/`client_id`).
- `403` : `CLIENT`/`HAIRDRESSER`/`ADMIN` ; gérant d'un **autre** salon (hors portée) → 403 générique.
  `401` : sans jeton. **Isolation** : données d'un autre salon jamais visibles.
- `unprotected_routes(app) == []` couvre les nouvelles routes ; non-collision de routage
  `dashboard/*` avec `customers`/`services`/`payments`/`appointments`.

**Backend — e2e PostgreSQL réel — `tests/test_dashboard_e2e.py`** *(patron `test_daily_summary_e2e.py`,
`coiflink-e2e-pg` port 55433)* : `slot @> now` réel (RDV en cours vs passés/futurs), joins de noms
(client/coiffeur/prestation), séries `GROUP BY`, KPI + évolution sur données réelles, **isolation
inter-salons**, non-PII des endpoints counts-only, écart de caisse (#36) alimentant `alerts`.

**Web (`web-dashboard/test/`, Vitest)**
- **Filtre de période** : mappe le choix sur `searchParams` → nouvelle URL serveur (jamais filtrage
  mémoire) ; parité UTC des bornes.
- **Cartes KPI** : rendu valeur + badge d'évolution (↑/↓/→) ; « en cours » sans badge ; « 0 » → état
  cohérent.
- **Graphiques SVG** : rendent des barres/aire proportionnelles, axes/légendes, `aria-label` + table de
  secours ; série tout-à-zéro → état vide.
- **Listes** : en-cours (colonnes cliente/prestation/professionnelle/heure/statut), timeline (tri, icône
  par kind), alertes (sévérité/compteur) ; états vides explicites.
- **Auto-refresh** : `setInterval` déclenche `router.refresh()` ; **pause** quand `visibilityState ===
  "hidden"` ; nettoyage à l'unmount ; aucun jeton dans le client.
- **États** : skeleton au chargement ; dégradation **locale** d'un panneau en panne (`null`) sans casser
  la page (patron #41) ; page `gerant-dashboard-page.test.ts` étendue.
- **Gateways** : URL correctes (période optionnelle), jeton **serveur** (jamais exposé), mapping
  `200/401/403/422/503`, mapping défensif des tableaux.

**Documentation / non-régression** : `scripts/test-gate.sh` au vert (pytest + npm test + flutter test) ;
`ruff check` propre ; `npm run lint && npm run build` (sortie standalone) inchangé.

## Documentation Updates

- **`docs/adr/0039-dashboard-manager-activite-salon.md`** (recommandé) — acter : « en cours » **dérivé**
  (vs statut/migration), « en attente » = `PENDING` (pas de file d'attente, §17 hors MVP), modèle de
  période + sémantique d'évolution, **graphiques SVG sans dépendance**, **auto-refresh polling
  visibility-aware** (vs websocket/SSE greenfield), timeline/alertes **dérivées** & arrivée/début/fin
  **différés** (aucune source), **extension** au-delà de l'Épic 6 analytique vers §7.2/§17 borné MVP,
  périmètre d'**émission de nom d'affichage**. Entrée dans **`docs/adr/README.md`**.
- **`backend/README.md`** — sous-section « Dashboard Manager — activité du salon (#148) » : routes
  `dashboard/*`, permission (**sixième+** usage de `STATS_READ_SALON`), définitions dérivées, note
  explicite « arrivée/début/fin de prestation non représentés au MVP (aucune source) », exemples `curl`.
- **`web-dashboard/README.md`** — écran d'activité `/gerant` (filtre de période, cartes + évolution,
  graphiques SVG, listes en-cours/activité/alertes, skeletons, auto-refresh), extension du
  `http-stats-gateway`.
- **`README.md` racine §6** — phrase de statut « Dashboard Manager activité (#148) livré » (style M5).
- **OpenAPI** — `summary`/`responses`/docstrings documentent les nouvelles API (visible sur `/docs`).
- **BACKLOG.md** — marquer #148 livré le cas échéant (géré hors phase de code par le pipeline).

## Risks and Open Questions

1. **[Décision structurante] « En cours » dérivé vs nouveau statut ; « en attente » vs file d'attente ;
   seuils d'alerte.** Recommandation : **dériver** « en cours » (`CONFIRMED` ∩ `slot @> now`) **sans**
   statut ni migration ; « en attente » = RDV `PENDING`. Un vrai suivi arrivée/début/fin (pointage,
   borne §17, QR §16.7) et une file d'attente sont **hors MVP** (§21, « Could Have » §22) et
   deviendraient un épic distinct (nouveau statut + colonnes d'horodatage + action + migration). Les
   **seuils** d'alerte (retard, attente prolongée) sont des **constantes de domaine** documentées et
   ajustables. **À confirmer / acter en ADR-0039.**
2. **Définition de « nombre de clientes ».** Recommandation : **comptes distincts avec un RDV
   `COMPLETED`** sur la période (une « visite » §8.1, cohérent avec #42 `active = new + recurring`).
   Alternatives : comptes distincts avec **tout** RDV (tous statuts), ou nombre de RDV. **À confirmer**
   (le libellé « nombre de clientes » suggère des **personnes** distinctes, pas des RDV).
3. **Endpoint KPI consolidé vs endpoints séparés.** Recommandation : **un** endpoint `dashboard/kpis`
   (un aller-retour, borne le coût du polling, tient « dashboard < 3 s » §12.1). Alternative : quatre
   endpoints réutilisant #39/#40/#42 (plus granulaire mais 4× appels par tick). **À confirmer.**
4. **[Décision de dépendance] Graphiques.** Recommandation : **SVG inline hand-rollé** (Server
   Component, aucune dépendance, SSR-friendly, cohérent avec le design system Tailwind et l'éthos
   « aucun call/dépendance superflu »), guidé par le skill `dataviz`. Alternative : une lib légère
   (Recharts/visx/Chart.js) — ajoute une dépendance **client**, du poids de bundle et de l'hydratation
   ; à ne retenir que si une interactivité riche (tooltips/zoom) devient requise. **À confirmer.**
5. **[Décision d'architecture] Mécanisme d'auto-refresh.** Recommandation : **polling client
   visibility-aware** via `router.refresh()` (re-rendu serveur, **jeton jamais exposé**, aucun nouveau
   BFF), intervalle ≥ 30 s, pause onglet masqué. Alternatives : (a) **BFF de polling ciblé** (rafraîchit
   seulement les panneaux « maintenant » — moins de charge serveur mais + de surface BFF) ; (b) **SWR**
   (ajoute une dépendance) ; (c) **websocket/SSE** (greenfield backend, hors périmètre — le backend est
   requête/réponse pur, ADR-0038 « liveness-only », pas d'infra de push). L'intervalle et la
   visibility-pause honorent §12.1 (aucun appel superflu). **À confirmer.**
6. **Permission des vues opérationnelles / alertes.** Recommandation : réutiliser **`STATS_READ_SALON`**
   pour tout `dashboard/*` (cohérence, `MANAGER` seul). L'alerte « anomalie de paiement » dérive de #36
   (`CASH_JOURNAL_READ`) — soit l'endpoint `alerts` reste sous `STATS_READ_SALON` en réutilisant le
   dépôt paiements (le `MANAGER` détient les deux permissions), soit un endpoint dédié `CASH_JOURNAL_READ`.
   **À confirmer** (recommandation : `STATS_READ_SALON` unique pour l'écran d'activité).
7. **Index de couverture.** `slot @> now` et les séries `GROUP BY date_trunc` n'ont pas d'index dédié
   parfait ; les index existants `(salon_id, appointment_date)` / `(salon_id, created_at)` couvrent
   l'essentiel. Recommandation : **aucun nouvel index au MVP** (volume salon faible) ; mesurer (#52)
   avant d'ajouter un index (ex. GiST sur `slot`, ou `(salon_id, status, appointment_date)`). **À
   confirmer.**
8. **Un ADR est-il nécessaire ?** Recommandation : **oui, ADR-0039** — #148 introduit **plusieurs**
   décisions transverses et **étend le périmètre** au-delà de l'Épic 6 analytique (l'issue demande
   explicitement de « documenter dans l'ADR/la spec » la définition « en cours »). **À confirmer.**
9. **Lecture salon des `notifications` (timeline).** La timeline « nouvelles réservations / annulations /
   modifications » nécessite un **nouveau** `NotificationRepository.list_for_salon` — ce qui
   **matérialise la lecture salon différée** par #47/#48 (parité, sans remise). Recommandation :
   l'implémenter **borné (top-N)** et **neutre** (aucune PII au-delà du nom d'affichage éventuel).
   Alternative MVP plus étroite : timeline = **paiements uniquement** (source la plus riche et déjà
   lisible). **À confirmer** (portée de la timeline).
10. **Réorganisation UX de `/gerant`.** #148 réunit l'écran d'activité **et** les panneaux #41/#42/#43.
    Recommandation : placer l'**écran d'activité en haut** (cartes + graphiques + en-cours + alertes),
    et **conserver** les panneaux analytiques (#41/#42/#43) en dessous (aucune régression). **À
    confirmer** (arbitrage produit sur la densité §UX « éviter la surcharge »).
11. **Cohérence temporelle du fuseau.** « Maintenant » (`is_in_progress`, retard) est calculé en
    `Africa/Abidjan` (UTC+0, convention #21) ; les bornes de période sont des **jours civils**. Vérifier
    l'absence de dérive de fuseau entre `now` serveur, `appointment_date`+`start_time` (naïfs) et
    `slot` TSRANGE. **À vérifier** en tests e2e.

## Implementation Checklist

**Backend**
1. **Lire** `adapters/inbound/stats.py`, `adapters/outbound/persistence/appointment_repository.py`
   (`count_by_status_for_day`, `segment_active_clients`, `performance_by_hairdresser`, `list_for_salon`),
   `domain/revenue.py` (`*_bounds`), `domain/discrepancy.py`, `application/ports/payment_repository.py`
   (`list_for_salon`, `*_completed_without_payment`) — s'imprégner des patrons #39–#43/#36.
2. **Trancher** les Open Questions 1–11 (surtout « en cours » dérivé, « en attente », « nombre de
   clientes », endpoint consolidé, graphiques SVG, auto-refresh) et **acter en ADR-0039** + README.
3. **Domaine** : créer `domain/dashboard.py` (`resolve_period`, `previous_period`, `Evolution`/
   `compute_evolution`, `is_in_progress`, `__all__`) ; écrire `tests/test_domain_dashboard.py` **avant**
   les use cases.
4. **Ports** : ajouter à `AppointmentRepository` les agrégats de plage + `list_in_progress_details`
   (+ `count_in_progress`) ; ajouter `NotificationRepository.list_for_salon` (docstrings : isolation
   §11.2 en SQL, `client_id` non émis pour les agrégats, nom d'affichage seul pour les listes, lecture
   pure).
5. **Use cases** : créer `application/dashboard.py` (`SummarizeDashboardKpis`, `ListInProgressServices`,
   séries, `activity`, `alerts` ; statuts imposés serveur ; aucun audit) ; `tests/test_dashboard_usecase.py`
   via fakes (compléter `conftest.py`).
6. **Adapters outbound** : implémenter les nouveaux agrégats (SQL, `WHERE salon_id`, `client_id` non
   sélectionné pour les counts), `list_in_progress_details` (joins `users`×2 + `services`, `slot @> now`),
   `notification_repository.list_for_salon` (top-N, `ORDER BY created_at DESC`).
7. **Adapters inbound** : ajouter à `stats.py` les schémas Pydantic **explicites** (aucune PII sur les
   counts-only ; nom d'affichage seul sur les listes) et les routes `dashboard/kpis`,
   `dashboard/revenue-series`, `dashboard/attendance-series`, `dashboard/in-progress`,
   `dashboard/activity`, `dashboard/alerts` (gardes `require_salon_scope` +
   `require_permission(STATS_READ_SALON)`, période + `date_to < date_from → 422`, OpenAPI documenté ;
   DI réutilisée). **Ne pas** toucher `PUBLIC_ROUTE_PATHS` ; actualiser le **commentaire** d'en-tête du
   router `stats` / `main.py`.
8. **Tests API & e2e** : `tests/test_dashboard_api.py` (200/401/403/422, non-PII, isolation, défaut de
   période, non-collision, `unprotected_routes == []`) ; `tests/test_dashboard_e2e.py` (agrégats SQL
   réels, `slot @> now`, joins de noms, séries, isolation). Exécuter `pytest` (+ `DATABASE_URL` e2e) et
   `ruff check`.
9. **Documentation backend** : `backend/README.md` (routes + usage `STATS_READ_SALON` + définitions
   dérivées + note arrivée/début/fin non représentés).

**Web**
10. **Domaine & accès** : `src/domain/dashboard/period.ts` + `kpi.ts`/`activity.ts`/`alerts.ts`
    (types + formatage, parité UTC) (+ tests) ; étendre `stats-gateway.ts` + `http-stats-gateway.ts`
    (nouvelles méthodes, jeton serveur, mapping défensif) (+ tests).
11. **UI & page** : créer `period-filter.tsx`, `dashboard-kpi-cards.tsx`, `revenue-chart.tsx`,
    `attendance-chart.tsx`, `in-progress-list.tsx`, `activity-timeline.tsx`, `alerts-panel.tsx`,
    `dashboard-skeleton.tsx`, `auto-refresh.tsx` + `app/(gerant)/gerant/loading.tsx` ; brancher dans
    `app/(gerant)/gerant/page.tsx` (searchParams période, chargements parallèles, dégradation locale,
    `<AutoRefresh>`). Respecter les états loading/empty/error.
12. **Tests Vitest** (période, gateways, cartes, charts SVG, listes, auto-refresh visibility-aware,
    états) ; étendre `gerant-dashboard-page.test.ts` ; `web-dashboard/README.md`.

**Documentation & vérification finale**
13. Rédiger **ADR-0039** + entrée `docs/adr/README.md` ; mettre à jour `README.md` racine (avancement
    Épic 6 / activité #148).
14. `scripts/test-gate.sh` au vert (pytest + npm test + flutter test), `ruff check`, `npm run lint &&
    npm run build` ; relire la PR : **aucune PII/secret** (`client_id`, téléphone, e-mail, jeton) en logs
    ou messages d'erreur ; nom d'affichage émis **uniquement** par les listes opérationnelles ; **aucune
    signature IA** introduite ; **aucune** migration.
