# Campagnes / messages aux clients (US-7.5)

> Spécification de planification pour l'issue GitHub **#49 — US-7.5 : Campagnes/messages aux
> clients** (`feature` `notifications` · **Could** · Effort **M** · PRD §6 Épic 7 / §8.4
> « Notifications » / §9.5 « Fiche client » / §9.8 « Notification » / §11.2 « Isolation par salon » /
> §11.3 « Données personnelles » / §11.4 « Journalisation » / §12.1 « Latence »).
> **Dépend de #28** (création d'une fiche client, livré) — la population de destinataires est
> l'ensemble des **fiches clients** (`customer_profiles`) rattachées au salon. S'appuie sur le
> **socle de notification** livré par **#45** (US-7.1), **#46** (US-7.2), **#47** (US-7.3) et **#48**
> (US-7.4) : émission/trace atomique, **remise proactive différée M5+** (ADR-0006).
> **Cette spec ne produit pas de code** : elle décrit l'approche à implémenter dans une phase
> ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 7, US-7.5) demande : **« en tant que gérant, je veux envoyer des campagnes/messages
à mes clients »**, avec pour exemples *« campagnes simples : rappel, promotion, fermeture
exceptionnelle »*. Le critère d'acceptation de l'issue #49 est :

- **Le gérant envoie un message à un segment de clients.**

