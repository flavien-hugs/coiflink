# ADR-0039 : Dashboard Manager — activité du salon : « en cours » dérivé, période + évolution, graphiques SVG sans dépendance, auto-refresh visibility-aware

- **Statut** : Accepté
- **Date** : 2026-08-09
- **Décideurs** : équipe CoifLink
- **Issue** : #148 (Dashboard Manager · Activité du salon)
- **Référence PRD** : §6 Épic 6 (extension), §7.2 (« Dashboard principal »), §8.1, §8.4, §11.2, §11.3,
  §11.4, §12.1, §12.2, §17 (Borne Intelligente, hors MVP), §21/§22 (périmètre MVP)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, `STATS_READ_SALON`),
  [ADR-0031](./0031-performance-des-coiffeurs.md) (émission maîtrisée d'un nom d'affichage),
  [ADR-0028](./0028-detection-ecarts-de-caisse.md) (écarts de caisse), [ADR-0006](./0006-notifications-fcm-sms.md)
  (messages neutres) et les **KPI dashboard livrés** (#39–#43, décisions pliées dans les README)

## Contexte et problème

Le PRD pose deux besoins que #148 réunit : l'analytique de l'Épic 6 (RDV du jour, CA, prestations
demandées, clients actifs, performance coiffeurs — livrés #39–#43) et l'écran « Dashboard principal »
(§7.2), qui liste des indicateurs « temps réel » absents du socle : clients en attente, prestations en
cours, transactions récentes, alertes importantes. L'issue #148 demande un écran consolidé avec quatre
cartes KPI + évolution, un filtre de période, deux graphiques, une liste d'en-cours, une timeline et des
alertes, actualisés automatiquement.

Plusieurs notions demandées **n'existent pas** dans le modèle MVP : aucun statut `IN_PROGRESS` (cinq
statuts seulement — PRD §9.4), aucune colonne d'horodatage d'arrivée/début/fin, aucune file d'attente,
aucune librairie de graphiques, aucun mécanisme de rafraîchissement serveur (le backend est
requête/réponse pur), aucun filtre de période unifié, aucun nom résolu sur la liste des RDV. #148
introduit **plusieurs décisions transverses** qui dépassent le pli habituel dans un README (patron
#41/#42) et étendent le périmètre au-delà de l'Épic 6 analytique — ceci justifie un ADR dédié.

## Décision

Consolider, au-dessus du socle #39–#43, un écran d'activité **entièrement dérivé en lecture** (aucune
migration, aucun nouveau statut) sur le router `stats` existant (`adapters/inbound/stats.py`), sixième+
consommateur de `STATS_READ_SALON`.

### 1. « En cours » dérivé (sans statut ni migration) ; « en attente » = `PENDING`

**« Prestations en cours »** = RDV `CONFIRMED` dont le créneau `[appointment_date+start_time,
appointment_date+end_time)` **contient l'instant présent** (`domain/dashboard.py::is_in_progress`,
fuseau salon `Africa/Abidjan` = UTC+0, naïf) — répliqué en SQL par le prédicat réel de la colonne
générée `slot` (`slot @> now::timestamp`, déjà présente pour l'exclusion anti-double-réservation #21).
**Aucune** valeur d'énum `IN_PROGRESS`/`ARRIVED`, aucune colonne d'horodatage de transition, aucune
migration, aucune machine à états. **« Clients en attente »** = RDV `PENDING` sur la période — la
source « queue » la plus proche existante ; aucune salle d'attente walk-in (concepts §16.7/§17, hors
MVP §21). Un vrai suivi arrivée/début/fin (pointage, borne, QR) reste un épic distinct, différé. Les
**seuils** des alertes `late`/`prolonged_wait` sont des constantes de domaine documentées
(`application/dashboard.py`), ajustables sans migration.

### 2. « Nombre de clientes » = comptes distincts avec un RDV `COMPLETED` sur la période

Une « visite » (§8.1), cohérent avec `active = new + recurring` de #42 — des **personnes** distinctes,
pas un nombre de RDV. Agrégat `COUNT(DISTINCT client_id)` en base (`client_id` compté, jamais émis,
anti-oracle §11.1). « Chiffre d'affaires » reste le **net `cash_journal`** (`PAYMENT`/`ADJUSTMENT`, net
des corrections #34), généralisé à une plage arbitraire (pas seulement jour/semaine/mois de #40).

