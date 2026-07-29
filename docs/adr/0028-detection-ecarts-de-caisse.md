# ADR-0028 : Détection des écarts de caisse — rapprochement RDV terminés ↔ paiements, en lecture

- **Statut** : Accepté
- **Date** : 2026-07-29
- **Décideurs** : équipe CoifLink
- **Issue** : #36 (US-5.4 — Détection des écarts de caisse, gérant)
- **Référence PRD** : §6 Épic 5 (US-5.4), §8.2 (« Les écarts entre prestations réalisées et paiements
  doivent être visibles »), §1/§2.4/§17 (réduction mesurable des erreurs ou fraudes de caisse), §9.4
  (statuts RDV), §9.6 (tables `payments`/`appointment_services`, mono-devise XOF), §11.2 (isolation par
  salon), §11.3 (non-fuite PII), §11.4 (journalisation des actions, pas des consultations), §12.1
  (garde de coût)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, portée salon),
  [ADR-0019](./0019-journalisation-audit-et-prestations.md) (audit §11.4, entrées neutres) et le
  **socle encaissement livré** ([ADR-0027](./0027-encaissement-coherence-montant.md) #33, journal &
  correction #34, historique filtrable #35)

## Contexte et problème

Le PRD identifie les **écarts de caisse** (prestations réalisées mais non encaissées) comme l'un des
maux principaux des salons cibles, et pose l'invariant produit (§8.2) : *« Les écarts entre prestations
réalisées et paiements doivent être visibles. »* Le critère d'acceptation de #36 est : **« Un RDV
terminé sans paiement est signalé comme écart. »**

Le dépôt savait déjà enregistrer un paiement cohérent lié à un RDV (#33), tenir un journal de caisse et
corriger par ajustement (#34), et lister l'historique filtrable des transactions (#35). Mais **rien**
ne rapprochait les **rendez-vous terminés** (`COMPLETED`) des **paiements enregistrés** : un RDV réalisé
sans paiement rattaché n'apparaissait nulle part comme anomalie.

## Décision

Ajouter une **tranche verticale de lecture** `GET /salons/{salon_id}/cash-discrepancies` qui liste les
RDV `COMPLETED` d'un salon **sans paiement rattaché**, paginée, salon-scopée, gardée par la permission
gérant **existante** `CASH_JOURNAL_READ`. Aucune écriture, aucun audit, aucune migration, aucune
modification de la matrice RBAC.

### 1. « Réalisé » = `COMPLETED`, et rien d'autre

Un écart ne concerne que les prestations **réalisées** : seul le statut `COMPLETED` compte. Un
`NO_SHOW`, `CANCELLED`, `PENDING` ou `CONFIRMED` n'est jamais signalé (rien n'a été réalisé, ou le RDV
est encore actif). La constante `domain/discrepancy.py::COMPLETED_STATUS` documente ce choix.

### 2. « Payé » = un paiement `VALIDATED` **ou** `ADJUSTED` rattaché (Open Question tranchée)

Le rapprochement est un `NOT EXISTS` : un RDV est un écart s'il **n'existe aucun** paiement
`payments.appointment_id = a.id` de statut `VALIDATED` **ou** `ADJUSTED`. Justification :

- un paiement **`VALIDATED`** couvre évidemment le RDV ;
- un paiement **`ADJUSTED`** (encaissement bien réalisé, puis corrigé par une ligne d'ajustement, #34)
  couvre lui aussi le RDV — le sortir ferait ré-apparaître à tort comme « écart » un RDV pourtant
  encaissé ;
- un paiement **`CANCELLED`** (ou `PENDING`) ne couvre **rien** : un RDV dont le seul paiement rattaché
  est annulé **est** un écart.

L'ensemble `PAID_PAYMENT_STATUSES = (VALIDATED, ADJUSTED)` matérialise cette règle.

### 3. Rapprochement **uniquement** sur `payments.appointment_id` (Open Question tranchée)

Le lien RDV↔paiement fait foi **exclusivement** via `payments.appointment_id`. Un walk-in encaissé sur
une prestation seule (`service_id`, sans `appointment_id`) n'a pas de RDV `COMPLETED` associé et n'entre
donc pas dans la comparaison ; symétriquement, un tel paiement ne « couvre » jamais un RDV terminé. Ce
choix reste cohérent avec l'égalité stricte montant↔prestation imposée à l'enregistrement (ADR-0027) :
« a un paiement » ⇒ « soldé au centime », donc la détection se limite au **RDV terminé *sans* paiement**
(pas de rapprochement de montants partiels au MVP).

### 4. Montant attendu = somme des `price_at_booking`, calculée **en SQL**

Chaque écart porte un **montant attendu** — la valeur « qui manque en caisse » — égal à la somme des
`price_at_booking` (prix figés à la réservation, même source de vérité que #29/#30/#31/#33) des lignes
`appointment_services` du RDV, via un `LEFT JOIN` + `GROUP BY`. La somme est faite **en SQL** puis
quantifiée au centime (`Decimal`, `NUMERIC(12,2)`, jamais un flottant), cohérente avec la fonction pure
`domain/payment.py::expected_amount_for_prices`.

### 5. Extension de `PaymentRepository` plutôt qu'un port dédié (Open Question tranchée)

Le rapprochement répond à la question « ce RDV a-t-il un paiement ? » — la table source du prédicat est
`payments`. On **étend** donc `PaymentRepository` (`list_completed_without_payment` /
`count_completed_without_payment`) plutôt que d'introduire un port dédié, cohérent avec le placement de
`list_for_salon`/`count_for_salon` (#35). Le `count_*` applique **exactement** les mêmes clauses
`WHERE`/`NOT EXISTS` que la liste (comptant les **RDV**, jamais les lignes de prestation) pour un total
cohérent avec la page.

### 6. Périmètre livré : **API seule** (Open Question tranchée)

Le critère #36 est strictement satisfait par l'API. La section web « Écarts » sous `/gerant/encaissements`
est **différée** à une issue distincte (Should, effort M) ; les patrons `transaction-list.tsx` /
`http-payment-gateway.ts` et une route BFF `cash-discrepancies` la porteront le moment venu.

### 7. Filtre de dates sur `appointment_date`, sans conversion de fuseau

Les bornes optionnelles `date_from`/`date_to` sont des **jours civils** `Africa/Abidjan` (UTC+0)
comparés **directement** à `appointments.appointment_date` (colonne `Date`, déjà exprimée en jour
civil). Contrairement à l'historique #35 — qui compare `created_at` (timestamp) et convertit donc en
bornes UTC — **aucune** conversion de fuseau n'est requise ici. Une plage incohérente
(`date_from > date_to`) lève `InvalidDiscrepancyFilter` → **`422`**, message neutre.

### 8. Lecture pure : ni écriture, ni audit, deny-by-default

Comme le journal #34 et l'historique #35, la consultation **ne journalise aucune action** (§11.4 vise
les actions, pas les consultations). Le filtre `salon_id` est **inconditionnel en SQL** (défense en
profondeur de `require_salon_scope`, §11.2) — dans la liste **et** dans la sous-requête `NOT EXISTS` :
jamais un RDV d'un autre salon, et un paiement d'un autre salon ne couvre jamais un RDV. La route est
gardée par `CASH_JOURNAL_READ` (détenue par le **seul** `MANAGER`), n'est **jamais** publique et
n'expose que `users.full_name` (colonne non sensible §11.3, `null` si non résolu) — jamais de
téléphone, email ni autre PII.

## Conséquences

- **Positif.** L'invariant §8.2 est désormais **matérialisé** : le gérant voit « ce qui a été fait mais
  pas encaissé ». La détection dérive de tables/colonnes/index **existants** (`appointments.status`,
  `appointment_services.price_at_booking`, `payments.appointment_id`/`status`,
  `ix_payments_appointment_id`, `ix_appointments_salon_id`) — **aucune migration**. La règle est pure,
  testée et salon-scopée en profondeur ; tri/pagination/bornes en SQL (garde de coût §12.1).
- **Compromis.** La détection porte **uniquement** sur le RDV terminé *sans* paiement (pas de
  rapprochement de montants partiels — impossible aujourd'hui du fait de l'égalité stricte #33). Un
  rapprochement de montants plus fin, la réconciliation automatique et l'export comptable restent V2+
  (PRD §16/§21). L'UI gérant est différée.
- **Performance.** Le `NOT EXISTS` s'appuie sur `ix_payments_appointment_id` et le filtre
  `salon_id`/`status` sur `ix_appointments_salon_id`. Un index partiel
  `(salon_id, appointment_date) WHERE status = 'COMPLETED'` n'est envisagé qu'en cas de besoin avéré
  (profilage) et resterait purement additif — non requis au MVP.
