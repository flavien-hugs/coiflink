# ADR-0037 : Campagnes/messages aux clients — table dédiée `campaigns`, segment salon-scopé sur les fiches, permission `CUSTOMER_MANAGE` réutilisée, remise différée M5

- **Statut** : Accepté
- **Date** : 2026-08-05
- **Décideurs** : équipe CoifLink
- **Issue** : #49 (US-7.5 — Campagnes/messages aux clients)
- **Référence PRD** : §6 Épic 7 (US-7.5), §8.4 (traçage des notifications critiques), §9.8 (types/canaux
  de notification), §11.2 (isolation par salon), §11.3 (données personnelles / consentement marketing),
  §11.4 (journalisation), §12.1 (garde de latence/coût)
- **S'appuie sur** : [ADR-0026](./0026-fiche-client-portee-salon.md) (fiches clients salon-scopées,
  `CustomerFilter`, permission `CUSTOMER_MANAGE`), [ADR-0033](./0033-notification-confirmation-rdv.md)/
  [ADR-0034](./0034-rappel-automatique-avant-rdv.md)/[ADR-0035](./0035-notification-salon-a-la-reservation.md)/
  [ADR-0036](./0036-notification-annulation-modification.md) (trio domaine/port/adapter de notification,
  émission/trace atomique, remise différée M5+), [ADR-0006](./0006-notifications-fcm-sms.md) (FCM/SMS,
  remise asynchrone différée), [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC
  deny-by-default)

## Contexte et problème

