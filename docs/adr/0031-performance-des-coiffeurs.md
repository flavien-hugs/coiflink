# ADR-0031 : Performance des coiffeurs — lecture salon-scopée `STATS_READ_SALON`, CA net attribué par RDV, émission maîtrisée de l'identité employé

- **Statut** : Accepté
- **Date** : 2026-08-03
- **Décideurs** : équipe CoifLink
- **Issue** : #43 (US-6.5 — Performance des coiffeurs, dashboard gérant)
- **Référence PRD** : §6 Épic 6 (US-6.5), §8.1 (réalisé = `COMPLETED`, devise XOF, `NUMERIC(12,2)`), §8.2 (paiement lié à un RDV ou une prestation, journal net), §11.2 (isolation par salon), §11.3 (non-fuite PII), §12.1 (garde de coût)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, `STATS_READ_SALON`),
  [ADR-0027](./0027-encaissement-coherence-montant.md) (encaissement, journal & correction #34) et les **KPI dashboard livrés** (#39 RDV du jour, #40 CA, #41 prestations les plus demandées, #42 clients actifs — décisions pliées dans les README)

## Contexte et problème

Le PRD (§6 Épic 6, US-6.5) pose : « en tant que gérant, je veux mesurer la performance de mes coiffeurs », spécifié par trois indicateurs — **prestations réalisées**, **CA généré**, **taux d'annulation**. Le critère d'acceptation de #43 est : **« Indicateurs par coiffeur cohérents avec le planning et la caisse. »**

C'est le **cinquième KPI** du tableau de bord gérant (Épic 6). Le socle existe déjà, établi par lecture du code : l'assignation d'un RDV à un coiffeur (`appointments.hairdresser_id`, posée par #25/#27) est **matérialisée mais jamais encore agrégée** au niveau salon ; le router `stats` (`adapters/inbound/stats.py`, garde `STATS_READ_SALON` + `require_salon_scope`) porte déjà quatre endpoints et **deux DI surchargeables** (`get_appointment_repository`, `get_cash_journal_repository`) ; le CA du salon est défini comme le **net du journal de caisse** (#40/#34). #43 étend cette surface d'un cinquième endpoint, **sans migration ni changement de schéma** — tout est dérivé en lecture.

Deux décisions ne sont **pas triviales** et justifient cet ADR (plus que #41/#42, qui ont plié leurs décisions dans les README) : (a) la **définition du « CA par coiffeur »** et (b) l'**émission de l'identité d'un employé** dans une réponse stats — un départ assumé du patron counts-only de #42.

## Décision

Ajouter une **tranche verticale de lecture pure** (`GET /salons/{salon_id}/hairdresser-performance`, garde `STATS_READ_SALON` + portée salon) exposant, **par coiffeur** assigné à ≥ 1 RDV du salon sur une période, les trois indicateurs. Aucune écriture, aucun audit, aucune migration.

### 1. CA par coiffeur = **net de la caisse, attribué par RDV** (pas `price_at_booking`)

Le CA d'un coiffeur est la somme **signée** des lignes `cash_journal` `PAYMENT`/`ADJUSTMENT` du salon, **attribuée** par la chaîne `cash_journal → payments.appointment_id → appointments.hairdresser_id`, **net des corrections** (#34, parité #40/#37). C'est possible ici — un paiement de RDV porte **un** coiffeur — là où #41 ne pouvait pas ventiler un paiement multi-prestations (d'où son recours à `price_at_booking`). Cela rend « cohérent avec **la caisse** » **vrai par construction**. L'alternative (somme des `price_at_booking` des RDV `COMPLETED` assignés — source unique `appointments`, « cohérent avec le planning ») est **écartée** : elle divergerait du cash net (RDV réalisé non payé compté, correction ignorée), comme #41. L'architecture (ports + domaine) supporterait les deux sans changer la forme de la réponse.

**Écarts de couverture assumés.** Les paiements **sans RDV** (`appointment_id IS NULL`) et les RDV **non assignés** (`hairdresser_id IS NULL`) sont **inattribuables** → exclus des lignes coiffeur ; la somme des CA par coiffeur peut **différer** du CA salon #40. Le CA est borné par **`appointment_date`** (axe **planning**), pas `cash_journal.created_at` (axe #40) : cela **aligne les trois indicateurs sur la même période** (renforçant « cohérent avec le planning **et** la caisse »), au prix d'une divergence possible avec le CA #40 sur une même fenêtre. Ces écarts sont **documentés** (README backend).

### 2. Émission **maîtrisée** de l'identité employé (départ assumé du counts-only #42)

La réponse émet le `hairdresser_id` **et** le **nom d'affichage** (`hairdresser_name = users.full_name`) : c'est **nécessaire** au KPI (« performance **des coiffeurs** ») et **légitime** (le gérant gère ses employés, `EMPLOYEE_MANAGE` #13). Cette émission suit une **convention déjà en place** — `CashJournalRepository.list_for_salon` (#34) résout déjà `performed_by → users.full_name` « sans exposer d'autre donnée sensible de l'auteur (§11.3) ». La réponse **n'émet jamais** `phone`, `email`, `role`, `status` de l'employé, ni aucune PII **client** (`client_id`/`appointment_id`). C'est le **seul** endpoint stats nominatif — à la différence de #42 (anti-oracle client, `client_id` jamais émis) ; la distinction est **délibérée** : un **employé du salon** ≠ un **client tiers**.

### 3. Trois indicateurs, chacun **cohérent avec son autorité** ; règle métier pure

Prestations réalisées (occurrences `appointment_services` des RDV `COMPLETED`) et taux d'annulation (RDV `CANCELLED` / **tous** les RDV assignés) dérivent **du planning** ; le CA dérive **de la caisse**. Les statuts (`COMPLETED`, `CANCELLED`) sont **décidés serveur** (`REVENUE_STATUSES`, `CANCELLED_STATUSES`), jamais soumis. Un `NO_SHOW` (absence) ne compte **pas** comme annulation (statut distinct). Les compteurs/sommes sont calculés **en base** (deux `GROUP BY hairdresser_id`, `COUNT`/`SUM(CASE …)` + sous-requête `COUNT(appointment_services)` — le comptage d'occurrences est **séparé** de celui des RDV pour ne pas sur-compter) ; le **calcul du taux** (division protégée, `Decimal`) et l'**ordre** du classement (CA décroissant, puis prestations, puis nom) sont une **fonction pure du domaine** (`domain/hairdresser_performance.py::rank_hairdresser_performance`), testable sans base. La liste des coiffeurs dérive **du planning** : un coiffeur avec du CA mais aucun RDV assigné dans la fenêtre n'apparaît pas.

### 4. Isolation §11.2 en profondeur, RBAC inchangé, lecture pure

Route salon-scopée (`require_salon_scope` → `403` **générique**, aucun oracle) **et** re-filtrage `WHERE appointments.salon_id` / `cash_journal.salon_id` **inconditionnel** en SQL. Un même compte membre de deux salons est mesuré **par salon**. `STATS_READ_SALON` est **déjà** au seul `MANAGER` : **aucune** modification de `ROLE_PERMISSIONS` (un coiffeur ne lit pas sa propre performance via #43). Aucune écriture, **aucun** audit §11.4 (patron des lectures #39/#40/#41/#42) ; aucun chemin ajouté à `PUBLIC_ROUTE_PATHS` (l'invariant `unprotected_routes(app) == []` couvre automatiquement la nouvelle route).

### 5. Aucune migration ; index existants suffisants

`REVENUE_STATUSES`/`AppointmentStatus`/`CashOperationType`/`ROLE_PERMISSIONS` réutilisés tels quels. Un `CANCELLED_STATUSES` **domaine** est ajouté comme simple constante Python (sans effet base). Les index `ix_appointments_salon_id (salon_id, appointment_date)`, `ix_payments_appointment_id`, `ix_cash_journal_salon_id` couvrent la requête ; un index composite `(salon_id, hairdresser_id, appointment_date)` reste une **optimisation future** (mesure d'abord — volume salon faible au MVP, §12.1 tenu).

## Conséquences

- **Positif.** Le gérant pilote son staffing, sa répartition de charge et son coaching avec trois indicateurs **cohérents avec leurs autorités** (planning + caisse). Cinquième endpoint sur un router stats mûr, sans migration ni nouvelle permission. Domaine pur et testé ; agrégats en base (non-PII, indexés). Le web `/gerant` ajoute un panneau « Performance des coiffeurs » sous les clients actifs, avec **dégradation locale** sur panne (patron #42).
- **Compromis.** Le CA par coiffeur **ne réconcilie pas** le CA salon #40 (résidu inattribuable des paiements sans RDV / RDV non assignés ; axes temporels distincts). Une éventuelle ligne « Non attribué » agrégée, ou une matrice coiffeur × prestation / série temporelle, sont des **suivis produit** (post-MVP, PRD §16/§21).
- **Sécurité.** L'émission du nom d'affichage employé est un **départ assumé** du counts-only #42, borné (jamais de contact) et conventionnel (#34) — acté ici pour tracer la décision. Le taux et le CA restent en `Decimal` (jamais un flottant), transportés en chaîne.
- **Suivi.** Un test e2e SQL réelle (PostgreSQL 16, `DATABASE_URL`) verrouille les chemins : agrégat par coiffeur, **attribution du CA** via `cash_journal → payments → appointments`, filtres `COMPLETED`/`CANCELLED`, RDV non assignés exclus, isolation inter-salons, absence de PII.
