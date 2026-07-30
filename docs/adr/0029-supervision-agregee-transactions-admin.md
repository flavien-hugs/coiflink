# ADR-0029 : Supervision agrégée des transactions (admin) — lecture plateforme gardée par `STATS_READ_PLATFORM`, net via `cash_journal`, non-PII

- **Statut** : Accepté
- **Date** : 2026-07-30
- **Décideurs** : équipe CoifLink
- **Issue** : #37 (US-5.6 — Supervision agrégée des transactions, admin)
- **Référence PRD** : §6 Épic 5 (US-5.6), §4.1 (matrice des permissions — `STATS_READ_PLATFORM` réservée à l'`ADMIN`), §11.2 (isolation par salon), §11.3 (non-fuite PII de paiement), §11.4 (journalisation des actions, pas des consultations), §12.1 (garde de coût)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, isolation par salon) et le
  **socle encaissement livré** ([ADR-0027](./0027-encaissement-coherence-montant.md) #33,
  [ADR-0028](./0028-detection-ecarts-de-caisse.md) #36, journal & correction #34, historique filtrable #35)

## Contexte et problème

Toutes les lectures financières livrées avant #37 (journal de caisse #34, historique filtrable #35, écarts #36) sont **salon-scopées** : gardées par `CASH_JOURNAL_READ` (détenue uniquement par le `MANAGER`) et montées sous `/salons/{salon_id}/…`, où `require_salon_scope` bloque tout accès inter-salons (§11.2). L'`ADMIN` — qui n'a ni `CASH_JOURNAL_READ` ni de salon dans sa portée — ne peut consulter aucune de ces surfaces.

Le PRD (§4.1/§6 Épic 5) exige que l'Admin CoifLink puisse **superviser l'activité d'encaissement de tous les salons** depuis une **vue agrégée** : combien de transactions, quel montant net encaissé, par salon — *sans* exposer les détails sensibles (identité du client, référence, auteur de la saisie, lignes individuelles). Le critère d'acceptation est :

> L'admin voit des agrégats par salon **sans PII de paiement superflue** (§11.2/§11.3).

La permission `STATS_READ_PLATFORM` existait déjà dans la matrice `ROLE_PERMISSIONS` (#12, ADR-0015), réservée à l'`ADMIN`, mais n'était consommée par aucune route. #37 en est le **premier consommateur**.

## Décision

Ajouter une **tranche verticale de lecture plateforme** `GET /admin/transactions/summary` qui renvoie, **par salon**, des agrégats de transactions (paiements, corrections, montant net, devise, identité métier) paginés et filtrables par plage de dates. Aucune écriture, aucun audit, aucune migration, aucune modification de la matrice RBAC.

### 1. Garde : `require_permission(STATS_READ_PLATFORM)` seule (pas de `require_salon_scope`)

La route est gardée par `require_permission(STATS_READ_PLATFORM)` **uniquement**. L'`ADMIN` est le **seul** rôle porteur (`ROLE_PERMISSIONS` fermée, §4.1 non modifiée) → `401` sans jeton, `403` générique pour tout autre rôle.

`require_salon_scope` **n'est pas** utilisé : la route n'est pas sous `/salons/{salon_id}`, et l'admin n'a pas de salon dans sa portée « propriété ». `AccessPolicy.scope_of` lui accorde déjà `SalonScope.platform()` (ADR-0015), légitimant la lecture inter-salons. Ce n'est **pas** un contournement de §11.2 — c'est la supervision plateforme prévue par le PRD.

### 2. Source de vérité : `cash_journal` (net) plutôt que `payments` (brut)

`total_amount` = **somme signée** des lignes `cash_journal.amount` (`PAYMENT` positif, `ADJUSTMENT` signé) — le **montant net** encaissé. Un paiement corrigé (#34) fait **baisser** `total_amount` et **incrémente** `adjustment_count`, fidèlement à la réalité de caisse.

Alternative rejetée : sommer `payments.amount` (brut). Un paiement corrigé serait ignoré, donnant un net faux. La somme du journal est la seule source de vérité fidèle — d'où la dépendance explicite `#37 → #34`.

`payment_count` / `adjustment_count` proviennent des mêmes lignes journal (`COUNT(*) FILTER`), garantissant la cohérence avec la caisse.

### 3. Agrégation sur `cash_journal GROUP BY salon` — salons sans activité exclus

L'agrégation groupe sur `cash_journal` (jointure `salons` pour l'identité métier). **Seuls les salons ayant au moins une ligne sous le filtre** apparaissent dans la liste — les salons sans activité sont absents. Cette approche est plus simple (`INNER JOIN`, `GROUP BY`) et évite le bruit d'une liste de salons à zéros.

L'index existant `ix_cash_journal_salon_id (salon_id, created_at)` couvre le groupement et le filtre de dates — **aucun nouvel index requis**.

### 4. Non-PII (§11.3) — forme de la réponse figée par des tests

La réponse ne porte **que** des compteurs, une somme et l'**identité métier** du salon (`salon_id`, `salon_name`) — jamais : `client_id`, nom de client, `reference`, `recorded_by`/`performed_by`, `owner_id`, ni ligne de paiement individuelle. Les schémas Pydantic listent les champs **explicitement** (pas de fuite par `orm_mode`/`extra`) ; un test d'API **fige** la forme (échec si un champ interdit apparaît).

`salon_name` n'est **pas** une PII de paiement : l'admin détient déjà `SALON_READ_ANY` ; l'identité du salon est l'unité d'agrégation indispensable.

### 5. Port dédié `PlatformTransactionRepository`

Les ports existants (`PaymentRepository`, `CashJournalRepository`) sont **inconditionnellement salon-scopés** (§11.2 en défense). Un agrégat qui groupe **tous** les salons leur est structurellement étranger. Un port dédié (`summary_by_salon`, `count_salons`) préserve l'isolation et l'intention de chaque port.

### 6. Helpers de fuseau extraits dans `domain/time_window.py`

La conversion « jour civil `Africa/Abidjan` → bornes UTC inclusives » était dans `domain/transaction.py`. Plutôt que de la dupliquer, elle est **extraite** dans `domain/time_window.py` (`SALON_TIMEZONE`, `day_start_utc`, `day_end_utc`) et réimportée dans `domain/transaction.py` (imports existants intacts). Réutilisée telle quelle par `validate_platform_summary_filter`.

### 7. Garde de coût et pagination en SQL

Toute l'agrégation (groupement, filtre, tri, `limit`/`offset`) est **en SQL** — jamais en mémoire. Bornes de pagination `1..200` (parité #34/#35). Tri déterministe `salon_name ASC, salon_id ASC`.

### 8. Lecture pure : aucune écriture, aucun audit, deny-by-default

Comme les lectures caisse #34/#35/#36, la consultation **ne journalise aucune action** (§11.4 vise les actions, pas les consultations). La route porte une garde de `Principal` et **n'est pas** publique-listée (`PUBLIC_ROUTE_PATHS` inchangée) — l'invariant `unprotected_routes(app) == []` la couvre automatiquement.

Devise : **XOF** (mono-devise MVP ; `cash_journal` ne porte pas de colonne `currency`). `total_amount` est sérialisé en **chaîne décimale** (`Decimal`/`NUMERIC(12,2)`, jamais un flottant), en parité avec #34/#35.

## Conséquences

- **Positif.** L'admin peut désormais superviser l'encaissement de tous les salons sans accéder aux données de paiement individuelles (§11.3). La permission `STATS_READ_PLATFORM` est pour la première fois consommée, validant le design RBAC d'ADR-0015. La tranche est hexagonale, pure et testée ; aucune migration, aucun nouvel index.
- **Compromis.** Seuls les salons **avec activité** sont listés (choix simplifiant). Un drill-down vers le détail des transactions d'un salon depuis la supervision admin n'est **pas** fourni (hors périmètre US-5.6 ; surfaces salon-scopées #34/#35 restent exclusives au `MANAGER`). L'UI web admin (`/admin`) est différée — la zone n'existe pas encore dans le `web-dashboard`.
- **Multi-devise.** La mono-devise XOF est assumée au MVP. Si des devises hétérogènes coexistaient, un `SUM` global serait faux ; le groupement `(salon, currency)` est à prévoir avant tout support multi-devise.
- **Performance.** L'index `ix_cash_journal_salon_id (salon_id, created_at)` couvre le groupement/filtre. Un index supplémentaire ne serait envisagé qu'en cas de besoin avéré (profilage) et resterait purement additif.
- **Suivi.** Un test d'intégration SQL réelle (PostgreSQL 16, `DATABASE_URL`) pour `SqlPlatformTransactionRepository` est recommandé en parité avec #35 (net avec ajustements, bornes de dates inclusives `Africa/Abidjan`, pagination déterministe, salon sans activité). La route HTTP est entièrement couverte en tests API avec fake repo.