### 3. Filtre de période unifié + endpoint KPI **consolidé**

`DashboardPeriodKind = today | week | month | custom`, résolu **côté serveur**
(`domain/dashboard.py::resolve_period`, réutilise `day_bounds`/`week_bounds`/`month_bounds` de
`domain/revenue.py` — sémantique identique au CA #40) en bornes de jour civil `[date_from, date_to]`.
`custom` exige ses deux bornes ; `date_to < date_from` → `422`. L'**évolution** compare à la
**période précédente de même longueur** (`previous_period`, contiguë) — calculée **côté serveur**
(`Evolution`/`compute_evolution`), le front ne recalcule rien. Les 4 KPI sont exposés par **un seul**
endpoint consolidé (`GET /dashboard/kpis`) plutôt que quatre endpoints séparés réutilisant #39/#40/#42 :
un aller-retour au lieu de quatre par tick d'auto-refresh, ce qui borne le coût du polling (§12.1) et
tient le budget « dashboard < 3 s ». Les séries (`revenue-series`/`attendance-series`) et les vues
opérationnelles (`in-progress`/`activity`/`alerts`) restent des endpoints dédiés (formes de réponse
distinctes : buckets, listes nominatives, alertes).

### 4. Graphiques : SVG inline, **sans nouvelle dépendance**

`web-dashboard/package.json` ne portait que `next`/`react`/`react-dom` avant #148 et n'en porte
toujours pas d'autre après : les deux graphiques (évolution du CA, fréquentation) sont rendus en **SVG
inline côté serveur** (Server Component, `revenue-chart.tsx`/`attendance-chart.tsx`/
`dashboard-bar-chart.tsx`), sans dépendance client, sans hydratation supplémentaire, cohérent avec
l'éthos « aucun call/dépendance superflu » et le design system Tailwind existant. Une librairie de
charting (Recharts/visx/Chart.js) reste une option **future**, à ne retenir que si une interactivité
riche (tooltip/zoom) devient un besoin produit explicite — non requis par l'issue.

### 5. Auto-refresh : polling client **visibility-aware**, aucun websocket/SSE

Le backend reste un service **requête/réponse pur** (aucune occurrence de
`websocket|SSE|EventSource|StreamingResponse|poll|BackgroundTasks` avant #148) ; l'infrastructure
temps-réel push (websocket/SSE) est **greenfield** et hors périmètre. L'auto-refresh (`<AutoRefresh>`,
`src/adapters/ui/auto-refresh.tsx`) déclenche `router.refresh()` à intervalle (`setInterval`), qui
**re-exécute le Server Component** `/gerant` — le jeton du cookie `httpOnly` reste lu **côté serveur**,
**jamais exposé au client** (invariant #14). Le rafraîchissement **se met en pause** quand l'onglet est
masqué (Page Visibility API, `document.visibilityState`) pour ne pas émettre d'appel superflu (§12.1).
Aucun nouveau Route Handler BFF de polling ciblé n'a été nécessaire : le fetch serveur direct +
`router.refresh()` suffisent (patron #40/#41).

### 6. Permission unique : `STATS_READ_SALON` pour tout `dashboard/*`, y compris `alerts`

Toutes les routes `dashboard/*` réutilisent **exclusivement** `STATS_READ_SALON` + `require_salon_scope`
(isolation §11.2) — **aucune** modification de `ROLE_PERMISSIONS`. L'alerte « anomalie de paiement »
dérive du dépôt paiements (`count_completed_without_payment`, #36, normalement sous
`CASH_JOURNAL_READ`) mais l'endpoint `dashboard/alerts` reste sous la permission unique
`STATS_READ_SALON` : le `MANAGER` détient les deux permissions, et l'écran d'activité gagne en
cohérence (une seule permission à vérifier pour tout l'écran) sans élargir l'accès à un rôle qui n'a
pas déjà l'un ou l'autre.

### 7. Timeline & alertes : dérivées, bornées aux faits **réellement horodatés**

La timeline (`GET /dashboard/activity`, §7.2 « Transactions récentes ») fusionne, triés par horodatage
décroissant et **bornés (top-N, `ACTIVITY_LIMIT_DEFAULT=20`, borne `[1, 100]`)** : les **paiements**
(nom d'affichage + montant, patron #36/#43) et les **notifications salon**
`NEW_BOOKING`/`CANCELLATION`/`APPOINTMENT_UPDATE` (#47/#48, libellé neutre ADR-0006) — ce qui
**matérialise enfin** la lecture salon-scopée des notifications différée par #47/#48
(`NotificationRepository.list_for_salon`, nouveau). Une paire `(type, appointment_id)` est
**dédupliquée** (un seul évènement métier par transition). « Arrivée cliente / début / fin de
prestation » **ne figurent pas** : aucune source ne les horodate au MVP (documenté explicitement dans
les docstrings OpenAPI de la route). Les alertes (`GET /dashboard/alerts`) dérivent de faits déjà
lisibles : `payment_anomaly` (écarts de caisse #36), `late` (RDV `CONFIRMED` dont le créneau est passé
sans clôture), `prolonged_wait` (RDV `PENDING` du jour dont le début est dépassé) — ne renvoyées que si
leur effectif est `> 0`, dans un ordre d'affichage stable (`payment_anomaly → late → prolonged_wait`).

### 8. Isolation, non-PII, lecture pure — inchangés par rapport au socle #39–#43

Chaque route est salon-scopée (`require_salon_scope`) **et** re-filtrée `WHERE salon_id` en SQL (défense
en profondeur §11.2) ; un salon hors périmètre est un `403` générique (aucun oracle). Les endpoints
counts-only (`kpis`, `revenue-series`, `attendance-series`) n'émettent **aucune** PII — schémas Pydantic
explicites, `client_id` groupé mais jamais sélectionné. Les endpoints opérationnels
(`in-progress`/`activity`/`alerts`) émettent **uniquement** le nom d'affichage (`users.full_name`,
`services.name`, patron #43/#36) — jamais `client_id`/`user_id`/contact. Aucune écriture, aucun audit
§11.4 (lecture pure, parité #39–#43). Aucune migration : `slot` (TSRANGE) et les index couvrants
(`ix_appointments_salon_id`, `ix_cash_journal_salon_id`, `ix_notifications_salon_id`) existaient déjà ;
aucun index dédié n'a été ajouté au MVP (volume salon faible — à mesurer avant d'optimiser, §12.1).

## Conséquences

- **Positif.** Le gérant dispose d'un écran d'activité « temps réel » cohérent avec le PRD §7.2, sans
  aucune migration ni nouvelle permission, entièrement dérivé de faits réels (aucun mock). Le filtre de
  période et l'évolution sont réutilisables par de futurs KPI. Les graphiques SVG et l'auto-refresh
  visibility-aware évitent toute nouvelle dépendance client et tout appel superflu.
- **Compromis.** « Prestations en cours » reste un **instantané** approximatif (dérivé du planning, pas
  d'un pointage réel) — un client arrivé en retard sur un créneau `CONFIRMED` compte comme « en cours »
  dès l'heure prévue, pas à l'arrivée réelle. « Clients en attente » (`PENDING`) ne reflète aucune file
  d'attente en salle. Ces écarts sont **assumés** et documentés (README backend, réponses OpenAPI) ; un
  vrai suivi arrivée/début/fin (pointage, borne §17, QR §16.7) est un **épic distinct**, hors MVP.
- **Sécurité.** L'émission de nom d'affichage sur `in-progress`/`activity` (client **et** coiffeur)
  élargit légèrement l'émission maîtrisée déjà actée par #43 (coiffeur seul) — bornée au salon du
  gérant, jamais un contact. L'alerte `payment_anomaly` sous `STATS_READ_SALON` (plutôt que
  `CASH_JOURNAL_READ`) est un choix de cohérence d'écran, pas un élargissement de rôle.
- **Suivi.** Un test e2e SQL réelle (PostgreSQL 16, `tests/test_dashboard_e2e.py`) verrouille les
  chemins ajoutés : prédicat `slot @> now`, jointures de noms, agrégats `GROUP BY` + conversion de
  fuseau (`net_revenue_series`), flux fusionné/dédupliqué/trié de la timeline, alertes dérivées,
  isolation inter-salons, absence de PII sur les endpoints counts-only.
