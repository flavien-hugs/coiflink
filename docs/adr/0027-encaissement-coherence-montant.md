# ADR-0027 : Encaissement — cohérence du montant avec la prestation liée & enregistrement d'un paiement

- **Statut** : Accepté
- **Date** : 2026-07-28
- **Décideurs** : équipe CoifLink
- **Issue** : #33 (US-5.1 — Enregistrement d'un paiement, gérant)
- **Référence PRD** : §6 Épic 5 (US-5.1), §5.3 (« Parcours encaissement » — le système vérifie que le
  montant correspond à la prestation ; transaction ajoutée au journal de caisse ; opération
  journalisée), §8.2 (« Encaissement » — paiement lié à une prestation ou un rendez-vous ; montant +
  mode + utilisateur responsable ; cohérence du montant), §9.6 (tables `payments`/`cash_journal`,
  mono-devise XOF), §11.2 (isolation par salon), §11.3 (non-fuite PII), §11.4 (journalisation)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, portée salon),
  [ADR-0019](./0019-journalisation-audit-et-prestations.md) (audit §11.4, entrées neutres) et le
  **socle d'enregistrement livré avec #34** (journal de caisse, correction par ajustement)

## Contexte et problème

Le PRD (§6 Épic 5, US-5.1) demande : *« en tant que gérant, je veux enregistrer un paiement pour
encaisser une prestation »*, avec pour critère d'acceptation **« paiement enregistré et lié au
RDV/prestation ; montant cohérent ; opération journalisée (§11.4) »**.

Particularité du dépôt : la **tranche verticale d'enregistrement d'un paiement était déjà livrée**
comme **socle de #34** (US-5.3 — journal de caisse), qui dépendait de #33 mais a été implémenté en
premier. Étaient donc déjà présents et testés : la route `POST /salons/{salon_id}/payments`
(garde `PAYMENT_RECORD` + portée), le cas d'usage `RecordPayment` (paiement `VALIDATED` → ligne
`PAYMENT` au journal → audit `PAYMENT_RECORDED` neutre, même unité de travail), le domaine
`domain/payment.py` (bornes du montant, mode, devise mono-XOF, référence prestation **ou** RDV) et le
dépôt SQL.

Il restait **deux manques** explicitement au critère d'acceptation :

1. **La cohérence du montant n'était pas vérifiée.** `validate_amount` ne contrôlait que les *bornes*
   (`>= 0`, ≤ max, ≤ 2 décimales) ; aucune comparaison entre le montant saisi et le **prix de la
   prestation/RDV liée** — alors que §5.3/§8.2 l'imposent.
2. **Aucune interface gérant pour encaisser.** La section « Encaissements » du dashboard était en
   `coming-soon`.

## Décision

### 1. Vérifier la cohérence du montant dans `RecordPayment`, avant toute écriture

`RecordPayment` injecte désormais deux **ports de lecture** (`AppointmentRepository`,
`ServiceRepository`) et résout un **« montant attendu »** à partir de la référence du paiement, puis
refuse tout écart **avant** la moindre écriture :

- paiement lié à un **RDV** (`appointment_id`) → attendu = **somme des `price_at_booking`** des lignes
  `appointment_services` du RDV ;
- paiement lié à une **prestation seule** (`service_id`, sans RDV) → attendu = **`Service.price`** de la
  prestation **active** du salon ;
- si les **deux** sont fournis, la cohérence porte sur le **RDV** (référence la plus spécifique) et le
  `service_id` doit faire partie des prestations du RDV, sinon la référence est rejetée.

La comparaison est une **fonction pure** du domaine (`validate_amount_matches`), en `Decimal` quantifié
au centime (`0.01`, miroir de `NUMERIC(12,2)`) — **jamais** un flottant.

### 2. Règle de tolérance : égalité stricte au centime (MVP)

