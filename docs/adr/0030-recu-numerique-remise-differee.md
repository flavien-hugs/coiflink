# ADR-0030 : Reçu numérique de paiement (client) — projection en lecture gardée par `PAYMENT_READ_OWN`, remise proactive différée M5

- **Statut** : Accepté
- **Date** : 2026-07-30
- **Décideurs** : équipe CoifLink
- **Issue** : #38 (US-5.5 — Reçu numérique de paiement, client)
- **Référence PRD** : §6 Épic 5 (US-5.5), §5.3 (parcours encaissement), §8.4 (notifications), §4.1 (matrice des permissions), §11.2 (isolation / appartenance), §11.3 (non-fuite PII), §12.1 (garde de coût)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default),
  [ADR-0006](./0006-notifications-fcm-sms.md) (notifications FCM/SMS différées M5) et le
  **socle encaissement livré** ([ADR-0027](./0027-encaissement-coherence-montant.md) #33, journal & correction #34, historique filtrable #35)

## Contexte et problème

Le PRD (§6 Épic 5, US-5.5) pose : « en tant que client, je veux recevoir un reçu numérique après paiement, pour garder une preuve de la transaction ». Le critère d'acceptation de #38 est unique : **« Un reçu est généré/envoyé après paiement. »**

Deux constats structurent la décision :

1. **Aucune notion de reçu n'existait.** L'enregistrement d'un paiement est livré (#33) : `POST /salons/{salon_id}/payments` crée un `Payment` `VALIDATED` portant un `client_id` **optionnel** — le seul lien entre un paiement et le client destinataire d'un reçu.
2. **La remise réelle (push FCM / SMS) est différée en M5** (Épic 7, ADR-0006). Le seul adapter de notification livré est un **stub no-op** ; aucun worker de remise n'existe. Rien ne peut être « poussé » à un appareil aujourd'hui.

Le critère est « **généré/envoyé** » (alternatives). Comme la remise dépend d'une infra non construite, l'interprétation MVP fidèle et livrable est : **générer un reçu récupérable par le client**, sans inventer de canal de remise.

## Décision

Ajouter une **tranche verticale de lecture d'appartenance** exposant, pour le **client authentifié**, ses reçus — projection en lecture seule dérivée du paiement déjà persisté. Aucune écriture, aucun audit, aucune migration, aucune remise.

### 1. Le reçu est une **projection en lecture**, pas une nouvelle entité

`Receipt`/`ReceiptLine` (`domain/receipt.py`) sont des `dataclass` **gelées** assemblées à la lecture depuis des sources **déjà persistées** : montant/devise/mode/statut/référence/horodatage = champs du `payment` (source de vérité) ; identité **publique** du salon = `salons.name` ; lignes = `appointment_services` (`price_at_booking` figé) pour un RDV, ou `services` (`Service.price`) pour une prestation seule. **Aucune** table, colonne, index ni migration côté paiement. Le total affiché reste `payment.amount` (cohérence somme des lignes = `amount` garantie par #33) ; les lignes sont informatives.

### 2. Endpoint d'**appartenance** (pas de portée salon), `client_id` imposé serveur

`GET /me/receipts` (page, plus récent d'abord) et `GET /me/receipts/{payment_id}` (détail) sont gardés par `require_permission(PAYMENT_READ_OWN)` **sans** `require_salon_scope` : un client n'a **aucune** portée salon et paie potentiellement dans plusieurs salons. Le filtre `payments.client_id = principal.id` est **imposé serveur** (jamais lu du corps/query) — patron identique à `GET /appointments/history` (#30). Un `payment_id` d'un autre client **ou** inexistant est un `404` **neutre indiscernable** (non-oracle §11.3) ; un paiement **sans `client_id`** (encaissement au comptoir) n'appartient à aucun client.

### 3. Nouvelle permission fermée `PAYMENT_READ_OWN`, détenue par le **seul** `CLIENT`

Ajoutée à l'enum `Permission` et à `ROLE_PERMISSIONS[CLIENT]` uniquement (matrice §4.1). Ni `MANAGER`, ni `HAIRDRESSER`, ni `ADMIN` ne la reçoivent (le gérant lit déjà les transactions via #35 avec `CASH_JOURNAL_READ`). Deny-by-default (ADR-0015) reste intact ; un test de matrice fige la règle.

### 4. Port dédié `ReceiptRepository` (lecture)

Un port dédié (`list_receipts_for_client`, `count_receipts_for_client`, `get_receipt_for_client`) garde `PaymentRepository` focalisé sur l'écriture/l'historique gérant (#35). Toutes les méthodes filtrent **inconditionnellement** sur `client_id` (appartenance §11.2 en défense). Aucune méthode d'écriture n'est exposée.

### 5. Non-PII (§11.3) et non-remise assumée

Le reçu ne contient **que** des données que le client possède déjà : son propre paiement, l'identité **publique** du salon (`salons.name`, déjà exposée sans authentification par #18/#19) et les prestations qu'il a réglées — **jamais** `recorded_by`, ni un autre client, ni donnée de gestion. Montants sérialisés en **chaîne décimale** (`NUMERIC(12,2)`, jamais de flottant). **Aucun** canal de remise n'est activé : rien n'est envoyé à un appareil ni à un opérateur tiers. Le stub no-op existant n'est pas sollicité. Aucun chemin n'entre dans `PUBLIC_ROUTE_PATHS` : un reçu financier n'est jamais public.

### 6. Variante « envoyé » (ligne `notifications`) **explicitement écartée** au MVP

Matérialiser le mot « envoyé » via une ligne `notifications` (`type=RECEIPT`) exigerait d'**élargir l'enum `NotificationType`** + une **migration Alembic** de la contrainte `CHECK` `notifications.type`, de coupler le chemin d'écriture atomique du paiement, et **ne pourrait rien pousser** tant que le worker M5 n'existe pas. Cela dépasse le périmètre Could/S ; la remise proactive (push/SMS) est renvoyée à **M5 (Épic 7)**.

## Conséquences

- **Positif.** Le client dispose enfin d'une **preuve récupérable** de ses paiements dès l'enregistrement (#33), sans nouvelle table ni migration. `PAYMENT_READ_OWN` est la première permission de lecture financière côté client, ajoutée sans élargir aucun autre droit. La tranche est hexagonale, pure et testée.
- **Compromis.** Le reçu est une **projection JSON** rendue par le client ; la génération d'un **PDF** téléchargeable (mise en page, stockage S3 ADR-0005) est une évolution ultérieure. La composition des lignes se fait par paiement (page bornée par `RECEIPTS_LIMIT_MAX`) — une jointure agrégée unique reste une optimisation possible si le profilage le justifie.
- **Non-remise.** #38 **génère** un reçu, il n'**envoie** rien : la remise proactive (push/SMS/e-mail) est M5 (Épic 7, ADR-0006). Un paiement `ADJUSTED` (#34) apparaît tel qu'enregistré (`status` reflété) ; un éventuel avertissement « corrigé » côté client reste à trancher (impact mineur).
- **Écran mobile.** L'écran client « Reçu » (accès depuis « Mon historique ») consomme ces endpoints sans changement backend ; il peut être livré séparément.
- **Suivi.** Un test e2e SQL réelle (PostgreSQL 16, `DATABASE_URL`) verrouille le parcours : paiement d'un RDV → reçu récupérable par le client (lignes + total + salon) ; jamais par un tiers (`404`) ; paiement sans `client_id` invisible ; `401`/`403`.
