# Détection des écarts de caisse (US-5.4, #36)

> **Issue** : GitHub #36 — US-5.4 « Détection des écarts de caisse » · Labels `feature`, `payments`
> **Priorité** : Should · **Effort** : M · **PRD** : §6 Épic 5 (US-5.4), §8.2 (« Les écarts entre
> prestations réalisées et paiements doivent être visibles »)
> **Dépend de** : #34 (US-5.3 — journal de caisse & correction par ajustement, **livré**)
> **Nature** : tranche verticale de **lecture** (aucune écriture métier) adossée au socle
> encaissement déjà livré (#33/#34/#35).

## Problem Statement

Le PRD identifie les **écarts de caisse** (prestations réalisées mais non encaissées, fraudes,
erreurs de saisie) comme l'un des maux principaux des salons cibles (§1, persona §2.4, §17
« réduction mesurable des erreurs ou fraudes de caisse »). §8.2 pose l'invariant produit : *« Les
écarts entre prestations réalisées et paiements doivent être visibles. »*

Aujourd'hui le dépôt sait :

- enregistrer un paiement cohérent lié à un RDV/prestation (`POST /salons/{salon_id}/payments`,
  US-5.1 #33) ;
- tenir un **journal de caisse** horodaté et corriger un paiement par ajustement (US-5.3 #34) ;
- lister l'**historique filtrable des transactions** (`GET /salons/{salon_id}/payments`, US-5.2 #35).

Mais **rien** ne rapproche les **rendez-vous terminés** (prestations réalisées) des **paiements
enregistrés**. Un RDV passé au statut `COMPLETED` sans qu'aucun paiement ne lui soit rattaché
n'apparaît nulle part comme anomalie : le gérant ne dispose d'aucune vue « ce qui a été fait mais pas
encaissé ». C'est le manque que comble US-5.4.

**Critère d'acceptation (issue #36)** : *« Un RDV terminé sans paiement est signalé comme écart. »*

## Goals

- Exposer une **lecture salon-scopée** qui liste les **rendez-vous `COMPLETED`** d'un salon
  **auxquels aucun paiement n'est rattaché** — chacun étant un « écart de caisse » au sens du critère
  d'acceptation.
- Pour chaque écart, fournir de quoi l'exploiter côté gérant : identifiant du RDV, date, client (nom
  résolu, colonne non sensible uniquement §11.3) et **montant attendu** (somme des `price_at_booking`
  des lignes du RDV — la valeur « qui manque en caisse »).
- Réutiliser les **invariants et conventions déjà en place** : isolation par salon (§11.2),
  permission gérant existante `CASH_JOURNAL_READ` (aucune modification de la matrice RBAC), pagination
  bornée (garde de coût §12.1), fuseau `Africa/Abidjan` pour les bornes de dates, architecture
  hexagonale (ADR-0008), **lecture pure sans journalisation d'audit** (comme le journal #34 et
  l'historique #35).
- (Optionnel, cf. Non-Goals) surfacer ces écarts dans le dashboard gérant, section
  « Encaissements ».

## Non-Goals

- **Aucun paiement, ajustement ou écriture de caisse** n'est créé par cette fonctionnalité : elle
  **signale**, elle ne corrige pas. La correction éventuelle passe par les routes existantes
  (enregistrer le paiement manquant via #33).
- **Détection des paiements partiels / de montant incohérent** : hors périmètre. Le critère #36 porte
  uniquement sur le **RDV terminé *sans* paiement**. De plus, `RecordPayment` (#33) impose déjà
  l'**égalité stricte** montant ↔ prestation à l'enregistrement : un paiement de montant partiel ne
  peut pas être enregistré, donc un RDV « avec paiement » est nécessairement soldé au centime. Un
  éventuel rapprochement de montants plus fin relève d'une évolution ultérieure.
- **Réconciliation automatique / rapprochement bancaire / export comptable** : explicitement V2+
  (PRD §16 « Réconciliation automatique », §21). Ici on **rend visible**, on n'automatise pas la
  résolution.
- **Écarts sur les paiements liés à une prestation seule (`service_id`, sans RDV)** : le walk-in
  encaissé directement n'a pas de RDV `COMPLETED` associé et n'entre donc pas dans la comparaison
  « prestation réalisée (= RDV terminé) vs paiement ». Traité en Open Question.
- **Modification du cycle de statut des RDV** ou de la logique de passage à `COMPLETED` (US-3.4 #25) :
  hors périmètre.
- **Notifications / alertes push** sur écart détecté : hors périmètre (Épic 7).

## Relevant Repository Context

Stack **arrêtée et livrée** (pas de décision de stack ouverte pour ce périmètre) :

- **Backend** : Python + **FastAPI**, architecture **hexagonale** (ADR-0008) — `domain/` et
  `application/` sans dépendance FastAPI/SQLAlchemy ; adapters entrants (`adapters/inbound/`) et
  sortants (`adapters/outbound/persistence/` via SQLAlchemy + Alembic, ADR-0009).
- **Web gérant** : Next.js (ADR-0002), dashboard `/gerant` protégé (BFF, cookie httpOnly).
- **Données** : PostgreSQL (ADR-0004). Mono-devise XOF (§9.6).

Modules directement concernés (déjà en place, à lire) :

- **Statuts RDV** — `backend/coiflink_api/domain/enums.py::AppointmentStatus` :
  `PENDING`/`CONFIRMED`/`CANCELLED`/`COMPLETED`/`NO_SHOW`. Un « RDV terminé » = **`COMPLETED`**
  (prestation réalisée). `NO_SHOW`/`CANCELLED` ne sont **pas** des prestations réalisées → hors
  comparaison.
- **Entité RDV** — `domain/appointment.py::Appointment` (avec ses `BookedService` portant
  `price_at_booking`, prix figé à la réservation). La somme de ces prix est le **montant attendu** ;
  la fonction pure `domain/payment.py::expected_amount_for_prices(prices)` la calcule déjà (réutilisée
  par #33).
- **Paiements** — `domain/payment.py::Payment` ; ORM `persistence/models.py::Payment` :
  `payments.appointment_id` (nullable, FK composite `(salon_id, appointment_id)`), `payments.status`
  (`PENDING`/`VALIDATED`/`CANCELLED`/`ADJUSTED`), index **`ix_payments_appointment_id`** (utile au
  rapprochement) et `ix_payments_salon_id (salon_id, created_at)`.
- **Port RDV** — `application/ports/appointment_repository.py` : déjà `list_for_salon(salon_id,
  date_from, date_to, statuses)` (salon-scopé, filtrable par statut, tous statuts par défaut).
- **Port paiements** — `application/ports/payment_repository.py` : déjà `list_for_salon` /
  `count_for_salon` (transactions filtrées), bornes de pagination `PAYMENTS_LIMIT_DEFAULT=50 / MIN=1 /
  MAX=200`.
- **Router encaissement** — `adapters/inbound/payments.py` : `POST …/payments`,
  `GET …/payments` (transactions), `GET …/cash-journal`, `POST …/payments/{id}/adjustments`. Toutes
  les routes de lecture caisse sont gardées par **`Permission.CASH_JOURNAL_READ`** (détenue **par le
  seul `MANAGER`**, `domain/permissions.py`) + `require_salon_scope`. **Aucune** route caisse n'est
  publique.
- **Filtre temporel** — `domain/transaction.py` : conventions `SALON_TIMEZONE = Africa/Abidjan`
  (UTC+0) et conversion jour civil → bornes UTC inclusives (`_day_start_utc`/`_day_end_utc`),
  réutilisables pour un éventuel filtre de dates sur les écarts.
- **Web** — `web-dashboard/app/(gerant)/gerant/encaissements/page.tsx`,
  `src/adapters/ui/transaction-list.tsx`, `transaction-filters.tsx`, `src/adapters/api/http-payment-gateway.ts`,
  BFF `app/api/salons/[id]/payments/route.ts` : patrons existants d'une surface caisse côté web.

Conventions transverses respectées par le socle et à préserver :

- Isolation §11.2 **imposée en SQL** (filtre `salon_id`), en défense en profondeur de
  `require_salon_scope`.
- Messages d'erreur **neutres**, **aucune PII/montant** dans l'audit ; les surfaces de lecture caisse
  **ne journalisent pas** (§11.4 vise les actions, pas les consultations).
- Montants en `Decimal` (jamais de flottant), quantifiés au centime (`NUMERIC(12,2)`).

## Proposed Implementation

Ajouter une **tranche verticale de lecture** `GET /salons/{salon_id}/cash-discrepancies` qui liste les
RDV `COMPLETED` sans paiement rattaché, paginée et salon-scopée, gardée par la permission gérant
existante `CASH_JOURNAL_READ`. Aucune écriture, aucun audit, aucune modification de la matrice RBAC ni
du schéma.

### 1. Domaine — `domain/discrepancy.py` (nouveau, pur)

- Objet-valeur de lecture `CashDiscrepancy` (dataclass gelée) :
  - `appointment_id: uuid.UUID`
  - `salon_id: uuid.UUID`
  - `appointment_date: datetime.date`
  - `start_time: datetime.time`
  - `client_id: uuid.UUID`
  - `client_name: str | None` (résolu `users.full_name`, colonne non sensible **uniquement** §11.3 ;
    `None` si non résolu)
  - `expected_amount: decimal.Decimal` (somme des `price_at_booking` du RDV, via
    `expected_amount_for_prices`) — le « montant manquant » ; `0.00` possible en théorie.
  - `currency: str` (= `DEFAULT_CURRENCY`, cohérence mono-XOF §9.6).
- Constante `COMPLETED_STATUS = AppointmentStatus.COMPLETED.value` documentant que « réalisé » =
  `COMPLETED` (jamais `NO_SHOW`).
- (Optionnel) réutiliser `domain/transaction.py` pour un filtre de dates ; s'il est ajouté, valider
  `date_from ≤ date_to` et convertir en bornes UTC via les helpers existants (ne pas réinventer le
  fuseau).

### 2. Port — méthode de dépôt de rapprochement

Recommandé : **ajouter une méthode au `PaymentRepository`** (le rapprochement est fondamentalement une
question « ce RDV a-t-il un paiement ? » — la table source est `payments`), par ex. :

```
def list_completed_without_payment(
    salon_id, *, date_from=None, date_to=None, limit, offset
) -> tuple[CashDiscrepancy, ...]: ...

def count_completed_without_payment(
    salon_id, *, date_from=None, date_to=None
) -> int: ...
```

- Alternative acceptable : un **port dédié** `CashDiscrepancyRepository` si l'on préfère ne pas
  élargir `PaymentRepository`. Décider à l'implémentation (voir Open Questions) ; dans les deux cas la
  requête est identique.
- Documenter dans la docstring que le filtre `salon_id` est **inconditionnel** (isolation §11.2) et
  qu'aucune donnée d'un autre salon n'est jamais lue.

### 3. Persistance — implémentation SQL (`persistence/payment_repository.py`)

Requête (SQLAlchemy Core/ORM) : RDV `COMPLETED` du salon **sans paiement rattaché** —

```sql
SELECT a.id, a.appointment_date, a.start_time, a.client_id, u.full_name,
       COALESCE(SUM(s.price_at_booking), 0) AS expected_amount
FROM appointments a
LEFT JOIN users u ON u.id = a.client_id
LEFT JOIN appointment_services s
       ON s.salon_id = a.salon_id AND s.appointment_id = a.id
WHERE a.salon_id = :salon_id
  AND a.status = 'COMPLETED'
  AND NOT EXISTS (
        SELECT 1 FROM payments p
        WHERE p.salon_id = a.salon_id
          AND p.appointment_id = a.id
          AND p.status IN ('VALIDATED', 'ADJUSTED')   -- cf. Open Question
      )
  -- AND a.appointment_date BETWEEN :date_from AND :date_to   -- si filtre de dates
GROUP BY a.id, a.appointment_date, a.start_time, a.client_id, u.full_name
ORDER BY a.appointment_date DESC, a.start_time DESC, a.id DESC
LIMIT :limit OFFSET :offset;
```

- Tri déterministe (`appointment_date DESC, start_time DESC, id DESC`), `limit`/`offset` **en SQL**
  (jamais en mémoire).
- `count_*` applique **exactement** les mêmes clauses `WHERE`/`NOT EXISTS` (total cohérent avec la
  page) — compter les RDV, pas les lignes de prestation.
- La sous-requête `NOT EXISTS` bénéficie de `ix_payments_appointment_id` ; le filtre
  `salon_id`/`status` de `ix_appointments_salon_id`. Évaluer un index partiel
  `(salon_id, appointment_date) WHERE status='COMPLETED'` **seulement** si un profilage le justifie
  (non requis pour le MVP).
- **Choix `NOT EXISTS` vs anti-jointure `LEFT JOIN … IS NULL`** : équivalents ; `NOT EXISTS` est plus
  lisible et robuste au fan-out des lignes de prestation. Le `GROUP BY` sert au calcul du montant
  attendu, pas au dédoublonnage du `NOT EXISTS`.

### 4. Application — `application/discrepancies.py` (nouveau)

- Cas d'usage `ListCashDiscrepancies` (calqué sur `ListTransactions` #35) : dépend **uniquement** du
  port ; `execute(salon_id, *, date_from, date_to, limit, offset) -> (page, total)` ; **lecture pure**
  (aucune écriture, **aucun audit**).

### 5. Adapter entrant — `adapters/inbound/payments.py`

- Nouvelle route `GET /salons/{salon_id}/cash-discrepancies` :
  - Gardes : `require_salon_scope` + `require_permission(Permission.CASH_JOURNAL_READ)` (gérant).
  - Query params optionnels : `date_from`, `date_to` (jour civil `Africa/Abidjan`), `limit`
    (borné `PAYMENTS_LIMIT_MIN..MAX`, défaut `PAYMENTS_LIMIT_DEFAULT`), `offset ≥ 0`.
  - Schémas Pydantic `CashDiscrepancyResponse` (id, date, heure, client_id, client_name,
    expected_amount, currency) et `CashDiscrepancyPageResponse` (items, total, limit, offset).
  - Traduction d'erreur : une éventuelle `InvalidDiscrepancyFilter`/`InvalidTransactionFilter` → `422`
    (message neutre), via le jeu `_VALIDATION_ERRORS` existant. **Pas** de verbe destructif ; route
    **jamais** publique (absente de `PUBLIC_ROUTE_PATHS`).
  - Injection de dépendances via `get_payment_repository` (ou un nouveau provider si port dédié),
    surchargeable en test.

### 6. Web gérant (optionnel — cf. Non-Goals / Open Questions)

Si retenu dans le périmètre de livraison : sous `/gerant/encaissements`, un onglet/section « Écarts »
listant les RDV terminés non encaissés (date, client, montant attendu), avec pagination — en
réutilisant les patrons `transaction-list.tsx` / `http-payment-gateway.ts` et une route BFF
`app/api/salons/[id]/cash-discrepancies/route.ts` (cookie httpOnly → API, deny-by-default). À défaut,
livrer l'API seule et suivre l'UI dans une issue distincte.

## Affected Files / Packages / Modules

**À créer :**

- `backend/coiflink_api/domain/discrepancy.py` — `CashDiscrepancy` + constante(s).
- `backend/coiflink_api/application/discrepancies.py` — `ListCashDiscrepancies`.
- Tests : `backend/tests/test_discrepancies_*.py` (domaine, application, e2e route).
- ADR `docs/adr/00XX-detection-ecarts-de-caisse.md` (voir Documentation Updates).
- (Optionnel web) `web-dashboard/app/api/salons/[id]/cash-discrepancies/route.ts`,
  `web-dashboard/src/adapters/api/http-payment-gateway.ts` (extension), composant liste, page
  `encaissements`.

**À modifier :**

- `backend/coiflink_api/application/ports/payment_repository.py` — nouvelles méthodes de rapprochement
  (ou nouveau port `cash_discrepancy_repository.py`).
- `backend/coiflink_api/adapters/outbound/persistence/payment_repository.py` — implémentation SQL.
- `backend/coiflink_api/adapters/inbound/payments.py` — route + schémas + provider.
- `backend/coiflink_api/domain/errors.py` — **seulement si** un filtre de dates dédié est ajouté
  (`InvalidDiscrepancyFilter`) ; sinon réutiliser `InvalidTransactionFilter`.

**À lire (référence, non modifiés) :** `domain/enums.py`, `domain/appointment.py`, `domain/payment.py`
(`expected_amount_for_prices`), `domain/transaction.py` (helpers fuseau), `domain/permissions.py`,
`application/ports/appointment_repository.py`, `persistence/models.py`.

## API / Interface Changes

**Nouvelle route (backend) :**

- `GET /salons/{salon_id}/cash-discrepancies`
  - **Auth** : Bearer JWT ; **permission** `CASH_JOURNAL_READ` (MANAGER) + portée salon.
  - **Query** : `date_from?`, `date_to?` (`YYYY-MM-DD`, jour civil `Africa/Abidjan`),
    `limit?` (1..200, défaut 50), `offset?` (≥ 0).
  - **200** — `CashDiscrepancyPageResponse` :
    ```json
    {
      "items": [
        {
          "appointment_id": "…",
          "appointment_date": "2026-07-20",
          "start_time": "14:30:00",
          "client_id": "…",
          "client_name": "Awa K.",
          "expected_amount": "5000.00",
          "currency": "XOF"
        }
      ],
      "total": 3, "limit": 50, "offset": 0
    }
    ```
  - **401** jeton absent/invalide · **403** rôle insuffisant ou salon hors périmètre (générique) ·
    **422** filtre de dates incohérent (message neutre).
  - Documentée en OpenAPI (docstring + `responses=`), patron des routes voisines.

**Aucune modification** des routes existantes. **Aucune** nouvelle permission (matrice
`ROLE_PERMISSIONS` inchangée). Route **jamais** publique.

Interface web (si retenue) : une route BFF `GET /api/salons/[id]/cash-discrepancies` (proxy
cookie→API). Décrite dans `web-dashboard/README.md`.

## Data Model / Protocol Changes

**None.** Aucune migration : la détection dérive de tables et colonnes **existantes**
(`appointments.status`, `appointment_services.price_at_booking`, `payments.appointment_id`,
`payments.status`) et des index déjà présents (`ix_payments_appointment_id`,
`ix_appointments_salon_id`). Un index partiel dédié n'est envisagé qu'en cas de besoin de performance
avéré (profilage), et resterait purement additif.

## Security & Privacy Considerations

- **Isolation par salon (§11.2)** : filtre `salon_id` **inconditionnel en SQL** dans les deux
  requêtes (liste + count), en défense en profondeur de `require_salon_scope`. Aucun écart d'un autre
  salon n'est jamais lu ; un `salon_id` hors périmètre → `403` générique (aucun oracle d'existence).
- **RBAC deny-by-default (ADR-0015)** : réutilise `CASH_JOURNAL_READ`, détenue par le **seul**
  `MANAGER` — un coiffeur/client ne peut pas voir les écarts. La matrice n'est **pas** élargie.
- **Non-fuite PII (§11.3)** : seul `users.full_name` (colonne non sensible) est résolu pour
  l'affichage ; **jamais** de téléphone, email, note privée ni autre donnée client. `client_name`
  peut être `null`.
- **Lecture seule / §11.4** : consultation → **aucune** entrée d'audit (aligné sur journal #34 et
  historique #35). Aucune écriture, donc aucune atteinte aux invariants append-only.
- **Logs/redaction** : ne **jamais** logguer montants attendus, noms clients ni identifiants dans les
  logs applicatifs ; messages d'erreur **neutres**.
- **Coût/latence (§12.1)** : pagination bornée (`limit ≤ 200`), tri et bornes **en SQL**, jamais de
  matérialisation complète en mémoire ; `NOT EXISTS` indexé.
- Le dépôt ne documente **aucune** contrainte de résidence/hébergement additionnelle propre à ce
  périmètre au-delà de celles déjà en vigueur (ADR-0011).

## Testing Plan

**Domaine (`domain/discrepancy.py`)** — unitaires purs :

- Construction de `CashDiscrepancy` ; `expected_amount` = somme des `price_at_booking` (réutilise
  `expected_amount_for_prices`, y compris somme vide → `0.00`) ; en `Decimal`, quantifié centime.
- (Si filtre de dates) `date_from > date_to` → erreur neutre ; conversion jour civil → bornes UTC
  inclusives cohérente avec `transaction.py`.

**Application (`ListCashDiscrepancies`)** — avec dépôt en mémoire/factice :

- Retourne `(page, total)` cohérents ; lecture pure ; **aucun** appel d'audit ni d'écriture.
- Pagination : `limit`/`offset` transmis ; `total` sous le même filtre.

**Persistance / intégration (Postgres réel, patron des tests e2e #35/#34)** :

- Un RDV `COMPLETED` **sans** paiement → **présent** dans la liste, `expected_amount` correct.
- Un RDV `COMPLETED` **avec** paiement `VALIDATED` rattaché → **absent**.
- Un RDV `COMPLETED` dont le paiement a été **corrigé** (`ADJUSTED`) → **absent** (cf. décision
  Open Question ; test à figer selon la décision).
- Un RDV `COMPLETED` dont le seul paiement rattaché est `CANCELLED` → **présent** (paiement annulé =
  non encaissé).
- Un RDV `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` → **jamais** signalé (seul `COMPLETED` compte).
- **Isolation §11.2** : un RDV `COMPLETED` non payé d'un **autre** salon → **absent** ; un paiement
  d'un autre salon ne « couvre » jamais un RDV.
- **Pagination** : `total` cohérent avec la page ; tri `appointment_date DESC, start_time DESC`.
- **Filtre de dates** (si implémenté) : bornes `Africa/Abidjan` inclusives ; hors plage → exclu.
- Résolution `client_name` = `full_name` ; RDV sans client résolu → `client_name = null`, **aucune**
  autre PII exposée.

**E2E route (`GET …/cash-discrepancies`)** :

- `401` sans jeton ; `403` pour un rôle sans `CASH_JOURNAL_READ` (coiffeur/client) et pour un salon
  hors périmètre ; `200` pour le gérant du salon.
- `422` sur filtre de dates incohérent (message neutre).
- Absence de verbe destructif ; route non listée comme publique.

**Sécurité (patron des tests de sécurité existants)** : la nouvelle route figure bien parmi les
routes **fermées par défaut** et **non publiques**.

## Documentation Updates

- **ADR** : `docs/adr/00XX-detection-ecarts-de-caisse.md` — décision « détection des écarts par
  rapprochement RDV `COMPLETED` ↔ paiements, en lecture, permission gérant existante, sans schéma ni
  audit » ; référencer PRD §8.2/§6 Épic 5, ADR-0008/0015/0019/0027 ; trancher les Open Questions
  (statuts de paiement comptant comme « payé », périmètre `service_id`). Ajouter l'entrée à
  `docs/adr/README.md`.
- **README backend / racine** : mentionner la route `GET /salons/{salon_id}/cash-discrepancies` dans
  la description du module Encaissement (au même endroit que #33/#34/#35).
- **`web-dashboard/README.md`** : documenter la section « Écarts » et la route BFF **si** l'UI est
  livrée dans ce lot.
- **`specs/`** : ce fichier ; référencer depuis le suivi Épic 5 si un index existe.

## Risks and Open Questions

1. **Quels statuts de paiement « couvrent » un RDV ?** Un paiement `VALIDATED` compte évidemment.
   Un paiement **`ADJUSTED`** (corrigé, mais bien réalisé) devrait, selon toute logique, compter comme
   « encaissé » → le RDV n'est **pas** un écart. Un paiement **`CANCELLED`** ne compte pas → le RDV
   **est** un écart. **Recommandation** : `NOT EXISTS payment WHERE status IN ('VALIDATED',
   'ADJUSTED')`. À **confirmer** et figer dans l'ADR (impacte un test).
2. **RDV `COMPLETED` avec paiement de montant partiel** — ne peut pas exister aujourd'hui
   (`RecordPayment` #33 impose l'égalité stricte), donc « a un paiement » ⇒ « soldé ». Si la règle
   d'égalité était un jour assouplie, US-5.4 devrait évoluer vers un rapprochement de **montants**
   (attendu vs somme encaissée). Noté comme dépendance implicite, hors périmètre actuel.
3. **Paiements liés à une prestation seule (`service_id`, sans `appointment_id`)** — walk-in encaissé
   sans RDV : pas de RDV `COMPLETED` associé, donc hors de la comparaison. Symétriquement, un RDV
   `COMPLETED` pourrait-il être « couvert » par un paiement lié à sa prestation mais non à son
   `appointment_id` ? **Recommandation** : non — le rapprochement se fait **uniquement** sur
   `payments.appointment_id` (source de vérité du lien RDV↔paiement). À confirmer.
4. **Port dédié vs extension de `PaymentRepository`** — décision d'implémentation (cohérence
   hexagonale). Recommandation : extension de `PaymentRepository` (table source = `payments`),
   sauf préférence contraire à la revue.
5. **Périmètre web dans ce lot** — livrer l'API seule (Should, effort M) ou aussi la section
   dashboard ? À confirmer avec le porteur produit ; l'API est la partie qui satisfait strictement le
   critère #36.
6. **Volumétrie / performance** — sur un gros historique de RDV `COMPLETED`, le `NOT EXISTS` +
   `GROUP BY` doit rester indexé ; prévoir un profilage et, si besoin **seulement**, un index partiel
   (purement additif). Pas bloquant au MVP.
7. **Fuseau des dates** — réutiliser strictement `Africa/Abidjan` (UTC+0) de `transaction.py` ; ne pas
   réintroduire de logique de fuseau ailleurs.

## Implementation Checklist

1. **Lire** `domain/enums.py` (`AppointmentStatus`), `domain/appointment.py`
   (`Appointment`/`BookedService`), `domain/payment.py` (`expected_amount_for_prices`),
   `domain/transaction.py` (fuseau), `domain/permissions.py`, `application/ports/payment_repository.py`,
   `persistence/models.py` (`Payment`/`Appointment`/index).
2. **Trancher** les Open Questions 1, 3, 4, 5 (idéalement dans l'ADR avant de coder).
3. Créer `domain/discrepancy.py` : `CashDiscrepancy` (gelée), `COMPLETED_STATUS`, réutilisation de
   `expected_amount_for_prices` ; (si retenu) validation d'un filtre de dates via les helpers fuseau
   existants. **Aucune** dépendance FastAPI/SQLAlchemy.
4. Étendre le **port** (`PaymentRepository` ou nouveau `CashDiscrepancyRepository`) :
   `list_completed_without_payment(...)` + `count_completed_without_payment(...)`, docstrings
   isolation §11.2.
5. Implémenter la **persistance SQL** (`persistence/payment_repository.py`) : requête `NOT EXISTS`
   salon-scopée, `GROUP BY` pour le montant attendu, résolution `client_name = users.full_name`, tri
   déterministe, `limit`/`offset` **en SQL** ; `count_*` avec les **mêmes** clauses.
6. Créer `application/discrepancies.py` : `ListCashDiscrepancies` (lecture pure, `(page, total)`,
   **sans** audit).
7. Ajouter la route `GET /salons/{salon_id}/cash-discrepancies` dans `adapters/inbound/payments.py` :
   gardes `require_salon_scope` + `require_permission(CASH_JOURNAL_READ)`, params bornés, schémas
   Pydantic + doc OpenAPI, traduction `422` sur filtre invalide, provider surchargeable. **Ne pas**
   ajouter de verbe destructif ; **ne pas** rendre la route publique ; **ne pas** modifier
   `ROLE_PERMISSIONS`.
8. **Tests** : domaine (unitaires purs) → application (dépôt factice) → persistance/intégration
   Postgres (cas payé/non payé/ADJUSTED/CANCELLED, statuts non-COMPLETED, isolation, pagination,
   dates, `client_name`) → e2e route (401/403/422/200) → sécurité (route fermée & non publique).
9. **Documentation** : rédiger l'ADR + entrée `docs/adr/README.md` ; mettre à jour le README backend
   (module Encaissement) ; (si UI livrée) `web-dashboard/README.md`.
10. **(Optionnel) Web** : BFF `app/api/salons/[id]/cash-discrepancies/route.ts`, extension du gateway,
    composant liste + section « Écarts » sous `/gerant/encaissements`, tests BFF/UI.
11. **Vérifier** : lint/format (ruff), suite de tests backend verte (dont e2e Postgres), critère #36
    satisfait (« un RDV terminé sans paiement est signalé comme écart »).
