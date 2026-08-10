# ADR-0040 : Impression du reçu (gérant) — numérotation séquentielle par salon, projection étendue, aperçu navigateur

- **Statut** : Accepté
- **Date** : 2026-08-10
- **Décideurs** : équipe CoifLink
- **Issue** : ad hoc (aucune issue GitHub créée en amont, comme #150–#153) — étend #38 (US-5.5)
- **Référence PRD** : §5.3 (parcours encaissement), §8.2 (paiements), §11.2 (isolation/appartenance),
  §11.3 (non-fuite PII)
- **S'appuie sur** : [ADR-0027](./0027-encaissement-coherence-montant.md) (#33, encaissement),
  [ADR-0028](./0028-detection-ecarts-de-caisse.md) (#36, écarts de caisse),
  [ADR-0030](./0030-recu-numerique-remise-differee.md) (#38, reçu numérique client) — **étendu** ici,
  pas remplacé

## Contexte et problème

Le gérant a besoin d'imprimer, au moment de l'encaissement, un reçu qu'il remet **physiquement** à la
cliente (mise en page adaptée à une imprimante thermique, aperçu avant impression). ADR-0030 (#38) a
déjà livré une projection en lecture `Receipt`/`ReceiptLine`, mais strictement **côté client**
(`GET /me/receipts*`, permission `PAYMENT_READ_OWN`) — le gérant n'y a **aucun** accès, et son propre
Non-Goal §« Reçu côté gérant / réimpression comptoir » renvoyait explicitement cette demande à une
« évolution ultérieure côté gérant ». C'est cette évolution.

Deux besoins nouveaux que #38 ne couvrait pas :

1. **Un numéro de reçu présentable.** ADR-0030 §Open Question 3 recommandait délibérément
   `payment.id` (l'UUID) comme identifiant, pour **éviter tout compteur** nécessitant une écriture. Un
   ticket physique remis en main a besoin d'un numéro court (`REC-000042`), pas d'un UUID.
2. **L'identité de la cliente sur le ticket.** Le reçu client ne l'affiche pas (elle se connaît déjà) ;
   le gérant, lui, doit pouvoir l'identifier — y compris pour un **paiement comptoir sans compte
   client** (`client_id` nul), cas que la lecture d'appartenance de #38 exclut structurellement.

## Décision

### 1. `receipt_number` devient un compteur séquentiel **persisté**, par salon

Révision assumée de ADR-0030 §3 : ajout de `payments.receipt_number` (migration `0012`, `INTEGER NOT
NULL`, `UNIQUE (salon_id, receipt_number)`), alloué **atomiquement** à la création du paiement
(`SqlPaymentRepository.create`) via un verrou consultatif **transactionnel** par salon
(`pg_advisory_xact_lock(hashtext(salon_id))` puis `MAX(receipt_number) + 1`) — sérialise les créations
concurrentes du même salon sans nouvelle table de compteur ni nouvelle frontière de transaction (le
verrou est relâché au commit/rollback déjà piloté par `get_session`). Paiements existants backfillés
par `ROW_NUMBER()` ordonné `created_at, id`. `format_receipt_number(receipt_number: int)` (désormais un
`int`, plus un UUID) formate en `REC-000042`.

Ce numéro reste **hors** du dataclass domaine `Payment`/`PaymentToCreate` et du port
`PaymentRepository` — seule la ligne ORM le porte, lu uniquement via `ReceiptRepository`. Choix
délibéré : éviter de faire onduler ~soixante-dix sites de test qui construisent `Payment(...)` pour un
champ que seul le reçu a besoin de connaître.

### 2. La **même** projection `Receipt` sert les deux lectures, via deux méthodes de dépôt distinctes

`ReceiptRepository` gagne `get_receipt_for_salon(salon_id, payment_id)` (portée **salon**, à côté de
`get_receipt_for_client` — portée **client**, inchangée). `Receipt` gagne `client_name`/`client_phone`
(`str | None`), renseignés **uniquement** par la lecture gérante (résolution `client_id →
users.full_name/phone`, `outerjoin` — jamais un `join`, pour ne pas exclure les paiements comptoir).
La lecture client ne les renseigne jamais : un client n'a pas besoin qu'on lui rappelle sa propre
identité. Pas de duplication de la logique d'assemblage des lignes (`_lines_for_payment`) : les deux
méthodes du dépôt SQL la réutilisent telle quelle.

### 3. Nouvel endpoint gérant, **aucune nouvelle permission**

`GET /salons/{salon_id}/payments/{payment_id}/receipt`, gardé par `require_salon_scope` +
`require_permission(Permission.CASH_JOURNAL_READ)` — la **même** permission que l'historique des
transactions (#35) et le journal de caisse (#34). Un reçu imprimable est une lecture financière du même
niveau de confiance ; créer une permission dédiée n'aurait ajouté aucune isolation supplémentaire.
`404` neutre (indiscernable) si le paiement n'existe pas ou appartient à un autre salon — même patron
non-oracle que `PaymentRepository.get`/`AdjustPayment`.

### 4. Paiements `ADJUSTED` : comportement inchangé, pas de nettage

Comme pour `/me/receipts` (ADR-0030), le reçu gérant reflète le paiement **tel qu'enregistré**
(`amount` d'origine + `status = ADJUSTED`) — la correction (`cash_journal`, #34) reste un registre
séparé, jamais fusionné dans la projection de lecture du reçu.

### 5. Impression : aperçu navigateur, succès *best-effort*

Côté web-dashboard, l'impression passe par `window.print()` + CSS `@media print` scopée (masque tout
sauf le bloc du reçu, largeur 80mm par défaut) — aucune génération PDF serveur, aucune dépendance
d'impression native. L'état « impression réussie » se déduit de l'évènement navigateur `afterprint`
(dialogue d'impression fermé) : c'est un signal **best-effort**, pas une confirmation matérielle — le
navigateur ne peut pas savoir si le ticket est réellement sorti de l'imprimante thermique. Documenté
comme limite assumée plutôt que dissimulé derrière un faux état « succès ».

### 6. Côté mobile client : consultation + partage, pas d'impression thermique

Le client n'a pas d'imprimante thermique sur son téléphone. La mobile app expose un écran « Mes reçus »
(liste + détail) consommant les endpoints **déjà livrés** par #38 (`GET /me/receipts*`, aucun
changement backend requis pour cette tranche) et un bouton « Partager » via le partage natif du
téléphone (texte formaté, nouveau paquet `share_plus`) — pas de SDK d'impression Bluetooth, hors
périmètre.

## Conséquences

- **Positif.** Le gérant dispose d'un reçu imprimable cohérent avec le reçu numérique client existant
  (même numéro `REC-…` visible des deux côtés) ; aucune nouvelle permission ni élargissement de la
  matrice RBAC ; le chemin d'écriture du paiement (#33) reste atomique, une seule ligne ajoutée à sa
  transaction déjà existante.
- **Compromis assumé.** `receipt_number` n'est **pas** gapless au sens strict (un paiement qui échoue
  après verrouillage mais avant commit ne consomme pas de numéro, donc pas de trou dans ce cas précis —
  mais un futur retrait de fonctionnalité ou une correction manuelle en base pourrait en laisser un) ;
  c'est acceptable pour un numéro de présentation, pas pour une exigence comptable stricte de
  séquence sans trou.
- **Compromis assumé.** L'état « impression réussie » côté web est un proxy (`afterprint`), pas une
  preuve d'impression physique — toute vérification allant plus loin demanderait une intégration avec
  le pilote de l'imprimante (hors périmètre navigateur).
- **Suivi.** Cette tranche referme le Non-Goal « reçu côté gérant » d'ADR-0030 et son Open Question §3
  (numérotation) — ADR-0030 n'est pas réécrite (une décision ne se réécrit jamais, ADR-0000), cette
  ADR-0040 la **complète**.
