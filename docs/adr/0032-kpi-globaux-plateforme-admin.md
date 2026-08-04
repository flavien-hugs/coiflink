# ADR-0032 : KPI globaux de la plateforme (admin) — instantané consolidé gardé par `STATS_READ_PLATFORM`, revenu net via `cash_journal`, report du KPI abonnements

- **Statut** : Accepté
- **Date** : 2026-08-03
- **Décideurs** : équipe CoifLink
- **Issue** : #44 (US-6.6 — KPI globaux plateforme, admin)
- **Référence PRD** : §6 Épic 6 (US-6.6), §7.3 (Interface admin — Dashboard admin), §13 (KPI de succès), §11.2 (isolation par salon), §11.3 (non-fuite PII), §11.4 (journalisation des actions, pas des consultations), §12.1 (garde de coût), §15.1 (modèle SaaS par abonnement)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, isolation par salon),
  [ADR-0029](./0029-supervision-agregee-transactions-admin.md) (#37 — lecture plateforme `STATS_READ_PLATFORM`,
  net via `cash_journal`, helpers `domain/time_window.py`, port dédié) et le **socle KPI salon** de l'Épic 6
  (#39–#43, patron des lectures statistiques en base ; bornes de mois `domain/revenue.py::month_bounds` #40)

## Contexte et problème

L'**Admin CoifLink** (super-administrateur plateforme, PRD §2/§4.1) doit disposer d'un **tableau de bord de pilotage global** exposant l'état agrégé de **toute** la plateforme : combien de salons sont inscrits, combien de rendez-vous ont été pris, quel revenu transite par CoifLink (PRD §7.3 « Dashboard admin », §13.1/§13.3).

Avant #44, **une seule** lecture plateforme existait : `GET /admin/transactions/summary` (#37, ADR-0029), qui renvoie une liste **par salon** d'agrégats de transactions. Il n'existait **aucune** vue de **KPI globaux consolidés** (compteurs et totaux à l'échelle de la plateforme entière). Toutes les autres lectures statistiques (Épic 6, #39–#43) sont **salon-scopées** (`STATS_READ_SALON`, montées sous `/salons/{salon_id}/…`) : par construction inaccessibles à l'admin.

Le critère d'acceptation du backlog est :

> **Dashboard admin avec KPI globaux agrégés.** KPI listés : salons inscrits, abonnements, rendez-vous, revenus plateforme.

**Écart notable — les « abonnements ».** Le PRD décrit un modèle SaaS par abonnement (§15.1) et une gestion d'abonnements côté admin (§7.3). **Or aucun modèle de données d'abonnement / facturation n'existe dans le backend** (aucune table, aucun domaine, aucun enum). Le KPI « abonnements » ne peut donc **pas** être calculé à partir de données réelles, et la mise en place d'un système d'abonnement/facturation est un **épic distinct** (hors backlog M5), pas le périmètre d'une US de tableau de bord (Effort M).

## Décision

Ajouter une **tranche verticale de lecture plateforme** `GET /admin/kpis` qui **calcule en base** un **instantané unique** (non paginé) de KPI globaux et l'expose comme **nouvelle route du router `/admin` existant** (#37). Aucune écriture, aucune migration, aucune PII, aucun audit, aucune modification de la matrice RBAC.

### 1. Garde : `require_permission(STATS_READ_PLATFORM)` seule (pas de `require_salon_scope`)

La route est gardée par `require_permission(STATS_READ_PLATFORM)` **uniquement** — identique à #37 (ADR-0029 §1). L'`ADMIN` est le **seul** rôle porteur (`ROLE_PERMISSIONS` fermée, §4.1 non modifiée) → `401` sans jeton, `403` générique pour tout autre rôle, `403` « Compte désactivé. » pour un admin non `ACTIVE`. `STATS_READ_PLATFORM` a désormais **deux** consommateurs (#37 supervision, #44 KPI globaux). `require_salon_scope` n'est **pas** utilisé : l'admin voit toute la plateforme (`AccessPolicy.scope_of` → `SalonScope.platform()`), lecture plateforme légitime (§11.2), pas un contournement d'isolation.

### 2. Périmètre des KPIs : les 4 du backlog **adossés à des données réelles**, + salons actifs & clients inscrits

La réponse porte : **salons inscrits** (`salons_total` + `salons_active`, PRD §7.3 « Salons actifs »), **clients inscrits** (`clients_total`, comptes de rôle `CLIENT` uniquement, PRD §13.1), **rendez-vous** (`appointments_total` + `appointments_this_month`) et **revenus plateforme** (`revenue_total` + `revenue_this_month`). Peu de coût, forte valeur, alignés PRD §7.3/§13.1.

### 3. **Report du KPI « abonnements »** — aucun modèle, aucun nombre inventé

#44 **n'introduit ni table, ni domaine, ni endpoint** de gestion d'abonnements, et **n'émet aucun champ `subscriptions`** : on ne fabrique pas un nombre d'abonnements à partir de données inexistantes. Le KPI « salons inscrits / actifs » couvre le besoin de pilotage adossé à des données réelles ; l'UI admin peut **libeller** `salons_active` « salons abonnés (actifs) ». La mise en place d'un système d'abonnement/facturation (plans tarifaires, échéances, statut paiement, historique) est un **épic distinct**, hors #44.

Alternative rejetée : émettre `subscriptions: null`. Un champ explicitement nul aurait tracé l'absence de modèle, mais alourdit le contrat public pour une donnée inexistante ; le libellé de `salons_active` suffit au MVP. Le champ reste **ré-introductible** sans rupture quand l'épic abonnement débarquera.

### 4. « Revenus plateforme » = flux net encaissé (`cash_journal`), **≠** « revenus d'abonnement »

`revenue_total` / `revenue_this_month` = **somme signée** des lignes `cash_journal.amount` (`PAYMENT` positif, `ADJUSTMENT` signé) sur **tous** les salons — le **montant net** encaissé, **même source de vérité** que #37/#40 (ADR-0029 §2) : un paiement corrigé (#34) fait **baisser** le net. C'est le **flux net encaissé par les salons**, **pas** un revenu de facturation SaaS (qui n'existe pas — §3). Cette distinction est **explicite** dans les libellés (docstrings backend, futur UI) pour ne pas induire en erreur.

### 5. `appointments_total` = **volume créé** (tous statuts, `CANCELLED` inclus)

Un « nombre de rendez-vous » de pilotage **plateforme** reflète le **volume créé** (tous statuts, y compris `CANCELLED`), distinct du CA où « annulés exclus » (§8.1) est vrai par construction (un RDV `CANCELLED` n'a ni paiement ni ligne de journal, cf. ADR sur #40). Décision **figée par test** d'intégration SQL.

### 6. Instantané unique calculé **en base**, sans pagination ni série temporelle

Chaque KPI est un `SELECT` scalaire (`COUNT`/`SUM`) **en SQL** (garde de coût §12.1, jamais en mémoire) : `salons_total`/`salons_active` (couvert par `ix_salons_status`), `clients_total` (`WHERE role = 'CLIENT'`), `appointments_total`, `appointments_this_month` (`WHERE appointment_date BETWEEN month_from AND month_to` — `appointment_date` est **déjà** un jour civil `Africa/Abidjan`, **sans** conversion de fuseau), `revenue_total`, `revenue_this_month` (bornes de mois **converties en UTC** via `domain/time_window.py`, car `created_at` est timezone-aware). Pas de pagination (une poignée de scalaires), pas de série temporelle, pas de snapshot persisté : instantané calculé à la demande. La fenêtre mensuelle réutilise `domain/revenue.py::month_bounds` (#40) — aucune duplication calendaire. Le paramètre `reference_date` (optionnel, défaut = jour courant `Africa/Abidjan`) cadre la fenêtre du mois ; mal formé → `422` (validation Query FastAPI).

### 7. Non-PII (§11.3) — **plus fort que #37**, forme figée par test

La réponse ne porte **que** des scalaires globaux (compteurs, montants, dates, devise). **Aucune** identité d'entité n'est émise — ni `salon_id`/`salon_name` (contrairement à #37 qui exposait l'identité métier du salon comme unité d'agrégation), ni `client_id`, ni `owner_id`, ni `reference`, ni `recorded_by`, ni aucune ligne individuelle. Le schéma Pydantic liste des champs **explicites** (pas de fuite par `orm_mode`/`extra`) ; un test d'API **fige** la forme (échec si un champ interdit apparaît). Montants en `Decimal`/`NUMERIC(12,2)`, sérialisés en **chaîne** (jamais un flottant) — parité #37/#40.

### 8. Port dédié `PlatformKpiRepository`, lecture pure, deny-by-default

Les ports existants (`PaymentRepository`, `CashJournalRepository`, …) sont **inconditionnellement salon-scopés** (§11.2) ; des compteurs/sommes portant sur **toutes** les entités de la plateforme leur sont structurellement étrangers → un port dédié `PlatformKpiRepository.compute_snapshot(...)` (raison identique à #37, ADR-0029 §5). Comme les lectures #37/#39–#43, la consultation **ne journalise aucune action** (§11.4 vise les actions, pas les consultations). La route porte une garde de `Principal` et **n'est pas** publique-listée (`PUBLIC_ROUTE_PATHS` inchangée) — l'invariant `unprotected_routes(app) == []` la couvre automatiquement. **Aucune** migration : lecture pure agrégée sur les tables existantes.

## Conséquences

- **Positif.** L'admin dispose d'un instantané consolidé de pilotage plateforme (salons, clients, RDV, revenus) adossé à des données **réelles**, sans accéder à aucune identité d'entité (§11.3, non-PII renforcée vs #37). La tranche est hexagonale, pure et testée ; aucune migration, aucun nouvel index, aucune modification RBAC.
- **Compromis — KPI abonnements reporté.** Le backlog listait « abonnements » ; faute de modèle de données, le KPI est **reporté** (aucun nombre inventé) et couvert au libellé près par `salons_active`. Un épic « abonnements/facturation » distinct devra l'introduire (table, domaine, endpoints) — le champ `subscriptions` reste ré-introductible sans rupture de contrat.
- **Compromis — pas de drill-down ni de web admin.** #44 renvoie des scalaires globaux uniquement (le détail par salon est déjà `GET /admin/transactions/summary`, #37). La zone web `/admin` **n'existe pas encore** (comme après #37) : #44 est livré **backend-first** ; une page KPI admin (amorçage `app/(admin)/…` + BFF) reste un livrable à confirmer (effort de type shell #14, possiblement > M).
- **Multi-devise.** La mono-devise **XOF** est assumée (parité #37/ADR-0029) ; un `SUM` global serait faux si des devises hétérogènes coexistaient — à revoir seulement si le modèle évolue.
- **Performance.** Les `COUNT(*)` globaux non filtrés balaient toute la table ; acceptable à la volumétrie pilote (§14). À profiler avant montée en charge ; tout index resterait **additif** (hors #44).
- **Suivi.** Un test d'intégration SQL réelle (PostgreSQL 16, base `coiflink-e2e-pg`) pour `SqlPlatformKpiRepository` est recommandé en parité avec #37 (compteurs multi-salons, `clients_total` = `CLIENT` seuls, RDV du mois aux bornes civiles, revenu net avec ajustements, plateforme vide). La route HTTP est couverte en tests API avec fake repo.
