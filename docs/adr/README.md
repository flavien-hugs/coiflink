# Architecture Decision Records (ADR)

Ce répertoire trace les **décisions d'architecture** de CoifLink. Chaque décision majeure fait
l'objet d'**un fichier ADR** versionné. Le format, la numérotation et les statuts sont définis par
**[ADR-0000](./0000-processus-et-gabarit-adr.md)**.

Les ADR sont la **source de vérité de la stack technique** (cf. README §4 et PRD §10). Une décision
n'est jamais réécrite : on en crée une nouvelle qui remplace l'ancienne (statut
`Remplacé par ADR-XXXX`).

## Index

| ADR | Titre | Statut | Issue |
| --- | --- | --- | --- |
| [0000](./0000-processus-et-gabarit-adr.md) | Processus et gabarit des ADR | Accepté | #1 |
| [0001](./0001-app-mobile-flutter.md) | Application mobile — Flutter | Accepté | #1 |
| [0002](./0002-web-gerant-admin-nextjs.md) | Interface web gérant / admin — Next.js (React) | Accepté | #1 |
| [0003](./0003-backend-fastapi.md) | Backend — FastAPI (API REST + JWT) | Accepté | #1 |
| [0004](./0004-donnees-postgresql-redis.md) | Données — PostgreSQL + Redis | Accepté | #1 |
| [0005](./0005-stockage-objet-s3-compatible.md) | Stockage de fichiers — objet S3-compatible | Accepté | #1 |
| [0006](./0006-notifications-fcm-sms.md) | Notifications — FCM + SMS | Accepté | #1 |
| [0007](./0007-arborescence-monorepo-versions.md) | Arborescence du monorepo, versions de référence & app web unique | Accepté | #2 |
| [0008](./0008-architecture-hexagonale.md) | Architecture hexagonale (ports & adapters) — tous les paquets | Accepté | suite #2 |
| [0009](./0009-orm-migrations-sqlalchemy-alembic.md) | ORM, migrations & driver — SQLAlchemy 2.0 + Alembic + psycopg 3 | Accepté | #3 |
| [0010](./0010-ci-cd-docker-packaging.md) | Pipeline CI/CD applicatif & empaquetage Docker | Accepté | #4 |
| [0011](./0011-deploiement-environnements-secrets.md) | Déploiement, environnements & gestion des secrets | Accepté | #5 |
| [0012](./0012-hachage-argon2-strategie-otp.md) | Hachage de mot de passe (argon2id) & stratégie OTP | Accepté | #8 |
| [0013](./0013-connexion-jwt-refresh-anti-bruteforce.md) | Connexion — bibliothèque JWT, refresh & anti-bruteforce | Accepté | #10 |
| [0014](./0014-reinitialisation-mot-de-passe-otp.md) | Réinitialisation du mot de passe par OTP (SMS ou e-mail) | Accepté | #11 |
| [0015](./0015-autorisation-rbac-deny-by-default.md) | Autorisation & RBAC — deny-by-default, permissions par rôle, isolation par salon | Accepté | #12 |
| [0016](./0016-comptes-employes-appartenance-salon.md) | Comptes employés — appartenance employé↔salon & création par le gérant | Accepté | #13 |
| [0017](./0017-creation-salon-medias-et-reservabilite.md) | Création d'un salon — rattachement au gérant, médias par URL signée & réservabilité | Accepté | #15 |
| [0018](./0018-configuration-horaires-salon.md) | Configuration des horaires d'ouverture — contrat JSONB & activation de la réservabilité | Accepté | #16 |
| [0019](./0019-journalisation-audit-et-prestations.md) | Journalisation d'audit §11.4 (table persistée) & gestion des prestations (soft-delete) | Accepté | #17 |
| [0020](./0020-catalogue-salons-cote-client.md) | Catalogue de salons côté client — ressource publique distincte, filtre `ACTIVE` & projection de vitrine | Accepté | #18 |
| [0021](./0021-consultation-salon-cote-client.md) | Consultation d'un salon côté client — fiche publique de détail, agrégation `ACTIVE`-only & point d'entrée réservation | Accepté | #19 |
| [0022](./0022-modification-informations-salon.md) | Modification des informations du salon — réutilisation du chemin d'écriture #15 & garantie de réflexion côté client sans cache | Accepté | #20 |
| [0023](./0023-moteur-disponibilite-anti-double-reservation.md) | Moteur de disponibilité & anti double-réservation — garantie portée par la contrainte d'exclusion base, moteur pur au-dessus | Accepté | #21 |
| [0024](./0024-reservation-cote-client.md) | Réservation côté client — tunnel mobile & session cliente au-dessus des endpoints #21 | Accepté | #22 |
| [0025](./0025-annulation-rendez-vous-client.md) | Annulation d'un rendez-vous côté client — transition d'état soft, motif optionnel & invariant CA | Accepté | #24 |
| [0026](./0026-fiche-client-portee-salon.md) | Fiche client — portée salon, genre optionnel & unicité du téléphone | Accepté | #28 |
| [0027](./0027-encaissement-coherence-montant.md) | Encaissement — cohérence du montant avec la prestation liée & enregistrement d'un paiement | Accepté | #33 |
| [0028](./0028-detection-ecarts-de-caisse.md) | Détection des écarts de caisse — rapprochement RDV terminés ↔ paiements, en lecture | Accepté | #36 |
| [0029](./0029-supervision-agregee-transactions-admin.md) | Supervision agrégée des transactions (admin) — lecture plateforme `STATS_READ_PLATFORM`, net via `cash_journal`, non-PII | Accepté | #37 |
| [0030](./0030-recu-numerique-remise-differee.md) | Reçu numérique de paiement (client) — projection en lecture `PAYMENT_READ_OWN`, remise proactive différée M5 | Accepté | #38 |
| [0031](./0031-performance-des-coiffeurs.md) | Performance des coiffeurs — lecture `STATS_READ_SALON`, CA net **attribué par RDV** (caisse), émission maîtrisée de l'identité employé | Accepté | #43 |
| [0032](./0032-kpi-globaux-plateforme-admin.md) | KPI globaux plateforme (admin) — instantané consolidé `STATS_READ_PLATFORM`, revenu net via `cash_journal`, report du KPI abonnements (aucun modèle), non-PII renforcée | Accepté | #44 |
| [0033](./0033-notification-confirmation-rdv.md) | Notification de confirmation de RDV — ligne `notifications` persistée atomiquement (émission/trace §8.4/§11.4), canal pur PUSH→SMS→IN_APP, remise proactive différée M5, aucune migration | Accepté | #45 |
| [0034](./0034-rappel-automatique-avant-rdv.md) | Rappel automatique avant RDV — rappels `notifications` datés (`scheduled_for`), annulation liée au cycle de vie du RDV (statut `CANCELLED`), remise proactive différée M5 | Accepté | #46 |
| [0035](./0035-notification-salon-a-la-reservation.md) | Notification au salon à la réservation — ligne `notifications` `NEW_BOOKING`/`IN_APP` persistée atomiquement (émission/trace §8.4/§11.4), destinataire = gérant (`salon.owner_id`), lecture salon-scopée différée, remise email/SMS différée M5 | Accepté | #47 |
| [0036](./0036-notification-annulation-modification.md) | Notification d'annulation/modification de RDV — émission atomique aux parties concernées, `CANCELLATION` réutilisé (client + salon, §8.4, sans migration), type `APPOINTMENT_UPDATE` (migration `0008`) pour les autres changements de statut & la modification, résolution du gérant via `SalonRepository`, lecture & remise différées M5 | Accepté | #48 |
| [0037](./0037-campagnes-messages-clients.md) | Campagnes/messages aux clients — table dédiée `campaigns` (migration `0009`, pas de fan-out dans `notifications`), segment = prédicat salon-scopé sur les fiches (#28) restreint aux fiches joignables SMS, effectif snapshot non-PII (`COUNT`), permission `CUSTOMER_MANAGE` réutilisée, audit `CAMPAIGN_CREATED` neutre, remise différée M5 | Accepté | #49 |
| [0038](./0038-observabilite-monitoring-rollback.md) | Mise en production — observabilité (monitoring/alerting native Railway + sonde de disponibilité externe visant 99 %), alerting non-PII, stratégie de rollback (app + arbre de décision base), liveness-only (readiness différée), suivi d'erreurs applicatif différé/optionnel | Accepté | #54 |
| [0039](./0039-dashboard-manager-activite-salon.md) | Dashboard Manager — activité du salon — « en cours » dérivé (`slot @> now`, sans statut ni migration), « en attente » = `PENDING`, filtre de période + évolution consolidés, graphiques SVG sans dépendance, auto-refresh polling visibility-aware (aucun websocket/SSE), timeline/alertes dérivées des faits horodatés | Accepté | #148 |

## Décisions volontairement différées (non bloquantes pour M1)

Ces points ne sont **pas** des décisions de stack majeures ouvertes ; ils sont rattachés à une issue
ultérieure et signalés en *Conséquences* des ADR concernés :

- **Plateforme d'hébergement & région des données** — **tranchée par
  [ADR-0011](./0011-deploiement-environnements-secrets.md)** (#5 : Railway, région `europe-west4`) ;
  la partie **CI/CD GitHub Actions & empaquetage Docker** l'avait été par
  [ADR-0010](./0010-ci-cd-docker-packaging.md) (#4). Le **registre d'images** est tranché par
  ADR-0011 (deploy-from-source ; push GHCR différé, optionnel).
- **Fournisseur SMS concret** (agrégateur local) — **reste différé** (opérationnel, M5) ; la surface
  de secrets est documentée par ADR-0011, voir ADR-0006.
- **Fournisseur de stockage objet** (AWS S3 / MinIO / R2 / bucket plateforme) — **provisionnement
  désormais actif depuis #15** (première feature d'upload M2 — création de salon, médias par URL
  signée) ; la configuration S3/MinIO (variables `S3_*` / `MEDIA_*`) est décrite dans
  `docs/environnements-et-secrets.md` ; voir ADR-0005 et
  [ADR-0017](./0017-creation-salon-medias-et-reservabilite.md).
- **Sauvegardes automatiques** (§10.2, §12.2) — **tranchées par ADR-0011** (#5 : quotidiennes,
  rétention 7 j, restauration testée), voir ADR-0004. La **mise en service `production`**,
  l'**activation** et la **vérification** de ces sauvegardes (test de restauration, RPO/RTO consignés)
  sont **exécutées et documentées par #54** — voir
  [ADR-0038](./0038-observabilite-monitoring-rollback.md) et
  [`docs/mise-en-production.md`](../mise-en-production.md).
- **Monitoring & alerting** (§12.2 : monitoring des services critiques, alertes en cas d'incident,
  disponibilité ≥ 99 %) et **stratégie de rollback** — **tranchés par
  [ADR-0038](./0038-observabilite-monitoring-rollback.md)** (#54 : observabilité native Railway + sonde
  de disponibilité externe, alerting non-PII, rollback manuel documenté app + base, **liveness-only** au
  MVP — readiness dédiée différée). Le **suivi d'erreurs applicatif** (Sentry ou équivalent) reste
  **différé/optionnel** (non câblé, surface documentée sans l'impliquer).
- **ORM + migrations** — **tranché par [ADR-0009](./0009-orm-migrations-sqlalchemy-alembic.md)** (#3 :
  SQLAlchemy 2.0 + Alembic + psycopg 3, PostgreSQL 16).
- **Lib de hachage de mot de passe** — **tranchée par [ADR-0012](./0012-hachage-argon2-strategie-otp.md)**
  (#8 : argon2id via `argon2-cffi`), fermant le « Suivi » d'ADR-0003 côté hachage.
- **Runner de tâches async** — voir ADR-0003 (différé). La **lib JWT** (émission de jetons) est
  **tranchée par [ADR-0013](./0013-connexion-jwt-refresh-anti-bruteforce.md)** (#10 : PyJWT, HS256 +
  refresh rotaté + anti-bruteforce en mémoire), fermant le « Suivi » d'ADR-0003 côté JWT.
- **Versions de référence** (Flutter/Dart, Python, PostgreSQL, Redis, Node) — **arrêtées en #2**, voir
  [ADR-0007](./0007-arborescence-monorepo-versions.md).
- **Store OTP persistant/partagé & invalidation immédiate des jetons** — signalés en *Conséquences*
  d'[ADR-0014](./0014-reinitialisation-mot-de-passe-otp.md) (#11) : le dépôt OTP de reset reste **en
  mémoire** (Redis à TTL différé, risque multi-instances documenté). Le **canal e-mail réel** reste
  différé M5 (ADR-0006 à compléter — pas d'e-mail transactionnel à ce jour).
  **Reformulé par [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (#12)** : la relecture du
  rôle et du statut **en base** à chaque requête protégée couvre désormais la **suspension** d'un
  compte (effet immédiat, sans attendre l'expiration du jeton). Reste **ouverte** la seule
  invalidation des jetons **après changement de mot de passe** (`password_changed_at` /
  `token_version` + migration) — point d'accroche identifié : `get_current_principal`.
- **Autorisation & RBAC** — **tranchée par [ADR-0015](./0015-autorisation-rbac-deny-by-default.md)**
  (#12 : gardes en dépendances FastAPI, deny-by-default par liste blanche testée, rôle **relu en
  base**, `403` uniforme sur l'accès inter-salons). Deux suivis en découlent :
  - **table d'appartenance employé↔salon** → **livrée par #13**
    ([ADR-0016](./0016-comptes-employes-appartenance-salon.md)) : la table `salon_members` (migration
    `0002`) est désormais la source d'autorité de la portée d'un `HAIRDRESSER` — la lecture
    `SqlSalonScopeRepository` a **remplacé** la dérivation par RDV assignés, **sans** changer le port
    ni les gardes ;
  - **index `ix_salons_owner_id`** → **#15** (première migration touchant les salons) : #12
    n'introduit **aucune** migration.
- **Journalisation d'audit** (PRD §11.4) — la **table `audit_logs`** (mécanisme de persistance) est
  **établie par #17** ([ADR-0019](./0019-journalisation-audit-et-prestations.md)) et journalise les
  mutations de prestations (`SERVICE_CREATED`, `SERVICE_UPDATED`, `SERVICE_DEACTIVATED`). **Étendue par
  #28** ([ADR-0026](./0026-fiche-client-portee-salon.md)) à la **création d'une fiche client**
  (`CUSTOMER_CREATED`, entité `customer`) — journalisée non pas au titre de la liste §11.4 mais de
  **§11.3** (« journalisation des accès sensibles » : créer une fiche est une collecte de PII), avec des
  `metadata` **vides** (ni nom, ni téléphone, ni genre, ni note). La
  journalisation des **refus d'accès** (log de sécurité) reste **rattachée à #52** et peut réutiliser
  la même table via le port `AuditLog`. ADR-0015 pose le cadre : un éventuel log de refus ne contient
  **que** `user_id` (UUID), `role`, méthode + chemin et décision — **jamais** de jeton, mot de passe,
  téléphone, e-mail ou nom.