Le PRD (§6 Épic 7, US-7.5) pose : « en tant que gérant, je veux envoyer un message à un segment de
clients (rappel, promo, fermeture) ». Le critère d'acceptation de l'issue (#49) est : **« Le gérant
envoie un message à un segment de clients. »**

Trois constats structurent la décision :

1. **Le socle de notification (#45–#48) est centré sur le RDV, pas transposable tel quel.** Le trio
   domaine/port/adapter (`domain/notification.py`, `NotificationRepository.enqueue`,
   `SqlNotificationRepository`) écrit une ligne `notifications` **par destinataire unique**, rattachée à
   un `appointment_id` et portant un libellé **templaté fixe**. Une campagne est un concept
   **un-à-plusieurs** (un message diffusé à N fiches) avec un **texte libre composé par le gérant** — ni
   la forme (une ligne par destinataire) ni le contenu (templaté) ne correspondent.
2. **Le fichier clients (#28) fournit déjà la population et le filtrage salon-scopés.** `customer_profiles`
   porte les fiches (walk-in ou liées à un compte), `CustomerFilter` (gender, plage de dates de création)
   et `count_for_salon`/`list_for_salon` existent déjà, salon-scopés (§11.2).
3. **La remise réelle (fan-out SMS) reste hors infra construite**, comme #45–#48 (ADR-0006) : aucun
   worker, aucun ordonnanceur, aucun fournisseur SMS concret. #49 **émet/trace** une campagne, il
   n'**achemine** rien.

## Décision

Créer une **table dédiée `campaigns`** (migration `0009`, `down_revision = 0008`) plutôt que de
matérialiser une ligne `notifications` par fiche destinataire. Le **segment** est un **prédicat
salon-scopé** traduit en `CustomerFilter` sur `customer_profiles` (#28), restreint aux fiches
**joignables par SMS** (`phone IS NOT NULL`) ; l'**effectif** (`recipient_count`) est un **snapshot
non-PII** (entier), résolu par **un seul** `COUNT`. La création réutilise la permission
**`CUSTOMER_MANAGE`** (aucune modification de `ROLE_PERMISSIONS`). La campagne et l'entrée d'audit
`CAMPAIGN_CREATED` sont **émises/tracées** atomiquement ; **rien n'est envoyé** (`status = PENDING`,
`sent_at = NULL`) — la remise proactive (fan-out SMS) reste **différée M5+**.

### 1. Table dédiée `campaigns` (migration `0009`) — pas de fan-out dans `notifications`

Matérialiser N lignes `notifications` à la création (une par fiche du segment) serait **volumineux**
(§12.1, un salon peut avoir des centaines de fiches), figerait un **snapshot de PII** (téléphones) au
moment de la création plutôt qu'à l'envoi, et exigerait un rattachement `customer_profile_id` que
`notifications.user_id → users.id` ne porte pas (une fiche walk-in n'a **pas** de compte `users`). La
table `campaigns` (`salon_id`, `created_by`, `type`, `segment`, `channel`, `title`, `message`,
`recipient_count`, `status`, `sent_at`, `created_at` ; FK **RESTRICT** vers `salons`/`users`, `CHECK`
dérivés de `CampaignType`/`CampaignSegment`/`NotificationChannel`/`CampaignStatus`, index
`(salon_id, created_at)`) porte un **effectif**, pas une liste de destinataires. Le fan-out réel
(résolution `segment → customer_profiles.phone`) est **différé** au worker M5+, qui re-résout le segment
**à l'envoi** — les numéros ne sont jamais copiés dans `campaigns`.

### 2. Segment = prédicat salon-scopé sur les fiches (#28), joignabilité SMS imposée

`domain/campaign.py::segment_to_customer_filter` traduit `segment` (`ALL`/`FEMALE`/`MALE`/`OTHER`) en
`CustomerFilter` : `ALL` → toutes les fiches **joignables** du salon (`has_phone=True`) ;
`FEMALE`/`MALE`/`OTHER` → même joignabilité **et** genre exact. La population de destinataires est les
**fiches** (`customer_profiles`), pas les comptes segmentés par activité (#42, qui exclut les walk-in) :
#49 dépend de #28, et la majorité des clients d'un salon sont walk-in. Une fiche sans téléphone ne peut
recevoir de SMS — elle n'entre **jamais** dans `recipient_count`, même si son genre correspond au segment
ciblé. Le détail (`from`/`to`, un critère plus fin type « inactif depuis N mois ») n'est **pas** retenu au
MVP ; extension naturelle documentée en Conséquences.

### 3. Effectif = un seul `COUNT` salon-scopé, jamais un fan-out matérialisé

`CreateCampaign` résout `recipient_count` via **un** `CustomerRepository.count_for_salon(salon_id,
filter=segment_to_customer_filter(segment))` — aucune liste de fiches n'est chargée ni journalisée
(garde de coût §12.1). Un segment sans fiche joignable donne un effectif `0` : la campagne est **quand
même créée** (l'émission n'est pas conditionnée à un effectif non nul — un gérant peut composer une
campagne avant d'avoir des fiches joignables dans un segment donné).

### 4. Permission : `CUSTOMER_MANAGE` réutilisée (pas de `CAMPAIGN_SEND` dédiée)

Le gérant qui gère déjà son fichier clients (#28, `CUSTOMER_MANAGE`) peut créer une campagne vers ce même
fichier — aucune modification de `ROLE_PERMISSIONS` (§4.1), cohérent avec le choix de #28 de ne pas
élargir la matrice. `require_salon_scope` + `require_permission(CUSTOMER_MANAGE)` sur **toutes** les
routes du router `campaigns.py` : seul le **MANAGER** avec le salon dans sa portée. `CLIENT`/
`HAIRDRESSER`/`ADMIN` et un gérant hors portée reçoivent un `403` générique (ADR-0015).

### 5. Domaine pur + cas d'usage — texte libre validé, pas de libellé templaté

`domain/campaign.py` valide et normalise (`strip`, bornes) le `type`/`segment`/`title`
(≤255 caractères)/`message` (≤1000 caractères, borne **applicative** au-delà de la colonne `TEXT`) —
différence structurante avec #45–#48 dont les libellés sont **fixes**. `build_campaign` assemble une
`CampaignToCreate` **neutre** (aucune donnée de destinataire acceptée en entrée). `CreateCampaign`
(application) valide → résout le canal (SMS, `resolve_notification_channel` partagé avec #45) → résout
l'effectif (COUNT) → persiste (`status = PENDING`) → journalise `CAMPAIGN_CREATED`, toutes ces étapes sur
la **même** `Session` (`get_session`) : une validation échouée (titre vide, segment inconnu, etc.) ne
persiste **ni** campagne **ni** audit.

### 6. Audit `CAMPAIGN_CREATED` neutre — trace d'une action manuelle du gérant

Contrairement à #45–#48 (effets de bord d'événements RDV déjà audités par ailleurs), une campagne est une
**action manuelle** du gérant méritant sa propre entrée d'audit (§11.4). `metadata` ne porte que `type` +
`segment` + `recipient_count` (entier) — **jamais** le titre ni le corps du message composé par le
gérant, ni un téléphone. La ligne `campaigns` elle-même **est** la trace primaire (type, canal, effectif,
statut, `created_at`) ; l'audit en est le complément côté journal d'actions.

### 7. Non-remise assumée, statut `PENDING` (honnête)

Comme #45–#48, #49 **émet/trace** ; il n'**envoie** rien. `status` reste `PENDING`, `sent_at` reste
`NULL` — le worker M5+ passera `SENT`/`FAILED` à la remise réelle, en résolvant `segment →
customer_profiles.phone` **à l'envoi** (jamais copié dans `campaigns`). Aucun appel réseau externe
n'entre dans le chemin de requête (§12.1) : la création n'ajoute qu'un `COUNT` + un `INSERT`. Aucun
secret n'entre au dépôt (#5).

### 8. Lecture minimale (`GET`), non-PII — parité #28/#45–#48

`GET /salons/{salon_id}/campaigns` (paginé, `CampaignSummaryResponse`) rend la création observable, comme
#28, sans exposer de destinataire ni le corps du message — celui-ci n'est renvoyé qu'à la création
(`POST`, `CampaignResponse`). Aucun rapport de délivrabilité (rien n'est remis).

## Conséquences

- **Positif.** Un gérant peut composer et **émettre/tracer** une campagne ciblée vers un segment
  salon-scopé de ses fiches clients, sans construire d'infra de remise. Table dédiée, séparée du concept
  RDV — pas de dette de modélisation sur `notifications`. Effectif non-PII, coût borné (un `COUNT`).
- **Compromis.** L'AC est satisfait **au sens de l'émission/trace**, pas de la remise : rien n'est
  réellement envoyé au client (le gérant crée la campagne, mais aucun SMS ne part). Le segment reste
  simple (genre + joignabilité) ; un critère d'activité plus fin (inactif depuis N mois) est une extension
  future, pas ce lot.
- **Non-remise.** Le fan-out SMS et l'ordonnanceur relèvent du **worker M5+** (ADR-0006), avec des
  fournisseurs concrets (#5). Aucun point d'accroche mort n'est ajouté ici.
- **Risque signalé, pas bloquant au MVP.** #49 introduit un **envoi marketing** potentiel ; l'opt-out/
  consentement par client n'existe pas encore (hors code, ADR-0026). Comme rien n'est **réellement**
  envoyé au MVP (émission/trace seulement), le risque est **contenu** — mais le durcissement du
  consentement (#52) est un **pré-requis** avant toute remise réelle M5+.
- **Périmètre.** Hors champ : fan-out réel, worker/ordonnanceur, fournisseur SMS concret, opt-out/
  consentement marketing (#52), UI web `/gerant` (formulaire de campagne — backend-first comme #45–#48),
  rapport de délivrabilité.
- **Suivi.** Tests e2e SQL réelle (PostgreSQL 16, `DATABASE_URL`) verrouillent le parcours : création →
  1 ligne `campaigns` `PENDING`/`sent_at NULL` ; effectif = `COUNT` réel des fiches joignables du segment
  (walk-in sans téléphone exclu, même si le genre correspond) ; isolation salon (liste/effectif) ;
  atomicité (payload invalide → aucune campagne ni audit) ; `CHECK` `type`/`segment` acceptant toutes les
  valeurs d'énumération ; round-trip Alembic de `0009`.