Le MVP applique l'**égalité stricte** (`montant == attendu`). Autoriser un **acompte / paiement
partiel** (`0 < montant <= attendu`) est une évolution possible mais **délibérément différée** : elle
impacte aussi la détection des écarts de caisse (#36) et le reçu (#38), et n'est pas requise par « le
montant correspond à la prestation ».

### 3. Source du montant attendu : le prix **figé** pour un RDV, le prix **courant** pour une prestation seule

Pour un **RDV**, `price_at_booking` (prix figé à la réservation) est la source de vérité — un
changement de tarif ultérieur ne doit pas invalider un encaissement légitime, et cet historique figé
est déjà celui qu'utilisent #29/#30/#31. Pour une **prestation seule** (sans RDV), il n'existe pas de
prix figé : le prix **courant** `Service.price` de la prestation **active** s'applique (`find_by_id`
filtre déjà l'actif). Le montant attendu vient donc **toujours** d'une donnée **salon-scopée**, jamais
d'un champ soumis par le client de l'API.

### 4. Code HTTP d'une référence introuvable : `422`, sans oracle

Une référence (`appointment_id`/`service_id`) **inexistante** ou appartenant à un **autre salon** est
**indiscernable** (aucun oracle d'existence inter-salons, §11.2) et produit une erreur métier neutre
`PaymentReferenceNotFound` traduite en **`422`** (donnée de requête invalide, cohérent avec les autres
refus de validation du paiement) — plutôt qu'un `404` qui suggérerait une distinction existence/portée.

### 5. Aucune régression sur les invariants livrés

`recorded_by` vient **toujours** du `Principal` (non-répudiation §8.2), `status` imposé `VALIDATED`,
**une** ligne `PAYMENT` par paiement, audit `PAYMENT_RECORDED` **neutre** (`metadata = {}` : ni montant,
ni mode, ni identité client), atomicité `flush()` sans `commit()`. Un paiement incohérent est rejeté
**avant** toute écriture : **aucune** trace `payments`/`cash_journal`/`audit_logs`. Les messages `4xx`
restent **métier et neutres** — ils ne reprennent **jamais** le montant saisi ni le prix attendu (§11.3).
Aucune migration : les tables/contraintes/enums existent depuis `0001` ; la matrice de permissions
§4.1 est inchangée (`PAYMENT_RECORD` reste détenue par le **seul** `MANAGER`).

### 6. Écran gérant « Enregistrer un paiement »

La section `encaissements` passe de `coming-soon` à `available`. Le parcours web réutilise le patron
fiche client (#28/#32) : domaine/port/gateway HTTP à **union discriminée** (`amount-mismatch` /
`reference-not-found` / `invalid` / `forbidden` / `unauthenticated` / `unavailable`), **BFF** lisant le
cookie `httpOnly` **côté serveur** (invariant #14), formulaire client-side à **montant pré-rempli** au
prix de la prestation (guidage de la cohérence, la source de vérité restant le backend). Le jeton ne
transite jamais vers le navigateur et n'est jamais journalisé.

## Conséquences

- **Positif.** Le montant est désormais **borné au prix réel** de la prestation/RDV : on ne peut plus
  enregistrer un montant décorrélé. La règle est **pure et testée** (domaine), l'isolation §11.2 est
  garantie **en profondeur** (portée HTTP + filtres `salon_id` des dépôts de lecture). Aucun couplage
  du domaine à l'ORM (résolution par ports). Le socle #34 (journal, correction) est **réutilisé**, pas
  réécrit.
- **Compromis.** L'égalité stricte interdit acompte/paiement partiel au MVP — assumé et documenté ; à
  rouvrir avec #36/#38 si le besoin se confirme. L'encaissement web se concentre sur la **prestation**
  (le backend supporte aussi le RDV) ; une sélection de RDV terminé pourra enrichir l'écran
  ultérieurement.
- **Frontière #33 ↔ #34.** Le backend #34 (journal de caisse, correction par ajustement) est livré ; son
  web ne l'est pas encore. #33 crée la page `encaissements` avec l'enregistrement ; la vue journal +
  correction (web) revient à #34. #33 ne duplique pas la logique journal/correction déjà présente.