C'est la **dernière** user story de l'Épic 7 (Notifications) et une story de priorité **Could** (la
plus basse dans MoSCoW), effort **M**. Elle diffère **fondamentalement** des quatre précédentes
(#45–#48) :

| | #45–#48 (confirmation / rappel / au salon / annulation-modif) | **#49 (campagnes)** |
| --- | --- | --- |
| **Déclencheur** | événement du **cycle de vie d'un RDV** (réservation, changement de statut) | **action manuelle du gérant** (il compose et envoie) |
| **Destinataire** | **une** partie (le client `client_id`, ou le gérant `owner_id`) | **un segment** de clients (fan-out **un-à-plusieurs**) |
| **Rattachement** | un **RDV** précis (`appointment_id`) | **aucun RDV** — un **salon** et son fichier clients (#28) |
| **Contenu** | `title`/`message` **templatés fixes et neutres** (aucune PII, aucun texte libre) | **texte libre composé par le gérant** (promotion, fermeture…) |
| **Cardinalité** | 1 à 2 lignes par événement | 1 campagne → **N** destinataires |

### État actuel du dépôt (vérifié pour cette spec)

Le **socle de notification est livré** (#45 → #46 → #47 → #48), mais il est **entièrement centré sur
le RDV** — il ne couvre **pas** une campagne :

1. **Le trio domaine / port / adapter existe** mais est modélisé pour une notification **liée à un
   RDV** :
   - `domain/notification.py` — `NotificationToCreate` (dataclass `frozen`, miroir de
     `models.Notification`, champs `user_id`/`salon_id`/`appointment_id`), `ChannelAvailability`,
     `resolve_notification_channel` (fonction pure **PUSH → SMS → IN_APP**, `WHATSAPP` exclu V2), et
     des **constructeurs à libellés fixes** (`build_confirmation_notification`,
     `build_reminder_notifications`, `build_salon_new_booking_notification`,
     `build_client_cancellation_notification`, …). **Aucun** constructeur ne porte de **texte libre**.
   - `application/ports/notification_repository.py` — `NotificationRepository(Protocol)` :
     `enqueue(notification) -> None` et `cancel_pending_for_appointment(appointment_id) -> None`.
   - `adapters/outbound/persistence/notification_repository.py` — `SqlNotificationRepository`
     (`session.add(...)` + `flush()`, **sans commit** ; ne journalise **jamais** destinataire ni
     contenu, ADR-0006).
2. **La table `notifications`** (`models.Notification`, migrations `0001` + `0006` + `0007` + `0008`)
   porte `user_id`/`salon_id`/**`appointment_id`** (tous nullable, FK **RESTRICT** → `users`/`salons`/
   `appointments`), `type` (`CHECK` = `NotificationType`), `channel`, `title`/`message` (**NOT
   NULL**), `status` (défaut `PENDING`), `sent_at` (nullable), `scheduled_for` (nullable). **Aucune**
   colonne ne relie une notification à une **fiche client** (`customer_profiles`) ni à une
   **campagne**. Le `user_id` référence `users.id` — **pas** `customer_profiles.id`.
3. **La fiche client (#28) est la population de destinataires** : `customer_profiles` (migration
   `0001` + `0005`) porte `salon_id`, `user_id` **nullable** (walk-in — **jamais rattaché à un compte
   dans le périmètre #28**, anti-oracle ADR-0026), `full_name`, `phone` (E.164 optionnel), `gender`,
   `notes`, `last_visit_at`, `total_visits`. Le dépôt `SqlCustomerRepository` sait **lister/filtrer**
   par salon (`list_for_salon`, `count_for_salon`) via un `CustomerFilter` **validé** (`q` nom,
   `gender`, plage de dates de création) et **compter** (`count_for_salon`). L'écrasante majorité des
   fiches est **walk-in** (pas de compte, pas de jeton push) : le canal réaliste est donc **SMS** vers
   `customer_profiles.phone`.
4. **La segmentation existe déjà côté statistiques** (#42, US-6.4) :
   `domain/client_segments.py::classify_client_segments` répartit les **comptes** en
   `new`/`recurring`/`inactive`/`active` sur une période, dérivé des visites **`COMPLETED`**
   (`appointment_repository.segment_active_clients`). **Attention** : #42 segmente des **comptes**
   (`client_id`), pas des **fiches** walk-in — vocabulaire réutilisable, mais **population différente**
   (voir Risks §2/§3).
5. **La remise réelle reste différée M5+** (ADR-0006/0030/0033/0034/0035/0036) : **aucun worker de
   remise, aucune file Redis câblée, aucun fournisseur SMS/email concret, aucun ordonnanceur, aucun
   registre de jetons d'appareil.** Le seul adapter « d'envoi » livré est le **stub no-op** d'OTP
   (`otp_sender_stub.py`), qui ne journalise jamais destinataire ni contenu.
6. **RBAC / audit** : `Permission.CUSTOMER_MANAGE` (matrice §4.1, **seul le `MANAGER`**) protège déjà
   les routes `/salons/{salon_id}/customers` (#28). `AuditAction` porte `CUSTOMER_CREATED`,
   `CUSTOMER_NOTE_UPDATED`, `PAYMENT_RECORDED`, … et journalise des `metadata` **vides** (aucune PII).
   Aucune permission `CAMPAIGN_*` n'existe.

### Le gap que #49 comble

Aujourd'hui, **rien** ne permet à un gérant de **composer** un message et de le **diffuser** à un
**ensemble** de ses clients. #49 introduit ce concept nouveau — une **campagne** : un message
(type + titre + corps, composé par le gérant) adressé à un **segment** du fichier clients (#28) du
salon. Comme #45–#48, l'interprétation MVP fidèle et livrable, cohérente avec ADR-0006, est :

> **Émettre/tracer** la campagne en persistant une ligne (le salon, l'auteur, le type, le segment
> ciblé, le message, un **effectif de destinataires** non-PII, `status = PENDING`) **dans la même
> unité de travail** que l'action. Cette ligne **est** la trace de l'action (§11.4) et **la file** que
> consommera le futur worker pour **résoudre le segment → fiches → téléphones** et **envoyer** les
> SMS. L'**émission** satisfait l'AC « le gérant envoie un message à un segment de clients » ; la
> **remise proactive** (fan-out SMS/push réel) reste **différée M5+**.

## Goals

- **Permettre au gérant de créer une campagne, atomiquement.** Exposer
  `POST /salons/{salon_id}/campaigns` (portée salon §11.2 + `require_permission`) : le gérant fournit
  un **type** (`REMINDER`/`PROMOTION`/`EXCEPTIONAL_CLOSURE`), un **segment cible**, un **titre** et un
  **corps de message**. Le serveur **valide**, **résout l'effectif** du segment (une requête `COUNT`
  salon-scopée sur `customer_profiles`), **persiste** la campagne (`status = PENDING`) et **journalise**
  l'action — le tout dans la **même** `Session` (commit/rollback conjoint).
- **Segment = prédicat sur le fichier clients (#28), imposé serveur.** Le segment cible est un
  **prédicat structuré et validé** sur `customer_profiles` du salon — au minimum **tout le fichier**
  (`ALL`), en réutilisant le `CustomerFilter` existant (#28/#35 : `gender`, plage de dates de création,
  et — via `last_visit_at`/`total_visits` de la fiche — un critère d'inactivité optionnel, voir
  Risks §3). Le `salon_id` vient **toujours du chemin** validé, jamais du corps.
- **La campagne = trace (§11.4).** La ligne persistée (salon, auteur, type, segment, effectif,
  `status`, `created_at`, `sent_at` ultérieur) **constitue** la trace de l'action importante. En
  complément, journaliser une entrée d'audit **neutre** `CAMPAIGN_CREATED` (`metadata` = type + effectif
  **non-PII**, **jamais** le corps du message, **jamais** un téléphone/nom) — recommandé car une
  campagne est une **action manuelle du gérant** (§11.4), non un effet de bord d'un événement RDV
  (à trancher, Risks §6).
- **Non-fuite de PII (§11.3, ADR-0006).** La campagne stocke le **corps composé par le gérant**
  (contenu **métier**, pas une PII client) et un **effectif** (entier). Elle ne stocke **aucun**
  téléphone, nom ni identité de destinataire : le worker de remise (futur) résoudra
  `segment → customer_profiles.phone` **à l'envoi**, jamais copié dans la campagne. Le message n'est
  **jamais journalisé** (ni logs applicatifs, ni `audit_logs.metadata`).
- **Canal réaliste = SMS.** La population #28 étant walk-in (pas de compte, pas de jeton push), le
  canal effectif au MVP est **SMS** (`customer_profiles.phone`). Une fiche **sans téléphone** ne peut
  recevoir de SMS : l'effectif compté doit refléter cette exclusion (voir Risks §4).
- **Remise différée, assumée et documentée (cohérence #45–#48/#38).** Aucun envoi réel
  (SMS/push/email), **aucun** ordonnanceur, **aucun** fan-out par destinataire. `status = PENDING`,
  `sent_at = NULL`. Aucun appel réseau externe dans le chemin de requête (budget §12.1). **Aucun**
  secret n'entre au dépôt (#5).
- **Garde de coût (§12.1).** La création n'exécute **qu'un** `COUNT` salon-scopé (effectif) + les
  `INSERT` de la campagne et de l'audit — **jamais** une matérialisation par destinataire (qui pourrait
  être volumineuse). La route reste bien sous 3 s quel que soit le nombre de fiches.
- **Bornes d'entrée explicites.** `title` ≤ 255 (aligné `String(255)`), `message` borné
  **applicativement** (colonne `TEXT`, borne ≤ 1000 recommandée, §12.1), `type`/`segment` ∈ énumérations
  fermées, `CustomerFilter` déjà borné (#28). La validation précède **toute** écriture — un champ
  invalide ne produit ni campagne, ni entrée d'audit.
- **Couverture de tests.** Domaine (validation type/segment/titre/message, neutralité), cas d'usage
  (effectif résolu salon-scopé, persistance `PENDING`, atomicité, **aucune** campagne sur validation
  échouée), API (RBAC deny-by-default, portée, `422`/`403`), e2e PostgreSQL (ligne réelle, contraintes
  FK `RESTRICT`/`CHECK`, ordre de nettoyage), sécurité (aucun contenu/PII journalisé).

## Non-Goals

- **Construire l'infra de remise (worker Redis, ordonnanceur, SMS/FCM, registre de jetons).** La
  remise **proactive** (résolution du segment → fiches → téléphones, envoi des SMS, passage `SENT` +
  `sent_at`) dépend d'un worker consommant la file (ADR-0006) + fournisseurs concrets (#5), **différés
  M5+**. #49 **émet/trace** la campagne ; il n'envoie **aucun** message.
- **Matérialiser une ligne par destinataire** (`notifications` par fiche, ou table
  `campaign_recipients`). Le fan-out réel appartient au worker (il re-résout le segment à l'envoi) —
  matérialiser N lignes à la création serait volumineux (§12.1) et figerait un snapshot de PII
  (téléphones) inutilement (voir Risks §1). #49 stocke un **effectif** (entier), pas la liste.
- **Endpoint de lecture/consultation riche des campagnes ou de leur délivrabilité** (statuts d'envoi
  par destinataire, taux de délivrance). Une **liste minimale** non-PII des campagnes du salon peut
  accompagner la création (parité #28), mais tout rapport de remise est **différé** (rien n'est remis
  au MVP).
- **Segmentation avancée / ciblage marketing** (combinaisons booléennes riches, RFM, exclusions,
  opt-out par client, préférences de canal, planification/récurrence de campagne, A/B). Le MVP se
  limite à un segment **simple** (au minimum `ALL`, + les prédicats `CustomerFilter` existants).
- **Recueil du consentement / opt-out marketing (RGPD-like).** #28 note déjà que le **consentement**
  est un **processus métier hors code** au MVP et qu'aucun droit à l'oubli n'est promis (durcissement
  M6, #52). #49 n'ajoute **pas** de mécanisme d'opt-out ; il est signalé comme suivi (voir Risks §8).
- **Écran mobile / web dédié.** Comme #45–#48 (livrés **backend-first / backend-only**), aucune UI
  n'est requise par l'AC (« le gérant **envoie** » = un endpoint). Une éventuelle page `/gerant` est
  **optionnelle** et différée (voir Risks §9).
- **Modifier / annuler / renvoyer une campagne** après création. Le MVP crée (émet/trace) ; l'édition,
  la suppression et le renvoi sont hors périmètre.

## Relevant Repository Context

### Stack & architecture (figées par les ADR)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Architecture | **Hexagonale** : `domain/` (pur) → `application/` (+ `ports/`) → `adapters/` | [0008](../docs/adr/0008-architecture-hexagonale.md) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic + psycopg 3, **PostgreSQL 16** | [0009](../docs/adr/0009-orm-migrations-sqlalchemy-alembic.md) |
| Autorisation | RBAC **deny-by-default**, permissions §4.1, **portée salon §11.2** | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Notifications | **FCM + SMS via file Redis**, WhatsApp V2, **remise asynchrone différée** ; stub no-op au MVP | [0006](../docs/adr/0006-notifications-fcm-sms.md) |
| Fiche client (#28) | ressource salon-scopée `customer_profiles`, walk-in `user_id NULL`, anti-oracle, unicité `(salon_id, phone)` | [0026](../docs/adr/0026-fiche-client-portee-salon.md) |
| Confirmation/rappel/salon/annulation (#45–#48) | ligne `notifications` `PENDING` persistée atomiquement, **remise différée** | [0033](../docs/adr/0033-notification-confirmation-rdv.md) · [0034](../docs/adr/0034-rappel-automatique-avant-rdv.md) · [0035](../docs/adr/0035-notification-salon-a-la-reservation.md) · [0036](../docs/adr/0036-notification-annulation-modification.md) |

`docs/adr/` s'arrête aujourd'hui à **ADR-0036** (#48) ; la dernière migration livrée est **`0008`**
(`0008_notification_appointment_update_type`). L'introduction du concept de **campagne** (nouvelle
table, nouvelles énumérations, message libre du gérant, fan-out différé) justifie un **ADR-0037**
« Campagnes/messages aux clients — table dédiée, émission/trace atomique, segment = prédicat
salon-scopé sur les fiches, remise (fan-out SMS) différée M5 » (voir *Documentation Updates*).

### Patrons à réutiliser tels quels

- **Ressource imbriquée sous le salon (#28/#17)** — router `/salons/{salon_id}/campaigns` avec
  `require_salon_scope` (isolation §11.2) + `require_permission(...)`. Le `salon_id` vient **toujours**
  du chemin validé ; le corps est `extra="ignore"` (anti-élévation, miroir de `CreateCustomerRequest`).
- **Trio domaine / port / adapter + écriture atomique (`flush` sans `commit`)** — gabarit direct du
  `SqlCustomerRepository`/`SqlNotificationRepository` : `add()` + `flush()` sur la **même** `Session`
  que l'audit (`get_session` pilote le commit). Nouvelle table `campaigns`, nouveau
  `CampaignRepository` (port) + `SqlCampaignRepository` (adapter).
- **Résolution de l'effectif du segment (COUNT salon-scopé)** — `SqlCustomerRepository.count_for_salon`
  (#28) fait déjà un `COUNT` filtré par `CustomerFilter`. Le prédicat de segment `ALL`/filtre réutilise
  **directement** cette brique (aucun nouveau chemin d'agrégat). *(Si le segment d'activité #42 est
  retenu, `segment_active_clients` fournit les effectifs — mais sur des comptes, voir Risks §2/§3.)*
- **Énumération fermée → `CHECK` dérivé (`models.py::enum_check`)** — `CampaignType`, `CampaignSegment`,
  `CampaignStatus` dans `domain/enums.py` ; les colonnes `text` + `CHECK` du modèle `Campaign` en
  **dérivent** (jamais de type `ENUM` PostgreSQL, ADR conventions). Patron de `NotificationType`.
- **Migration Alembic chaînée** — dernière révision livrée `0008` (`down_revision = "0008"`) ; #49
  ajoute `0009_campaigns` (création de table + `CHECK` + index). Round-trip `upgrade`/`downgrade`
  vérifié en CI (PostgreSQL 16).
- **Journalisation §11.4/§11.3 neutre** — `AuditAction.CAMPAIGN_CREATED` (nouveau), `metadata`
  **non-PII** (type + effectif ; **jamais** le message ni un téléphone/nom), écrite dans la **même**
  unité de travail (patron `CUSTOMER_CREATED` #28, `PAYMENT_RECORDED` #33).
- **Injection surchargeable en test** — providers `get_*_repository(session)` +
  `app.dependency_overrides` ; e2e adossés à un vrai PostgreSQL, sautés si `DATABASE_URL` absent ; garde
  deny-by-default (`tests/test_security_guards.py::unprotected_routes`) — **aucun** chemin campagne dans
  `PUBLIC_ROUTE_PATHS`.

### Contraintes transverses documentées

- **PRD §8.4 / Épic 7** : rappel/promotion/fermeture exceptionnelle ; **campagnes simples**. #49 les
  matérialise comme un **type de campagne**.
- **PRD §11.2 / ADR-0015 / ADR-0026** : isolation par salon — segment **et** effectif calculés
  **uniquement** sur les `customer_profiles` du salon de la portée ; `salon_id` du chemin, jamais du
  corps. Deny-by-default : aucune route publique.
- **PRD §11.3 / §11.4 / ADR-0006** : collecte minimale, **non-fuite de PII**, **ne jamais journaliser**
  le corps du message / les numéros ; **clés SMS/FCM hors dépôt** (#5) ; **trace** des actions
  importantes (la ligne `campaigns` + l'audit `CAMPAIGN_CREATED`).
- **PRD §12.1** : réponse API < 3 s → la remise réelle (fan-out) et l'ordonnancement restent **hors**
  chemin requête. #49 n'ajoute qu'**un** `COUNT` + quelques `INSERT` locaux.
- **CONTRIBUTING.md** : commits conventionnels ; **aucune signature IA**. **Test gate** :
  `scripts/test-gate.sh` (pytest + npm test + flutter test).

## Proposed Implementation

Approche recommandée : **une campagne est une ligne d'une nouvelle table `campaigns`, émise dans la
même unité de travail que l'action ; segment = prédicat salon-scopé sur `customer_profiles` (#28) dont
seul l'effectif (entier, non-PII) est snapshotté ; canal SMS ; remise réelle (fan-out) différée M5+
(aucun envoi, aucun ordonnanceur, aucune ligne par destinataire).**

### (A) Data model — migration `0009_campaigns` (nouvelle table)

- **Énumérations** (`domain/enums.py`, dérivant les `CHECK`) :
  - `CampaignType` : `REMINDER`, `PROMOTION`, `EXCEPTIONAL_CLOSURE` (les trois exemples du backlog
    « rappel, promotion, fermeture exceptionnelle »).
  - `CampaignSegment` : au minimum `ALL` ; extension recommandée réutilisant le prédicat `CustomerFilter`
    (voir Risks §3). *(Alternative : réutiliser le vocabulaire #42 `NEW`/`RECURRING`/`INACTIVE`/`ACTIVE`
    — attention population « comptes » vs « fiches », Risks §2.)*
  - `CampaignStatus` : `PENDING` (MVP), `SENT`, `FAILED` (réservés au worker). *(Réutiliser
    `NotificationStatus` est possible mais mélange deux cycles de vie — préférer un enum dédié, à
    confirmer.)*
- **Table `campaigns`** (`models.Campaign`) :
  - `id` (uuid pk) ;
  - `salon_id` (FK `salons.id` **RESTRICT**, **NOT NULL** — salon-scopée §11.2) ;
  - `created_by` (FK `users.id` **RESTRICT**, **NOT NULL** — l'**auteur** gérant, imposé serveur) ;
  - `type` (`String(32)`, `CHECK` = `CampaignType`) ;
  - `segment` (`String(32)`, `CHECK` = `CampaignSegment`) — le segment ciblé ; les **paramètres** de
    filtre éventuels (gender, dates) peuvent être portés par un `segment_params` `JSONB` **non-PII**
    (bornes/critères structurels, **jamais** un identifiant/numéro de client) *(à confirmer, Risks §3)* ;
  - `channel` (`String(16)`, `CHECK` = `NotificationChannel` — `SMS` au MVP) ;
  - `title` (`String(255)`, **NOT NULL**) — composé par le gérant ;
  - `message` (`Text`, **NOT NULL**) — composé par le gérant, borné **applicativement** (≤ 1000) ;
  - `recipient_count` (`Integer`, **NOT NULL**) — **effectif snapshot** du segment à la création
    (non-PII) ;
  - `status` (`String(32)`, `CHECK` = `CampaignStatus`, défaut `PENDING`) ;
  - `sent_at` (`TIMESTAMPTZ`, nullable — `NULL` au MVP) ;
  - `created_at` (`_created_at()`).
  - **Index** : `ix_campaigns_salon_id (salon_id, created_at)` (liste du salon, la plus récente
    d'abord). **Aucune** table `campaign_recipients` (fan-out différé).
- **Migration** `0009_campaigns` (`down_revision = "0008"`) : `op.create_table(...)` + `CHECK`
  dérivés + index ; `downgrade()` = `op.drop_table("campaigns")`. **Aucun backfill**. Round-trip Alembic
  vérifié en CI (`backend` job, PostgreSQL 16).

### (B) Backend — domaine (`domain/campaign.py`, nouveau ; `domain/enums.py`, étendre)

- **Validation** (précède toute écriture ; erreurs de domaine **neutres**, sans reprendre le corps) :
  - `validate_campaign_title(title) -> str` (non vide après trim, ≤ 255) → `InvalidCampaignTitle`.
  - `validate_campaign_message(message) -> str` (non vide, ≤ `CAMPAIGN_MESSAGE_MAX_LENGTH`) →
    `InvalidCampaignMessage`.
  - `normalize_campaign_type(value) -> str` (∈ `CampaignType`) → `InvalidCampaignType`.
  - `normalize_campaign_segment(value, params?) -> CampaignSegment/predicate` (∈ `CampaignSegment`,
    params validés/bornés) → `InvalidCampaignSegment`.
- **Objet-valeur** `CampaignToCreate` (dataclass `frozen`, miroir des colonnes) : `salon_id`,
  `created_by`, `type`, `segment`, `channel`, `title`, `message`, `recipient_count`,
  `status = CampaignStatus.PENDING.value`. **Neutre** : ne porte **aucune** PII de destinataire.
- **Constructeur** `build_campaign(*, salon_id, created_by, type, segment, channel, title, message,
  recipient_count) -> CampaignToCreate` (gabarit `build_confirmation_notification`, mais **avec texte
  libre validé** — c'est la différence structurante). Export `__all__`.

### (C) Backend — ports & adapters

- **Port** `application/ports/campaign_repository.py::CampaignRepository(Protocol)` :
  `create(campaign: CampaignToCreate) -> Campaign` (`flush` sans `commit`, atomicité avec l'audit ;
  patron `CustomerRepository.create`). *(Optionnel, si liste minimale : `list_for_salon(salon_id, *,
  limit, offset) -> tuple[Campaign, ...]` + `count_for_salon`.)*
- **Adapter** `adapters/outbound/persistence/campaign_repository.py::SqlCampaignRepository` — mappe
  `Campaign` ↔ `models.Campaign` ; `add()` + `flush()` sans commit ; ne journalise **jamais** le
  message ni un destinataire.
- **Effectif du segment** : réutiliser `CustomerRepository.count_for_salon(salon_id, filter=...)` (#28)
  pour `recipient_count` — le segment `ALL` = `CustomerFilter()` vide ; un segment filtré = le
  `CustomerFilter` correspondant. *(Éventuel critère « avec téléphone » : ajouter une clause
  `phone IS NOT NULL` au `count_for_salon`, voir Risks §4.)*

### (D) Backend — cas d'usage (`application/campaigns.py::CreateCampaign`, nouveau)

`CreateCampaign(campaign_repository, customer_repository, audit_log).execute(salon_id, command,
*, actor_user_id)` :

1. **Valider** type/segment/titre/message (domaine) — un champ invalide lève avant toute écriture.
2. **Résoudre le canal** : `SMS` au MVP (`resolve_notification_channel(ChannelAvailability(
   has_push_token=False, has_phone=True))` → SMS, ou `NotificationChannel.SMS.value` explicite).
3. **Résoudre l'effectif** : `recipient_count = customer_repository.count_for_salon(salon_id,
   filter=<segment→filter>)` (salon-scopé §11.2).
4. **Persister** la campagne (`CampaignToCreate`, `status = PENDING`, `created_by = actor_user_id`) via
   `campaign_repository.create(...)`.
5. **Journaliser** `CAMPAIGN_CREATED` (`metadata` = `{"type": ..., "segment": ..., "recipient_count":
   ...}` — **non-PII**, jamais le message) dans la **même** `Session`.
6. Retourner la `Campaign` persistée (pour la réponse `201`).

Toutes les étapes 3–5 partagent la **même** `Session` (`get_session`) : une validation échouée (2) ne
persiste **rien** ; une erreur en (4)/(5) rollback la campagne **et** l'audit conjointement.

### (E) Backend — adapter entrant (`adapters/inbound/campaigns.py`, nouveau)

- **Router** `APIRouter(prefix="/salons", tags=["campaigns"])`.
- **`POST /{salon_id}/campaigns`** → `201 CampaignResponse` :
  - Dépendances : `require_salon_scope` + `require_permission(Permission.CUSTOMER_MANAGE)` (recommandé —
    voir Risks §5) ; providers `get_campaign_repository`, `get_customer_repository`, `get_audit_log`
    (même `Session`).
  - Corps `CreateCampaignRequest` (`extra="ignore"`) : `type`, `segment` (+ `segment_params?`),
    `title`, `message`. **Aucun** `salon_id`/`created_by`/`status`/`recipient_count` accepté du corps
    (imposés serveur).
  - Erreurs → `422` (`InvalidCampaign*`), `403` (rôle/portée, générique), `401`.
  - `created_by = principal.id` (jamais du corps).
- **(Optionnel) `GET /{salon_id}/campaigns`** → liste paginée non-PII (type, segment, titre, effectif,
  statut, `created_at`) — parité #28 (rend la création observable) ; **jamais** le message aux tiers,
  jamais de destinataire. *(À confirmer, Risks §9.)*
- **Aucune** route ajoutée à `PUBLIC_ROUTE_PATHS` ; **aucune** modification de la matrice RBAC si l'on
  réutilise `CUSTOMER_MANAGE`.

### (F) Backend — (différé, hors périmètre) remise proactive & fan-out

Le **worker M5+** (Épic 7, ADR-0006) interrogera les campagnes `PENDING`, **résoudra le segment →
`customer_profiles` du salon → téléphones** (`phone IS NOT NULL`), enverra les SMS via le fournisseur
concret (#5) et passera `SENT` + `sent_at`. La **résolution des numéros se fait à l'envoi** — **jamais**
copiée dans `campaigns`. **#49 ne construit ni worker, ni ordonnanceur, ni table de destinataires** —
cohérent avec #45–#48/#38 ; aucun point d'accroche mort n'est ajouté.

### (G) Trace §11.4 — la ligne `campaigns` + `CAMPAIGN_CREATED`

La **ligne `campaigns`** (type, segment, effectif, statut, `created_at`, `sent_at` ultérieur) **est** la
trace de la campagne. En complément, `CAMPAIGN_CREATED` (audit **neutre**) trace l'**action manuelle du
gérant** (§11.4) — recommandé car, contrairement à #45–#48 (effets de bord d'événements RDV déjà
audités), une campagne est une action initiée par un acteur, méritant sa propre entrée d'audit
(à trancher, Risks §6).

## Affected Files / Packages / Modules

### Backend (`backend/`) — à créer / modifier

| Fichier | Modification |
| --- | --- |
| `migrations/versions/0009_campaigns.py` | **nouveau** — `create_table("campaigns")` + `CHECK` (`type`/`segment`/`channel`/`status`) + index `ix_campaigns_salon_id` ; `downgrade` = `drop_table` |
| `coiflink_api/domain/enums.py` | **modifier** — `CampaignType`, `CampaignSegment`, `CampaignStatus` (+ `__all__`) |
| `coiflink_api/domain/campaign.py` | **nouveau** — `CampaignToCreate`, `Campaign`, validations (`validate_campaign_title`/`_message`, `normalize_campaign_type`/`_segment`), `build_campaign`, bornes (`CAMPAIGN_MESSAGE_MAX_LENGTH`) |
| `coiflink_api/domain/errors.py` | **modifier** — `InvalidCampaignTitle`, `InvalidCampaignMessage`, `InvalidCampaignType`, `InvalidCampaignSegment` (sous-classes `DomainError`) |
| `coiflink_api/domain/audit.py` | **modifier** — `AuditAction.CAMPAIGN_CREATED` (metadata neutre) |
| `coiflink_api/application/ports/campaign_repository.py` | **nouveau** — `CampaignRepository(Protocol)` (`create`, + `list_for_salon`/`count_for_salon` si liste) |
| `coiflink_api/application/campaigns.py` | **nouveau** — `CreateCampaign` (+ `CampaignCommand`) ; (optionnel) `ListSalonCampaigns` |
| `coiflink_api/adapters/outbound/persistence/models.py` | **modifier** — modèle ORM `Campaign` (table + FK RESTRICT + `CHECK` dérivés + index) |
| `coiflink_api/adapters/outbound/persistence/campaign_repository.py` | **nouveau** — `SqlCampaignRepository` (`create`, mapping domaine↔ORM, `flush` sans commit) |
| `coiflink_api/adapters/inbound/campaigns.py` | **nouveau** — router `POST /salons/{salon_id}/campaigns` (+ `GET` optionnel), schémas Pydantic, providers, mapping erreurs |
| `coiflink_api/adapters/inbound/__init__.py` / app factory | **modifier** — enregistrer le nouveau router |
| `coiflink_api/application/ports/customer_repository.py` | **lire / (option) étendre** — `count_for_salon` réutilisé ; option `phone IS NOT NULL` (Risks §4) |
| `backend/README.md` | section « Campagnes/messages aux clients » : création émise/tracée, segment salon-scopé, effectif non-PII, canal SMS, **non-remise (M5)**, migration `0009` |

### Backend — tests

| Fichier | Contenu |
| --- | --- |
| `tests/test_campaign_domain.py` | **nouveau** — validations (titre/message vides ou trop longs → erreur ; type/segment hors enum → erreur), `build_campaign` (`status = PENDING`, champs corrects, **sans PII**) |
| `tests/test_campaign_usecase.py` | **nouveau** — `CreateCampaign` : effectif résolu via `count_for_salon` (salon-scopé), campagne `PENDING` persistée, `CAMPAIGN_CREATED` audité (metadata non-PII), **atomicité** (même `Session`/fakes), validation échouée → **0** campagne/**0** audit |
| `tests/test_campaign_api.py` | **nouveau** — `POST` : `201` (auteur = principal, `salon_id` du chemin) ; corps privilégié ignoré ; `422` (champs invalides) ; **RBAC** : `CLIENT`/`HAIRDRESSER`/`ADMIN` → `403`, hors portée → `403` ; (option) `GET` liste non-PII |
| `tests/test_security_guards.py` | **vérifier** — aucune route campagne dans `PUBLIC_ROUTE_PATHS` ; matrice RBAC inchangée (si `CUSTOMER_MANAGE` réutilisé) |
| `tests/test_campaign_e2e.py` | **nouveau** (PostgreSQL réel, sauté si `DATABASE_URL` absent) — création → **1** ligne `campaigns` `status=PENDING`, `sent_at IS NULL`, `salon_id`/`created_by` corrects, `recipient_count` = nombre réel de fiches du segment, **sans** téléphone/nom stocké ; contraintes `CHECK`/FK `RESTRICT` réelles ; nettoyage `campaigns` (et `notifications`) **avant** `customer_profiles`/`appointments`/`users`/`salons` |
| `tests/conftest.py` | **étendre** — `FakeCampaignRepository` (accumule les créations) + réutiliser un fake `CustomerRepository` renvoyant un `count_for_salon` déterministe |

### Backend — à lire (sans modifier)

`adapters/outbound/persistence/customer_repository.py` (`count_for_salon`/`_filter_clauses`),
`adapters/inbound/customers.py` (patron router salon-scopé + `extra="ignore"` + mapping erreurs),
`adapters/outbound/persistence/session.py` (`get_session`, commit par requête),
`domain/notification.py` (`resolve_notification_channel`, canal SMS), `domain/client_segments.py`
(vocabulaire de segment #42, si retenu), `domain/audit.py` (`AuditAction`, metadata neutre),
migration `0008` (patron de migration chaînée), `adapters/outbound/notifications/otp_sender_stub.py`
(non-journalisation).

### Documentation (racine)

`README.md` (§6 : phrase de statut « M5 : campagnes/messages aux clients (US-7.5, #49) »),
nouvel ADR `docs/adr/0037-campagnes-messages-clients.md` + index `docs/adr/README.md`.

### Web (`web-dashboard/`) & Mobile (`app-mobile/`)

**Aucun** changement requis (backend-first, parité #45–#48 ; UI optionnelle/différée, Risks §9).

## API / Interface Changes

- **Nouvel endpoint** `POST /salons/{salon_id}/campaigns` (protégé : `require_salon_scope` +
  `require_permission(CUSTOMER_MANAGE)`) :
  - **Requête** `CreateCampaignRequest` (`extra="ignore"`) : `type` (`REMINDER`/`PROMOTION`/
    `EXCEPTIONAL_CLOSURE`), `segment` (au moins `ALL`) [+ `segment_params?` non-PII], `title` (≤ 255),
    `message` (≤ 1000). **Aucun** champ privilégié (`salon_id`/`created_by`/`status`/`recipient_count`)
    accepté du corps.
  - **Réponse** `201 CampaignResponse` : `id`, `salon_id`, `type`, `segment`, `channel`, `title`,
    `message`, `recipient_count`, `status` (`PENDING`), `sent_at` (`null`), `created_at`. **Aucune**
    identité de destinataire.
  - **Erreurs** : `401` (jeton), `403` (rôle/portée, générique), `422` (champs invalides).
- **(Optionnel) `GET /salons/{salon_id}/campaigns`** — liste paginée non-PII des campagnes du salon
  (parité lecture minimale #28). *(À confirmer, Risks §9.)*
- **CLI / interfaces web/mobile** : aucun changement.
- **Nouvelle variable d'environnement** : **aucune** au MVP (le fournisseur SMS et l'ordonnanceur, avec
  leurs secrets, en auront — différés M5+, #5).

Ces endpoints seront **documentés** (OpenAPI/docstrings) — nouvelle API publique du backend.

## Data Model / Protocol Changes

- **Migration `0009_campaigns` : nouvelle table `campaigns`** (`down_revision = "0008"`), avec FK
  **RESTRICT** vers `salons`/`users`, `CHECK` dérivés de `CampaignType`/`CampaignSegment`/
  `NotificationChannel`/`CampaignStatus`, index `ix_campaigns_salon_id (salon_id, created_at)`.
  `downgrade()` = `drop_table`. **Aucun backfill.**
- **Nouvelles énumérations** (`domain/enums.py`) : `CampaignType`, `CampaignSegment`, `CampaignStatus`.
- **`AuditAction.CAMPAIGN_CREATED`** (`domain/audit.py`) — la table `audit_logs` existe (#17/#28),
  **aucune** migration : seule une valeur d'action s'ajoute (colonne `action` `String`, non contrainte
  par un `CHECK` figé — vérifier ; sinon régénérer comme le patron `NotificationType`).
- **Sérialisation** : la campagne stocke le **corps composé par le gérant** (contenu métier) + un
  **effectif** (entier). Elle ne stocke **aucun** téléphone, nom ni identité de destinataire — le
  fan-out (numéros) est résolu **à l'envoi** par le worker (M5+), jamais copié.
- **`notifications`** : **inchangée** (aucun `campaign_id`, aucune ligne par destinataire au MVP).

## Security & Privacy Considerations

- **Isolation par salon (§11.2, ADR-0015/0026).** Le `salon_id` vient **toujours** du chemin validé
  (`require_salon_scope`), jamais du corps ; l'effectif (`count_for_salon`) et le futur fan-out ne
  portent **que** sur les `customer_profiles` de **ce** salon. `created_by = principal.id` (imposé
  serveur). Aucune campagne ne peut viser les fiches d'un autre salon.
- **RBAC deny-by-default (§4.1, ADR-0015).** Route protégée par `require_permission(CUSTOMER_MANAGE)` —
  **seul le `MANAGER`** (ni `CLIENT`, ni `HAIRDRESSER`, ni `ADMIN`). **Aucun** chemin ajouté à
  `PUBLIC_ROUTE_PATHS`. Si l'on préfère une permission dédiée `CAMPAIGN_SEND`, l'ajouter à la matrice
  (MANAGER) **et** aux tests de matrice (Risks §5).
- **Non-fuite de PII (§11.3, ADR-0006).** La campagne stocke le **message du gérant** (contenu métier,
  **pas** une PII client) et un **effectif** (entier) — **jamais** un téléphone, un nom, ni une identité
  de destinataire. Le message étant **diffusé à l'identique** à tout le segment, il **ne doit pas**
  contenir de PII d'un client précis (le système n'y injecte **aucune** donnée client). Le worker
  (futur) résout `segment → phone` **à l'envoi**, jamais copié dans la campagne.
- **Non-journalisation du contenu (ADR-0006).** L'adapter `create`, le cas d'usage et l'audit
  n'émettent **aucun** `logger`/`print` du **corps du message** ni d'un téléphone. `CAMPAIGN_CREATED`
  porte un `metadata` **non-PII** (type + segment + effectif) — **jamais** le message. Le stub OTP n'est
  pas sollicité.
- **Atomicité (§11.4).** Création + audit dans la **même** `Session` (`get_session`, commit/rollback
  conjoint) : pas de campagne « fantôme » sur une erreur, pas de campagne sans sa trace d'audit.
- **Remise différée = aucune exposition externe.** Aucun appel SMS/FCM, aucun ordonnanceur, aucun
  fan-out : rien n'est transmis à un tiers au MVP. **Clés/identifiants restent hors dépôt** (#5) — #49
  n'en introduit aucun.
- **Budget de latence & coût (§12.1).** La création n'exécute qu'**un** `COUNT` salon-scopé + les
  `INSERT` de la campagne et de l'audit — **jamais** de matérialisation par destinataire. La route reste
  bien sous 3 s quel que soit le nombre de fiches.
- **Consentement / opt-out marketing.** Le dépôt **documente** (ADR-0026) que le consentement est un
  **processus métier hors code** au MVP et qu'aucun droit à l'oubli n'est promis (durcissement M6, #52).
  #49 **n'affaiblit** aucune contrainte, mais introduit un **envoi marketing** : l'opt-out par client est
  signalé comme suivi (Risks §8) — à trancher avec le durcissement §11.3 (#52) **avant** toute remise
  réelle (M5+).

Le dépôt **documente** ces contraintes (PRD §8.4/§11.2/§11.3/§11.4/§12.1, ADR-0006/0026) : #49 les
respecte sans en affaiblir aucune.

## Testing Plan

### Backend — unitaires domaine (`pytest`, sans I/O)

- **`tests/test_campaign_domain.py`** (nouveau) : `validate_campaign_title`/`validate_campaign_message`
  (vide/blanc → erreur ; trop long → erreur ; nominal → trim), `normalize_campaign_type`/
  `normalize_campaign_segment` (hors enum → erreur), `build_campaign` (`status = PENDING`,
  `type`/`segment`/`channel`/`title`/`message`/`recipient_count` corrects ; l'objet **n'accepte aucune**
  donnée de destinataire — pas de champ téléphone/nom).

### Backend — cas d'usage (`pytest`, fakes de `conftest.py`)

- **`tests/test_campaign_usecase.py`** (nouveau), `FakeCampaignRepository` + fake `CustomerRepository` +
  fake `AuditLog` :
  - **création nominale** : `recipient_count` = valeur renvoyée par `count_for_salon(salon_id,
    filter=<segment>)` (vérifier que le **filtre** correspond au segment demandé et que le `salon_id`
    passé est celui de la portée) ; **1** campagne `PENDING` créée (`created_by = actor_user_id`) ;
    **1** entrée `CAMPAIGN_CREATED` avec `metadata` **non-PII** (pas de message, pas de téléphone).
  - **validation échouée** (titre/message vide, type/segment inconnu) → **0** campagne, **0** audit
    (l'exception précède toute écriture).
  - **atomicité** : campagne et audit passent par le **même** port/`Session` (fakes) ; une erreur du
    dépôt de campagne n'écrit pas d'audit orphelin (et inversement).

### Backend — API (`TestClient` + `app.dependency_overrides`)

- **`tests/test_campaign_api.py`** (nouveau) :
  - `POST` **`201`** : réponse projetée (aucun destinataire, `status = PENDING`, `sent_at = null`) ;
    `salon_id` du chemin ; `created_by` = principal ; corps privilégié (`salon_id`/`created_by`/
    `status`/`recipient_count`) **ignoré**.
  - `422` : `type`/`segment` hors enum, `title`/`message` vide ou trop long.
  - **RBAC/portée** : `CLIENT`, `HAIRDRESSER`, `ADMIN` → `403` ; gérant hors de son salon → `403`
    (générique) ; jeton absent → `401`.
  - *(option)* `GET` liste : non-PII (pas de destinataire), paginée, salon-scopée.
- **`tests/test_security_guards.py`** : `unprotected_routes(app)` **inchangé** ; aucun chemin campagne
  dans `PUBLIC_ROUTE_PATHS` ; matrice RBAC figée (si `CUSTOMER_MANAGE` réutilisé).

### Backend — e2e (PostgreSQL réel, sauté si `DATABASE_URL` absent)

- **`tests/test_campaign_e2e.py`** (nouveau, patron #28/#45–#48 — plage de numéros réservée, nettoyage
  avant/après) : créer un salon + quelques `customer_profiles` (dont au moins une **sans** téléphone),
  poster une campagne, vérifier **1** ligne `campaigns` (`status = PENDING`, `sent_at IS NULL`,
  `salon_id`/`created_by` corrects, `recipient_count` = nombre réel de fiches du segment [selon la règle
  « avec téléphone », Risks §4], `message` = celui soumis, **aucun** téléphone/nom stocké hors du corps
  composé) ; contraintes réelles (FK `RESTRICT`, `CHECK` `type`/`segment`/`channel`/`status`) ; une
  entrée `audit_logs` `CAMPAIGN_CREATED` `metadata` **non-PII** ; **nettoyage** : `campaigns` (et
  `notifications`) supprimés **avant** `customer_profiles`/`appointments`/`users`/`salons` (FK
  `RESTRICT`).

### Documentation / non-régression

`scripts/test-gate.sh` (pytest + npm test **web inchangé** + flutter test **mobile inchangé**) au vert ;
`ruff check` propre ; **round-trip Alembic** (`0009` up/down) vert ; aucune régression sur les fiches
(#28), les notifications RDV (#45–#48) ni les statistiques (#42). Relire la PR pour garantir qu'**aucun**
message, téléphone, nom ni secret n'apparaît dans les logs.

## Documentation Updates

- **`backend/README.md`** — nouvelle section « Campagnes/messages aux clients (US-7.5) » : le gérant
  crée une campagne (`POST /salons/{salon_id}/campaigns`, `CUSTOMER_MANAGE` + portée) d'un **type**
  (`REMINDER`/`PROMOTION`/`EXCEPTIONAL_CLOSURE`) vers un **segment** salon-scopé de son fichier clients
  (#28) ; la campagne est **émise/tracée** (`status = PENDING`, effectif snapshot **non-PII**) dans la
  même transaction que l'audit `CAMPAIGN_CREATED` ; **la remise proactive (fan-out SMS) est différée
  M5+** (ADR-0006) — rien n'est envoyé, `sent_at` reste `NULL`. Migration `0009`.
- **`README.md`** (racine) — §6 : phrase de statut « **M5** : campagnes/messages aux clients (US-7.5,
  #49) — le gérant crée une campagne (rappel/promotion/fermeture) ciblant un segment de ses fiches
  clients, **émise/tracée** dans `campaigns` (effectif non-PII, `PENDING`) ; **remise (fan-out SMS)
  différée** (ADR-0006) », dans le style existant. Épic 7 achevé côté émission/trace.
- **`docs/adr/0037-campagnes-messages-clients.md`** (**nouvel ADR**) : figer (a) la **table dédiée
  `campaigns`** (vs matérialisation par destinataire dans `notifications`) ; (b) le **segment = prédicat
  salon-scopé** sur `customer_profiles` (#28), effectif **snapshot non-PII**, numéros résolus à l'envoi ;
  (c) la **permission** (réutilisation `CUSTOMER_MANAGE` ou `CAMPAIGN_SEND`) ; (d) le **canal SMS** au
  MVP (walk-in) ; (e) l'audit **`CAMPAIGN_CREATED`** neutre ; (f) le périmètre (**remise différée**, pas
  de fan-out, pas d'opt-out, backend-first). Mettre à jour `docs/adr/README.md`.
- **OpenAPI** — docstrings du nouveau router `campaigns.py` (endpoint, RBAC, non-remise, non-PII).

## Risks and Open Questions

1. **Table dédiée `campaigns` vs matérialisation par destinataire dans `notifications`.**
   *Recommandation : table dédiée* — une campagne est un concept **un-à-plusieurs** avec **texte libre**,
   sans RDV ; matérialiser N `notifications` à la création (une par fiche) serait volumineux (§12.1),
   figerait un snapshot de PII (téléphones) et exigerait de toute façon un `campaign_id`/
   `customer_profile_id` (walk-in `user_id NULL` — `notifications.user_id` → `users`, inadapté). Le
   fan-out réel appartient au **worker M5+** (re-résolution du segment à l'envoi). **À trancher dans
   l'ADR-0037.**
2. **Population de destinataires : fiches `customer_profiles` (#28) vs comptes segmentés (#42).**
   *Recommandation : les **fiches** (`customer_profiles`)* — #49 **dépend de #28**, la majorité des
   clients d'un salon y sont walk-in (sans compte), et le canal SMS cible `customer_profiles.phone`.
   La segmentation #42 (`new`/`recurring`/`inactive`) porte sur des **comptes** avec visites `COMPLETED`
   et **exclut** les walk-in : réutilisable comme **vocabulaire**, mais **population différente**. **À
   confirmer.**
3. **Définition du segment : `ALL` seul, `CustomerFilter` (#28/#35), ou segments d'activité (#42) ?**
   *Recommandation : au minimum `ALL`, + réutiliser le `CustomerFilter` existant* (gender, plage de
   dates de création) pour un segment simple, salon-scopé et déjà outillé (`count_for_salon`). Un
   critère « inactif depuis N mois » (via `last_visit_at`/`total_visits` de la fiche) est une extension
   naturelle. La forme de stockage du segment (enum seul, ou enum + `segment_params` JSONB non-PII) est
   à figer. **À trancher.**
4. **Effectif : toutes les fiches du segment, ou seulement celles **avec téléphone** ?** Une fiche
   walk-in **sans** téléphone ne peut recevoir de SMS. *Recommandation : compter (et à terme n'envoyer
   qu'à) les fiches **avec** téléphone* (`phone IS NOT NULL`), pour que `recipient_count` reflète les
   destinataires réellement joignables. Exposer éventuellement les deux (total vs joignables). **À
   confirmer.**
5. **Permission : réutiliser `CUSTOMER_MANAGE` vs nouvelle `CAMPAIGN_SEND`.** *Recommandation :
   réutiliser `CUSTOMER_MANAGE`* (le gérant gère déjà son fichier clients ; aucune modification de la
   matrice §4.1, cohérent avec #28 qui n'a pas élargi la matrice). Alternative plus explicite/auditable :
   ajouter `CAMPAIGN_SEND` (MANAGER) — impose de modifier `ROLE_PERMISSIONS` **et** les tests de matrice.
   **À trancher dans l'ADR-0037.**
6. **Trace : ligne `campaigns` seule vs + audit `CAMPAIGN_CREATED`.** *Recommandation : les deux* —
   contrairement à #45–#48 (effets de bord d'événements RDV déjà audités), une campagne est une **action
   manuelle du gérant** (§11.4) méritant une entrée d'audit **neutre**. Vérifier si `audit_logs.action`
   porte un `CHECK` figé (sinon régénérer, patron `NotificationType`) ou est un `String` libre. **À
   confirmer.**
7. **Statut initial `PENDING` (honnête) & non-remise.** Comme #45–#48, `PENDING` + `sent_at = NULL` ; le
   worker M5+ passera `SENT`/`FAILED`. Ne **pas** marquer `SENT` au MVP (mensonger). **À confirmer.**
8. **Opt-out / consentement marketing (§11.3, #52).** #49 introduit un **envoi marketing** ; l'opt-out
   par client n'existe pas (le consentement est hors code au MVP, ADR-0026). *Recommandation : signaler
   comme **pré-requis au durcissement (#52) avant toute remise réelle M5+*** ; #49 (émission/trace) ne
   diffuse rien, le risque est donc **contenu** au MVP. **À consigner.**
9. **UI web `/gerant` : incluse ou différée ?** #45–#48 sont **backend-only**. *Recommandation :
   backend-first* (l'AC « le gérant envoie » est satisfaite par l'endpoint) ; un formulaire de campagne
   dans la section **Clients**/**Notifications** du dashboard est une extension optionnelle. **À
   confirmer.**
10. **Lecture minimale des campagnes (`GET`).** *Recommandation : oui, minimale et non-PII* (parité #28
    — rend la création observable, sans exposer de destinataire) ; tout rapport de délivrabilité est
    différé (rien n'est remis). **À confirmer.**
11. **ADR dédié.** *Recommandation : oui* — **ADR-0037** figeant table dédiée + segment salon-scopé +
    permission + canal SMS + audit + non-remise. **À confirmer.**

## Implementation Checklist

1. **Vérifier l'état livré & trancher.** Relire le socle notification (#45–#48 :
   `domain/notification.py`, port/adapter), la fiche client (#28 : `domain/customer.py`,
   `SqlCustomerRepository.count_for_salon`/`_filter_clauses`, `adapters/inbound/customers.py`), la
   segmentation (#42 : `domain/client_segments.py`), la matrice RBAC (`domain/permissions.py`), l'audit
   (`domain/audit.py`) et le patron de migration `0008`. **Trancher** les questions 1–11 ; consigner dans
   un **ADR-0037**.
2. **Migration** : créer `0009_campaigns` (`down_revision = "0008"`) — `create_table("campaigns")`
   (colonnes + FK `RESTRICT` `salons`/`users` + `CHECK` dérivés + index `ix_campaigns_salon_id`) ;
   `downgrade` = `drop_table`. Vérifier le **round-trip** sur PostgreSQL 16.
3. **Domaine** : ajouter `CampaignType`/`CampaignSegment`/`CampaignStatus` (`domain/enums.py`) ; créer
   `domain/campaign.py` (`CampaignToCreate`, `Campaign`, validations, `build_campaign`, bornes) ; ajouter
   les erreurs `InvalidCampaign*` (`domain/errors.py`) et `AuditAction.CAMPAIGN_CREATED`
   (`domain/audit.py`). Écrire `tests/test_campaign_domain.py`.
4. **Ports & adapters** : `application/ports/campaign_repository.py` (`CampaignRepository`) ; modèle ORM
   `Campaign` (`models.py`) ; `adapters/outbound/persistence/campaign_repository.py`
   (`SqlCampaignRepository`, `flush` sans commit). (Réutiliser `count_for_salon` #28 ; option
   `phone IS NOT NULL`, Risks §4.)
5. **Cas d'usage** : `application/campaigns.py::CreateCampaign` (valider → résoudre canal SMS → résoudre
   effectif via `count_for_salon` → persister campagne `PENDING` → journaliser `CAMPAIGN_CREATED` neutre,
   **même** `Session`). Étendre `conftest.py` (`FakeCampaignRepository`, fake `CustomerRepository`) et
   écrire `tests/test_campaign_usecase.py`.
6. **Adapter entrant** : `adapters/inbound/campaigns.py` (`POST /salons/{salon_id}/campaigns`,
   `require_salon_scope` + `require_permission(CUSTOMER_MANAGE)`, schémas `extra="ignore"`, mapping
   erreurs → `422`/`403`, `created_by = principal.id`) ; enregistrer le router ; (option) `GET` liste
   non-PII. Écrire `tests/test_campaign_api.py` ; vérifier `tests/test_security_guards.py`.
7. **e2e** : `tests/test_campaign_e2e.py` (création → 1 ligne `campaigns` `PENDING` liée & sans PII de
   destinataire ; effectif réel ; audit `CAMPAIGN_CREATED` neutre ; nettoyage `campaigns`/`notifications`
   avant `customer_profiles`/`appointments`/`users`/`salons`). Exécuter `pytest` (+ `DATABASE_URL`,
   `alembic upgrade head`) et `ruff check`.
8. **Documentation** : section `backend/README.md` ; phrase de statut `README.md` racine (M5) ;
   `docs/adr/0037-campagnes-messages-clients.md` + index `docs/adr/README.md` ; docstrings OpenAPI.
9. **Vérification finale** : `scripts/test-gate.sh` au vert (pytest + npm test **web inchangé** +
   flutter test **mobile inchangé**), `ruff check`, round-trip Alembic (`0009`) vert ; relire la PR pour
   garantir qu'**aucun** message, téléphone, nom ni secret n'apparaît dans les logs ; que la campagne est
   **émise dans la même transaction** que l'audit ; que le segment **et** l'effectif sont **salon-scopés**
   (§11.2) ; que `created_by` vient du **principal** (jamais du corps) ; que **rien n'est réellement
   envoyé** (non-remise assumée, `PENDING`, `sent_at NULL`, ADR-0006) ; que le **périmètre** exclut le
   fan-out, l'ordonnanceur, l'opt-out et l'UI ; et qu'**aucune signature IA** n'a été introduite.
