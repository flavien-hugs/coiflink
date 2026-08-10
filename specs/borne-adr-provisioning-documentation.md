# ADR, documentation & procédure de provisioning borne (US-8.7)

> Spécification de planification pour l'issue GitHub **#161 — US-8.7 : ADR, documentation &
> procédure de provisioning borne** (`docs` `infra` · Should · Effort S · PRD §17 « Borne
> Intelligente d'Accueil »), dernière issue du jalon **M7 — Borne client (kiosque libre-service)**,
> Épic 8. **Dépend de : #155, #156, #157, #158, #159, #160.** **Cette spec ne produit pas de
> code** : elle décrit l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires
> Dart/Python/TypeScript), en-têtes de section en **anglais** (attendus par le gabarit ADW),
> identifiants techniques (noms de routes, champs JSON, symboles, valeurs d'enum SQL) inchangés.
> **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le jalon M7 introduit deux décisions d'architecture structurantes — un nouveau modèle
d'authentification par device (#155) et un nouveau domaine `QueueTicket` indépendant
d'`Appointment` (#157) — ainsi qu'un objet physique (une tablette en boîtier kiosque) qui doit être
associé à un salon, sorti de son mode verrouillé pour maintenance, puis révoqué si perdu ou volé.
Aucun de ces trois besoins n'est aujourd'hui couvert par la documentation du dépôt :

- **Aucun ADR ne couvre encore un modèle d'authentification « device ».** Le dépôt compte
  aujourd'hui 41 ADR (`docs/adr/0000-processus-et-gabarit-adr.md` à
  `docs/adr/0040-impression-recu-encaissement-gerant.md`, vérifié par `ls docs/adr/`) ; le
  prochain numéro libre est **`0041`**. L'ADR la plus proche par le sujet est
  [ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default), qui ne
  couvre que des comptes personnels (`Role.CLIENT/HAIRDRESSER/MANAGER/ADMIN`,
  `backend/coiflink_api/domain/enums.py:31-37`) authentifiés par JWT bearer
  (`JwtTokenService.issue_pair`, `backend/coiflink_api/adapters/outbound/security/jwt_token_service.py:44-45,62`
  — `access_ttl` 15 min, `refresh_ttl` 30 jours). Aucun mécanisme de jeton « longue durée par
  salon », de clé API ou de compte « device » n'existe : #155 introduit ce mécanisme et porte
  l'ADR correspondante (`docs/adr/0041-authentification-borne-kiosque.md`, committée avec sa PR
  d'implémentation, cf. `specs/borne-role-authentification-kiosque.md` — « ADR requise, même
  exigence que l'anti-oracle ADR-0026 », texte de l'issue #155 dans `BACKLOG.md:427-435`) ; #161
  en vérifie la présence et la complétude en fin de jalon.
- **Aucun ADR ne couvre encore l'architecture `QueueTicket`.** La file d'attente existante
  (PR #152, [ADR-0039](../docs/adr/0039-dashboard-manager-activite-salon.md)) est **dérivée
  d'`Appointment`** : `domain/queue.py` définit `QUEUE_APPOINTMENT_STATUSES` (statuts retenus parmi
  ceux d'un rendez-vous planifié) et `derive_queue_status` à partir de `arrived_at`/`started_at`
  (colonnes ajoutées à `appointments` par la migration `0011`,
  `backend/migrations/versions/0011_employee_profile_and_appointment_pointage.py`) — il n'existe
  ni table, ni colonne de numéro de passage, ni notion d'ETA nulle part dans le schéma actuel
  (confirmé par grep négatif sur « ticket »/« estimated »/« queue_number » dans `backend/`). #157
  introduit un domaine entièrement nouveau, rendu visible au gérant par fusion **en lecture** dans
  `GET /salons/{salon_id}/queue` (objet `{appointments, walk_in_tickets}`), sans jamais écrire dans
  `appointments` : c'est une décision de modélisation qui mérite d'être actée, pas simplement
  déduite de l'implémentation — elle l'est par `docs/adr/0042-file-attente-walkin-queue-ticket.md`,
  committée avec la PR d'implémentation de #157 (cf. `specs/borne-ticket-file-attente-walkin.md`).
- **Aucune procédure de provisioning n'existe pour un terminal physique.** Le dépôt documente déjà
  des runbooks opérationnels autonomes — `docs/environnements-et-secrets.md` (gestion des secrets
  par environnement) et `docs/mise-en-production.md` (mise en service `production`, monitoring,
  sauvegardes, rollback, issue #54) — mais aucun des deux, ni aucun autre fichier de `docs/`, ne
  couvre l'association d'un device physique à un salon, la sortie d'un mode kiosque verrouillé, ou
  la révocation d'un terminal perdu. Le seul flux d'émission de credential à un tiers du dépôt est
  l'onboarding employé (#13, `specs/creation-invitation-comptes-employes.md:405-408` — création
  directe avec mot de passe temporaire, un **vrai** flux d'invitation par jeton étant documenté comme
  évolution non livrée) : il n'y a donc pas non plus de patron « invitation/provisioning par jeton »
  déjà éprouvé dans le dépôt sur lequel #161 pourrait s'appuyer sans le documenter de zéro.
- **`BACKLOG.md` et `prd-coiflink.md` ne reflètent pas encore la clôture du jalon.** `BACKLOG.md`
  liste aujourd'hui #155 à #161 comme un jalon actif, sans aucune mention « Livré » ni lien de PR
  (vérifié par lecture de `BACKLOG.md:408-487`) — à la différence des items déjà clos du dépôt
  (`BACKLOG.md:141-147` « Prestations · Illustration téléversable », `BACKLOG.md:327-343` #148/« PR
  #152 »), qui suivent tous un même gabarit `· **Livré**` + `*Livré via :*`. `prd-coiflink.md §17`
  décrit encore la version originale de la borne (identification par téléphone **ou QR code ou code
  de réservation ou nom**, vérification de rendez-vous existant, ticket **numérique + SMS/WhatsApp**,
  paiement autonome en « Version future » — `prd-coiflink.md:1290-1346`) sans aucune note renvoyant
  au sous-ensemble effectivement livré par M7 ; seul `BACKLOG.md:497-501` porte aujourd'hui la
  mention de la promotion du sous-ensemble walk-in.

Le gap que #161 comble : **(1)** la **vérification de présence et de complétude des deux ADR du
jalon** — **ADR-0041** (authentification borne, committée avec la PR de #155) et **ADR-0042**
(architecture `QueueTicket`, committée avec la PR de #157) —, en les écrivant à ce stade si elles
manquent encore, et la mise à jour de l'index `docs/adr/README.md` pour les deux ; **(2)** un
**document opérationnel autonome** de provisioning/sortie de mode kiosque/révocation, dans le style
des runbooks déjà présents ; **(3)** la **mise à jour de `BACKLOG.md` et `prd-coiflink.md`** une
fois le jalon effectivement livré (PR mergées de #155 à #160).

## Goals

- **Garantir deux ADR distinctes actant les deux décisions structurantes de M7** :
  `docs/adr/0041-authentification-borne-kiosque.md` pour le modèle d'authentification borne (rôle
  `KIOSK`, credential device longue durée, permissions minimales — décisions de #155) et
  `docs/adr/0042-file-attente-walkin-queue-ticket.md` pour l'architecture `QueueTicket` (entité
  indépendante d'`Appointment`, formule d'ETA V1, fusion en lecture dans la file gérant —
  décisions de #157). Une décision = une ADR, chacune committée avec la PR de la fonctionnalité
  qu'elle acte, conformément à la pratique du dépôt (ADR-0039 livrée avec #148, ADR-0040 avec
  #154) ; #161 vérifie leur présence et leur complétude, et les écrit à ce stade si elles manquent
  encore.
- **Documenter une procédure de provisioning vérifiable**, couvrant l'association d'un device neuf
  à un salon, le stockage du credential côté terminal, la sortie du mode kiosque par PIN gérant pour
  maintenance/mise à jour, et la révocation d'un device perdu ou volé — chaque étape référençant les
  mécanismes concrets livrés par #155/#159 (pas des mécanismes inventés par #161).
- **Ne pas rejouer les décisions déjà actées par #155-#160.** #161 **consolide et documente** ; il
  ne réouvre, ne modifie ni ne réécrit aucune décision technique déjà prise par les specs/PR des
  issues précédentes du jalon (cohérent avec le principe « une décision ne se réécrit jamais »,
  `docs/adr/README.md:8-9`).
- **Mettre à jour `docs/adr/README.md`** (table d'index) avec les entrées des ADR-0041 et
  ADR-0042, dans le même format que les 41 lignes existantes.
- **Préparer, sans l'exécuter par anticipation, la mise à jour de `BACKLOG.md` et
  `prd-coiflink.md`** qui n'aura lieu que lorsque le jalon M7 sera **effectivement livré** (toutes
  les PR de #155 à #160 mergées sur `main`) — #161 documente le contenu exact de cette mise à jour
  dans sa propre spec, pour qu'elle soit appliquée mécaniquement en fin de jalon plutôt
  qu'improvisée.
- **Couverture de vérification adaptée à une issue documentaire** : pas de tests automatisés
  (aucun code produit), mais une procédure de provisioning **vérifiée sur au moins un device
  physique** — c'est le critère d'acceptation explicite de #161 (`BACKLOG.md:485-486`).

## Non-Goals

- **Rejalonner ou réécrire les décisions techniques de #155/#156/#157/#158/#159/#160.** #161 ne
  spécifie ni le schéma des tables, ni les endpoints, ni les écrans Flutter : il **documente** des
  décisions prises et implémentées par ces issues, sur la base de leurs propres specs et PR.
- **Vérification/check-in d'un rendez-vous existant depuis la borne**, **identification par QR code
  ou code de réservation** (PRD §17.3), **affichage temps réel des coiffeurs disponibles avant
  affectation**, **paiement autonome sur la borne** (« Version future » du PRD lui-même) — ces
  quatre points restent **hors scope de M7 dans son ensemble** (pas seulement de #161) ; #161 les
  mentionne dans les ADR-0041/0042 et dans la mise à jour du PRD comme différés, mais ne les
  traite pas.
- **Développer un outil de gestion de flotte de devices (MDM tiers).** La décision retenue pour M7
  est l'Android Lock Task Mode natif, pas un MDM payant (décision assumée en amont, à documenter
  dans l'ADR-0041, pas à réévaluer par #161).
- **Écrire ou modifier du code applicatif.** #161 ne touche ni `backend/`, ni `web-dashboard/`, ni
  `app-mobile/` — uniquement `docs/adr/`, un nouveau document opérationnel sous `docs/`, et
  (une fois le jalon livré) `BACKLOG.md`/`prd-coiflink.md`.
- **Exécuter la mise à jour `BACKLOG.md`/`prd-coiflink.md` avant que M7 soit livré.** Documenter le
  contenu exact de cette mise à jour fait partie du périmètre de #161 (livrable de spec) ; l'**exécuter**
  reste conditionné à la fusion effective des PR #155-#160, comme pour tout item déjà « Livré » du
  backlog (`BACKLOG.md:141-147`, `:327-343`) — #161 elle-même sera marquée « Livré » séparément une
  fois sa propre PR (ADR + doc de provisioning) mergée, indépendamment de cette mise à jour finale.

## Relevant Repository Context

### Stack & architecture (rappel, inchangées par #161)

| Couche | Décision | ADR |
| --- | --- | --- |
| Backend | Python ≥ 3.12 · FastAPI · REST · JWT | [0003](../docs/adr/0003-backend-fastapi.md) |
| Autorisation | RBAC deny-by-default, permissions §4.1, portée salon §11.2 | [0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md) |
| Fiche client & anti-oracle | Pas de recherche `users` par téléphone (ADR-0026) | [0026](../docs/adr/0026-fiche-client-portee-salon.md) |
| File d'attente gérant existante | Dérivée d'`Appointment` (`arrived_at`/`started_at`) | [0039](../docs/adr/0039-dashboard-manager-activite-salon.md) |
| Déploiement/exploitation | Runbooks opérationnels autonomes sous `docs/` | [0011](../docs/adr/0011-deploiement-environnements-secrets.md), [0038](../docs/adr/0038-observabilite-monitoring-rollback.md) |

`docs/adr/` compte aujourd'hui **41 fichiers** (`0000` à `0040` inclus, vérifié par
`ls docs/adr/*.md | sort`) : les **deux prochains numéros libres sont `0041` et `0042`**.

### Style à reproduire — ADR proches par le sujet

- **[ADR-0026](../docs/adr/0026-fiche-client-portee-salon.md)** (fiche client, portée salon) —
  gabarit d'en-tête (Statut/Date/Décideurs/Issue/Référence PRD/S'appuie sur), section « Décision »
  en points numérotés, chacun justifié par un « pourquoi » avant le « quoi », section
  « Conséquences » scindée Positives/Négatives-suivis. C'est l'ADR la plus proche pour la partie
  « anti-oracle » de #161 (elle documente déjà pourquoi interroger `users` par téléphone est un
  oracle d'existence de compte — #155/#156 doivent expliciter en quoi la recherche de
  `CustomerProfile` par téléphone depuis un terminal **public partagé** est un risque **différent**,
  pas un contournement de la même règle).
- **[ADR-0040](../docs/adr/0040-impression-recu-encaissement-gerant.md)** (impression du reçu) —
  ADR la plus récente (2026-08-10), rédigée pour une PR déjà mergée (#150-154, « ad hoc — aucune
  issue GitHub créée en amont ») avec des sections « Décision » très concrètes (numéros de section
  `### 1.` à `### 6.`, chacune citant fichier/ligne du mécanisme retenu) : bon gabarit pour le
  niveau de précision attendu, y compris la façon dont elle assume des compromis (§« Conséquences »
  → « Compromis assumé »).
- **[ADR-0015](../docs/adr/0015-autorisation-rbac-deny-by-default.md)** — à relire pour le
  vocabulaire RBAC exact (`Permission`, `ROLE_PERMISSIONS`, `require_permission`,
  `require_salon_scope`) que l'ADR-0041 doit réutiliser sans le redéfinir.

### RBAC & authentification actuels (contexte pour l'ADR-0041, #155)

- `Role` est une énumération **fermée** à 4 valeurs (`backend/coiflink_api/domain/enums.py:31-37` :
  `CLIENT`, `HAIRDRESSER`, `MANAGER`, `ADMIN`).
- `ROLE_PERMISSIONS` (`backend/coiflink_api/domain/permissions.py:84-139`) est un dictionnaire
  **fermé et exhaustif** — le commentaire d'en-tête (`permissions.py:11-13`) énonce explicitement
  « deny-by-default jusque dans le domaine : un rôle absent de la table n'a aucune permission ».
  `Permission.CUSTOMER_MANAGE` (ligne 65) n'est détenue que par `MANAGER` (ligne 121) ;
  `Permission.APPOINTMENT_BOOK` (ligne 54) que par `CLIENT` (ligne 92) — aucun rôle actuel ne cumule
  les deux, ce qui est précisément le constat qui motive #155 (« aucun rôle existant ne convient à
  un terminal public partagé »).
- L'authentification personnelle passe par `JwtTokenService.issue_pair`
  (`backend/coiflink_api/adapters/outbound/security/jwt_token_service.py:62-72`), avec
  `access_ttl=15 min` / `refresh_ttl=30 jours` (lignes 44-45) — un jeton **par utilisateur**, jamais
  par salon ni par terminal. `adapters/inbound/security.py:104-135` (`PUBLIC_ROUTE_PATHS`) et
  `:325-` (`require_authenticated`) portent l'invariant deny-by-default vérifié mécaniquement par
  `unprotected_routes(app)` (mentionné dans le docstring de `security.py:20-24`).
- Ces éléments ne sont **pas modifiés par #161** ; ils forment le **contexte** que l'ADR-0041 doit
  citer pour justifier pourquoi un rôle `KIOSK` et un credential device sont une extension nécessaire
  plutôt qu'une réutilisation détournée d'un rôle existant.

### File d'attente existante (contexte pour l'ADR-0042, #157)

- `backend/coiflink_api/domain/queue.py` : `QUEUE_APPOINTMENT_STATUSES` (statuts d'`Appointment`
  retenus pour la file, `CONFIRMED`/`COMPLETED`, jamais `PENDING`) et `derive_queue_status` — dérivée
  uniquement de `arrived_at`/`started_at` et du statut de paiement, **aucun** calcul de position ou
  d'ETA.
- Migration `0011` (`backend/migrations/versions/0011_employee_profile_and_appointment_pointage.py`)
  a ajouté `appointments.arrived_at`/`appointments.started_at` (`TIMESTAMPTZ`) — **aucune** colonne
  de numéro de passage n'existe sur `appointments`, ni ailleurs au schéma.
  `Appointment` (`adapters/outbound/persistence/models.py:298-338`, à re-confirmer par lecture au
  moment de rédiger l'ADR si le schéma a bougé) ne porte ni compteur ni horodatage d'émission de
  ticket.
- Le tri de la file gérant est purement chronologique sur `start_time`
  (`adapters/outbound/persistence/appointment_repository.py`, `order_by start_time.asc(), id.asc()`,
  à revérifier ligne exacte en implémentation) — **aucun** compteur séquentiel n'existe dans le
  dépôt à ce jour.
- Le seul précédent de « compteur séquentiel par salon » du dépôt est `payments.receipt_number`
  (migration `0012`, [ADR-0040](../docs/adr/0040-impression-recu-encaissement-gerant.md) §1) —
  alloué atomiquement via un verrou consultatif transactionnel `pg_advisory_xact_lock`. C'est le
  patron le plus proche que #157 devra probablement suivre ou expliciter pourquoi il s'en écarte
  (un ticket walk-in n'est pas un paiement : la fenêtre de concurrence et la fréquence d'émission
  diffèrent) — point à traiter par la **spec de #157**, mais que l'ADR-0042 doit au moins mentionner
  comme précédent connu.

### Runbooks opérationnels existants (patron pour le document de provisioning)

- `docs/mise-en-production.md` : en-tête avec citation des ADR de socle, avertissement
  « invariant non négociable » (aucun secret committé/journalisé), sommaire numéroté, sections
  numérotées avec étapes **idempotentes**, un § « Vérifications finales (critères d'acceptation) »
  correspondant explicitement aux critères de l'issue documentée. C'est le gabarit le plus proche du
  document que #161 doit produire pour le provisioning borne.
- `docs/environnements-et-secrets.md` : gabarit pour la partie « où vit le secret » (variables
  d'environnement vs magasin de secrets de la plateforme) — utile pour documenter où le credential
  device (#155) doit être stocké côté serveur (jamais en clair, jamais loggé) en miroir de
  `JWT_SECRET`.
- Aucun des deux fichiers existants ne traite d'un terminal physique ni d'un flux d'association
  device↔salon : #161 crée un **troisième** document dédié plutôt que de surcharger l'un des deux
  (séparation par audience — l'un s'adresse à un opérateur infra, l'autre à un gérant de salon).

### Flux d'émission de credential déjà documenté (contexte, pas un patron à copier tel quel)

- `specs/creation-invitation-comptes-employes.md:60,134,387,405-408` : l'« invitation » d'un
  employé (#13) a été tranchée en **création directe** avec mot de passe temporaire, un **vrai**
  flux par jeton à usage unique étant explicitement noté comme **évolution non livrée**. Il n'existe
  donc **aucun** mécanisme de jeton d'invitation à usage unique déjà implémenté dans le dépôt sur
  lequel #161 pourrait s'appuyer : la procédure de provisioning de #161 doit décrire un flux
  **cohérent avec les mécanismes que #155 aura réellement livrés** (à vérifier au moment de la
  rédaction de l'ADR — voir *Risks and Open Questions*), pas un flux générique emprunté à #13.

### Gabarit `BACKLOG.md` pour un item « Livré »

Deux variantes déjà utilisées, vérifiées par lecture directe :

- Item déjà numéroté au backlog (`BACKLOG.md:327-334`, #148) : le titre gagne le suffixe
  `· **Livré**`, le corps et la ligne `*Dépend de :*` restent inchangés, une ligne
  `*Livré via :* #149 (mergé sur main), [ADR-0039](./docs/adr/0039-dashboard-manager-activite-salon.md).`
  est ajoutée **après** `*Dépend de :*`.
- Item ad hoc sans issue préexistante (`BACKLOG.md:141-147`, `:336-343`) : titre sans numéro `#`
  suivi de `· **Livré**`, une ligne `*Livré via :* [PR #151](https://github.com/flavien-hugs/coiflink/pull/151) (mergée sur main).`
  Ce deuxième gabarit **ne s'applique pas** à #155-#161, qui sont des issues déjà numérotées dans
  `BACKLOG.md` — c'est le premier gabarit (variante #148) qui s'applique.

### Section PRD à mettre à jour

`prd-coiflink.md:1271-1363` (§17, « Borne Intelligente d'Accueil ») décrit encore la version
**complète** de la borne (identification par téléphone/QR/code/nom, vérification de rendez-vous
existant, ticket **numérique** + SMS/WhatsApp, paiement autonome). `BACKLOG.md:497-501` porte déjà
une note de renvoi vers M7 dans la section « Hors périmètre MVP », mais **le PRD lui-même
(§17.3/§17.4) ne porte encore aucune annotation** indiquant quel sous-ensemble a été effectivement
livré ni sous quelle forme (ticket **papier**, pas numérique + SMS/WhatsApp) : c'est l'écart que
#161 doit combler une fois M7 livré.

## Proposed Implementation

### (A) ADR-0041 & ADR-0042 — plan détaillé

Deux fichiers : `docs/adr/0041-authentification-borne-kiosque.md` (committée avec la PR
d'implémentation de #155) et `docs/adr/0042-file-attente-walkin-queue-ticket.md` (committée avec
la PR de #157) — numéros suivants confirmés ci-dessus. #161 vérifie leur présence et leur
complétude, et les écrit à ce stade si elles manquent encore. Gabarit ADR-0000
(`docs/adr/0000-processus-et-gabarit-adr.md`), calibré sur le niveau de détail
d'ADR-0026/ADR-0040 :

**En-tête** (commun aux deux ADR)
- Statut : Accepté (chaque ADR est rédigée avec l'implémentation qu'elle acte, comme ADR-0039
  livrée avec #148 et ADR-0040 avec #154 : elle documente une PR réelle, pas une spec pas encore
  codée).
- Décideurs : équipe CoifLink.
- Issue : #155 (US-8.1) pour l'ADR-0041, #157 (US-8.3) pour l'ADR-0042 — #161 (ADR, documentation
  & procédure de provisioning borne) vérifie leur présence et leur complétude.
- Référence PRD : §17 (« Borne Intelligente d'Accueil », en particulier §17.1/§17.2/§17.3), Risque 5
  (« lancer d'abord sans borne », « tester sur 2-3 salons pilotes »), §11.1/§11.2/§11.3 (auth,
  isolation salon, PII).
- S'appuie sur : ADR-0008 (hexagonal), ADR-0009 (migrations), ADR-0013 (JWT), ADR-0015 (RBAC
  deny-by-default), ADR-0026 (anti-oracle `CustomerProfile`/`users`), ADR-0039 (file d'attente
  existante dérivée d'`Appointment`).

**Contexte et problème** — reprendre la synthèse de la section *Problem Statement* ci-dessus :
aucun rôle existant ne convient à un terminal public partagé (§4.1 séparant `CUSTOMER_MANAGE` et
`APPOINTMENT_BOOK`) ; la file d'attente existante (#152/ADR-0039) est dérivée d'`Appointment` et ne
porte ni numéro de passage ni ETA.

**Décision** — points numérotés répartis entre les deux ADR (points 1-2 pour l'ADR-0041, points
3-5 pour l'ADR-0042), chacun **résumant** (pas réinventant) les choix effectivement retenus et
implémentés par #155 et #157 :

1. **Authentification borne (#155).** Nouveau rôle `KIOSK` scopé à un salon, distinct des 4 rôles
   personnels existants ; nouveau credential device longue durée (mécanisme exact — jeton signé
   dédié, clé API opaque, ou autre — **à confirmer au moment de la rédaction, une fois #155
   implémentée**, voir *Risks and Open Questions* §1) ; permissions minimales et dédiées
   (catalogue en lecture, recherche téléphone restreinte à `CustomerProfile`, création de ticket
   walk-in) sans jamais accorder `CUSTOMER_MANAGE` ni `APPOINTMENT_BOOK` complets — la matrice
   `ROLE_PERMISSIONS` reste fermée et auditable (ADR-0015).
2. **Anti-oracle appliqué à un terminal public partagé, au-delà d'ADR-0026.** ADR-0026 interdit
   déjà d'interroger `users` par téléphone (oracle d'existence de compte). #155/#156 étendent la
   vigilance à un risque **différent** : `CustomerProfile` n'a ni mot de passe ni compte, donc
   aucune attaque par force brute de compte n'est possible, mais le terminal est **physiquement
   partagé** dans un lieu public — afficher un nom complet associé à un numéro de téléphone sur un
   écran visible de la file d'attente est une exposition de PII (§11.3). Décision : n'afficher que
   le **prénom** côté écran borne, et limiter le débit de tentatives de recherche par téléphone
   (mécanisme exact à confirmer une fois #156 implémentée).
3. **Architecture `QueueTicket` (#157).** Nouveau domaine indépendant d'`Appointment` (pas de
   détournement de créneaux planifiés existants) : numéro séquentiel par salon/jour, statut, heure
   d'émission, estimation d'attente (formule V1 : position dans la file × durée moyenne des
   prestations des tickets en attente et en cours ÷ coiffeuses actives, avec les replis documentés
   par #157). Visibilité gérant assurée par fusion **en lecture** dans
   `GET /salons/{salon_id}/queue` (objet `{appointments, walk_in_tickets}`, tickets du jour
   `waiting`/`called`/`in_progress`/`done`), sans jamais écrire dans `appointments` — la file
   planifiée (#152/ADR-0039) n'est ni dupliquée ni modifiée.
4. **Numérotation séquentielle — précédent `receipt_number` (ADR-0040) suivi ou explicitement
   écarté.** L'ADR doit indiquer si `QueueTicket.ticket_number` réutilise le même patron de verrou
   consultatif transactionnel par salon que `payments.receipt_number`, ou une méthode différente
   (fréquence d'émission et fenêtre de concurrence différentes d'un paiement) — décision déjà prise
   par l'implémentation de #157 au moment où l'ADR-0042 est rédigée ; l'ADR la **documente**, ne la
   tranche pas a priori.
5. **Aucune régression sur la file des rendez-vous planifiés.** `QUEUE_APPOINTMENT_STATUSES` et
   `derive_queue_status` (`domain/queue.py`) restent le mécanisme de la file **planifiée** ; la
   fusion en lecture n'altère ni leur signature ni leur comportement, et aucune ligne
   `appointments` n'est jamais créée ou modifiée par un ticket walk-in.

**Conséquences** — Positives (un terminal public a un scope d'accès minimal et auditable ; le
ticket walk-in ne pollue pas le modèle `Appointment` ; la file gérant existante reste la source
unique de vérité pour l'affichage, #152 n'est pas dupliqué) ; Négatives/suivis (la formule d'ETA V1
est une heuristique perfectible, sans données historiques — à réévaluer après un pilote 2-3 salons,
en écho direct au Risque 5 du PRD ; le rôle `KIOSK` ajoute un 5ᵉ élément à une énumération `Role`
jusqu'ici fermée à 4 valeurs — vérifier explicitement qu'aucun test d'invariant de #12/#15 ne fige
« exactement 4 rôles » d'une manière qui casserait silencieusement ailleurs).

### (B) `docs/adr/README.md` — mise à jour de l'index

Ajouter deux lignes à la table (`docs/adr/README.md:11-55`), immédiatement après la ligne `0040`,
au même format que les 41 lignes existantes :

```markdown
| [0041](./0041-authentification-borne-kiosque.md) | Authentification borne kiosque (rôle KIOSK, credential device) | Accepté | #155 |
| [0042](./0042-file-attente-walkin-queue-ticket.md) | File d'attente walk-in (QueueTicket, ETA, fusion en lecture) | Accepté | #157 |
```

Le libellé exact de la colonne « Titre » sera affiné lors de la rédaction réelle de chaque ADR
(une fois #155/#157 implémentées et leur contenu définitif connu), en cohérence avec les titres
denses déjà utilisés pour ADR-0039/ADR-0040.

### (C) Nouveau document opérationnel — procédure de provisioning

Nouveau fichier `docs/provisioning-borne-kiosque.md`, gabarit `docs/mise-en-production.md` (en-tête
citant l'ADR-0041 et les issues #155/#159/#160, avertissement PII/secrets, sommaire numéroté,
étapes idempotentes, section finale de vérification des critères d'acceptation de #161). Plan :

1. **Portée et prérequis** — rappel : un device = une tablette Android en boîtier kiosque, liée à
   **un seul salon** de façon durable (décision « borne mono-salon », `salon_id` figé à
   l'installation, pas de sélection de salon à l'écran). Prérequis : compte `MANAGER` actif du
   salon concerné, accès physique au device.
2. **Association d'un device neuf à un salon (« provisioning initial »)** — étapes côté gérant
   (dashboard web ou écran dédié — surface exacte à confirmer une fois #155/#159 implémentées, voir
   *Risks and Open Questions* §2) pour générer un credential device scopé au salon, et étapes côté
   terminal (saisie du credential sur l'écran de premier lancement de `main_kiosk.dart`,
   `--dart-define=APP_MODE=kiosk` — écran livré par #159, `specs/borne-app-mobile-mode-kiosque.md`)
   pour l'enregistrer localement. Préciser explicitement **où** le credential est conservé sur le
   device (stockage sécurisé de la plateforme — Android Keystore/`flutter_secure_storage` derrière
   le port dédié type `KioskCredentialStore` livré par #159, #155 ne fournissant que le contrat
   HTTP et le format du credential — jamais un fichier en clair ni les préférences partagées non
   chiffrées) et confirmer qu'il **survit** au redémarrage de l'app (contrairement à
   `InMemoryTokenStore` utilisé pour les sessions personnelles, qui ne doit **jamais** être réutilisé
   pour ce credential).
3. **Verrouillage kiosque (Android Lock Task Mode)** — activation du mode kiosque natif au
   provisioning (empêche la sortie vers l'launcher/les réglages Android), sans dépendance à un MDM
   tiers payant pour cette V1 (décision assumée, à documenter comme telle avec ses limites : pas de
   déploiement de flotte centralisé, pas de géolocalisation, gestion device par device).
4. **Sortie du mode kiosque par PIN gérant (maintenance, mise à jour applicative)** — décrire le
   geste opérateur (combinaison d'actions déclenchant une invite PIN, saisie du PIN gérant du
   salon propriétaire du device) et l'action côté application une fois sorti (accès aux réglages
   Android/mise à jour du build, jamais un accès aux données d'un autre salon). Toute sortie de
   mode kiosque est **journalisée** (décision 11 : « sécurité opérationnelle » — sortie du mode
   kiosque et actions de maintenance protégées par PIN gérant, journalisées) — préciser le mécanisme
   de journalisation exact une fois #155/#159 implémentées (audit `AuditLog` existant réutilisé, ou
   journal local device — à confirmer, voir *Risks and Open Questions* §3).
5. **Révocation d'un device perdu ou volé** — procédure d'urgence côté gérant pour invalider
   immédiatement le credential d'un device donné (sans attendre une éventuelle expiration), effet
   attendu (le device révoqué ne peut plus créer de ticket ni lire le catalogue dès le prochain
   appel réseau), et rappel qu'aucune donnée personnelle persistante ne doit rester exploitable sur
   le terminal après révocation (le device ne stocke pas de session personnelle cliente, seulement
   son propre credential — cohérent avec la décision « aucune session personnelle active en fin de
   parcours » de #159).
6. **Mise à jour applicative** — procédure de mise à jour du build kiosque (nouvel APK/AAB signé,
   installation manuelle ou via un canal de distribution à définir — hors périmètre d'un vrai MDM
   pour cette V1), à exécuter après sortie du mode kiosque (étape 4).
7. **Vérifications finales (critères d'acceptation #161)** — check-list reprenant explicitement le
   critère d'acceptation de l'issue : ADR committée dans `docs/adr/` ; procédure **vérifiée sur au
   moins un device physique** (case à cocher documentant la date, le salon pilote et l'opérateur
   ayant réalisé le test, en écho à la recommandation PRD Risque 5 de piloter sur 2-3 salons avant
   généralisation).

### (D) Mise à jour de `BACKLOG.md` (à exécuter une fois M7 livré, pas au moment de la spec)

Une fois les PR de #155 à #161 mergées sur `main`, appliquer à chacune des 7 entrées
(`BACKLOG.md:427-487`) le gabarit déjà utilisé pour #148 (`BACKLOG.md:327-334`) :

```markdown
- **#155 — US-8.1 · Rôle & authentification borne** · `Must` · `M` · `feature` `security` · **Livré**
  [... texte existant inchangé ...]
  *Dépend de :* #12.
  *Livré via :* #<PR#> (mergé sur main), [ADR-0041](./docs/adr/0041-authentification-borne-kiosque.md).
```

... et de même pour #156 à #160 (chacune référençant sa propre PR une fois connue, #157
référençant en outre [ADR-0042](./docs/adr/0042-file-attente-walkin-queue-ticket.md)) ; #161
elle-même reçoit son propre suffixe `· **Livré**` + `*Livré via :*` pointant vers **sa propre** PR
(l'ADR + le document de provisioning), une fois celle-ci mergée séparément. Le bandeau de contexte
du jalon (`BACKLOG.md:408-425`) et la ligne du tableau des jalons (`BACKLOG.md:29`) restent
inchangés dans leur formulation ; seule une note peut être ajoutée en tête de section M7 indiquant
la date de clôture effective, en écho à la façon dont M7 a été introduit
(`BACKLOG.md:34-35`).

### (E) Mise à jour de `prd-coiflink.md` (à exécuter une fois M7 livré)

Ajouter une note d'annotation à `prd-coiflink.md` §17 (immédiatement après le titre §17.1 ou en tête
de §17.3/§17.4, format à trancher en rédaction), sans réécrire le texte existant du PRD (qui reste
la description de la vision complète, y compris ce qui reste différé) — dans le même esprit que la
note déjà posée dans `BACKLOG.md:497-501` mais côté PRD, qui n'en porte aujourd'hui aucune. Contenu
de la note : renvoi vers le jalon M7 livré, rappel du sous-ensemble effectivement construit
(identification téléphone/création de fiche walk-in, choix de prestation, ticket de passage avec
ETA, **impression papier** — pas « ticket numérique + SMS/WhatsApp » comme décrit en §17.3), et
rappel explicite de ce qui reste différé (vérification de RDV existant, QR code/code de réservation,
affichage temps réel des coiffeurs disponibles, paiement autonome).

## Affected Files / Packages / Modules

### Documentation — à créer

| Fichier | Rôle |
| --- | --- |
| `docs/adr/0041-authentification-borne-kiosque.md` | ADR actant l'authentification borne de #155 — committée avec la PR de #155 ; #161 la vérifie et l'écrit si elle manque encore |
| `docs/adr/0042-file-attente-walkin-queue-ticket.md` | ADR actant l'architecture `QueueTicket` de #157 — committée avec la PR de #157 ; #161 la vérifie et l'écrit si elle manque encore |
| `docs/provisioning-borne-kiosque.md` | Runbook opérationnel : association device↔salon, sortie mode kiosque par PIN, révocation, mise à jour applicative |

### Documentation — à modifier

| Fichier | Modification |
| --- | --- |
| `docs/adr/README.md` | nouvelles lignes d'index pour ADR-0041 et ADR-0042 |
| `BACKLOG.md` | suffixe `· **Livré**` + ligne `*Livré via :*` sur les entrées #155-#161, **une fois** leurs PR respectives mergées |
| `prd-coiflink.md` | note d'annotation §17 renvoyant au sous-ensemble livré par M7, **une fois** M7 mergé |

### Non modifiés (rappel du périmètre)

Aucun fichier de `backend/`, `web-dashboard/` ou `app-mobile/` n'est touché par #161 : ces paquets
sont modifiés par les issues #155 à #160, dont #161 documente et consolide les décisions déjà
prises, sans les rouvrir.

## API / Interface Changes

**Aucun changement direct.** #161 ne modifie ni n'ajoute aucune route, aucun schéma de requête/
réponse, aucune permission. Elle **consolide dans les ADR-0041/0042** des décisions d'interface déjà actées
par les specs et implémentations de #155 (rôle `KIOSK`, endpoints scopés device — provisionnement
lecture catalogue, recherche téléphone restreinte, création de ticket walk-in) et #157 (endpoint
kiosque « rejoindre la file » — réservé au rôle `KIOSK`, jamais dans `PUBLIC_ROUTE_PATHS` ; le
« public » du texte de `BACKLOG.md` qualifie l'usage en libre-service, pas le régime
d'authentification —, formule d'ETA) : le contenu exact de ces interfaces (méthodes
HTTP, chemins, codes de statut) est décrit par les specs respectives de #155/#157, pas réinventé
ici. Les ADR-0041/0042 **citent** ces interfaces à titre de contexte décisionnel, sans en constituer la
source de vérité contractuelle (qui reste le code et l'OpenAPI générée).

## Data Model / Protocol Changes

**Aucun changement direct.** #161 n'ajoute, ne modifie ni ne supprime aucune migration Alembic,
aucune colonne, aucune contrainte. Le schéma du credential device (#155) et celui de `QueueTicket`
(#157, numéro séquentiel par salon/jour, statut, estimation d'attente) sont définis par les
migrations livrées par ces deux issues ; les ADR-0041/0042 les **documentent rétrospectivement** (comme
ADR-0039/ADR-0040 documentent des schémas déjà migrés au moment de leur rédaction), sans se
substituer aux migrations elles-mêmes comme source de vérité du schéma (`models.py` reste la source
de vérité du schéma, convention déjà établie par les ADR précédentes).

## Security & Privacy Considerations

- **L'ADR-0041 est elle-même un artefact de sécurité.** Le mandat explicite de #155
  (`BACKLOG.md:431` : « ADR requise, même exigence que l'anti-oracle ADR-0026 ») fait de sa
  rédaction une **condition de clôture** de M7, pas une simple bonne pratique documentaire — un
  nouveau rôle et un nouveau mécanisme d'authentification touchent directement au périmètre
  deny-by-default (ADR-0015) et méritent la même rigueur de revue qu'un changement de RBAC.
- **Distinction explicite entre l'anti-oracle ADR-0026 (comptes `users`) et le risque PII du
  terminal partagé (`CustomerProfile`).** L'ADR-0041 doit énoncer clairement que ce sont deux
  risques **différents**, pas une extension mécanique de la même règle : ADR-0026 protège contre un
  oracle d'existence de **compte** (mot de passe, `users`) ; le risque propre à la borne est
  l'**exposition PII sur un écran public partagé** (nom associé à un téléphone visible par d'autres
  clients dans la file). La mitigation documentée (prénom seul affiché, limitation de débit des
  tentatives de recherche) doit être présentée comme une réponse à ce second risque, pas comme une
  clause supplémentaire de l'anti-oracle existant.
- **Aucun secret dans le document de provisioning.** Comme `docs/mise-en-production.md:10-14,40-43`,
  le runbook de provisioning ne doit contenir **aucune valeur réelle** de credential device, PIN
  gérant ou identifiant de salon pilote — uniquement la procédure et des espaces réservés
  (`<credential>`, `<pin>`).
- **Le credential device est un secret opérationnel**, à traiter avec la même rigueur que
  `JWT_SECRET` (jamais loggé, jamais committé, stockage sécurisé côté device) — l'ADR et le document
  de provisioning doivent le dire explicitement, même si le mécanisme de stockage exact (Android
  Keystore ou équivalent) relève de l'implémentation de #155/#159.
- **La révocation doit être immédiate et vérifiable**, pas seulement documentée en théorie : le
  runbook doit décrire comment un opérateur **confirme** qu'un device révoqué ne peut plus émettre
  de ticket (test manuel après révocation), pour qu'un device volé ne reste pas un vecteur d'accès
  après signalement.
- **Aucune PII n'entre dans l'ADR ni dans le runbook eux-mêmes.** Ni l'un ni l'autre ne doit citer de
  nom, téléphone ou identifiant réel de client ou de salon pilote — seuls des identifiants
  techniques génériques ou des espaces réservés.
- **Journalisation des actions de maintenance (décision 11).** La sortie du mode kiosque par PIN
  gérant doit être journalisée — l'ADR-0041 doit préciser si cette journalisation réutilise le port
  `AuditLog`/`audit_logs` existant (§11.4, patron déjà établi par #17/#28) ou un mécanisme dédié côté
  device, et le document de provisioning doit refléter le choix retenu une fois connu.

## Testing Plan

Issue **exclusivement documentaire** : aucun test automatisé n'est produit par #161 (aucun code
n'est modifié). La vérification porte sur le contenu et sur une validation opérationnelle :

- **Revue de contenu des ADR-0041 et ADR-0042** : relecture croisée confirmant qu'elles ne
  contredisent ni ne réécrivent aucune décision déjà actée par les specs/PR de #155/#157 (elles
  **consolident**, elles ne **décident** pas a posteriori) ; vérification que les numéros
  `0041`/`0042` sont bien les prochains libres au moment de la rédaction réelle (`ls docs/adr/`
  peut avoir avancé entre cette spec et l'implémentation de #161, si d'autres ADR sont committées
  entretemps par des issues parallèles).
- **Revue de la mise à jour de `docs/adr/README.md`** : les nouvelles lignes respectent le format
  exact des 41 lignes existantes (colonnes ADR/Titre/Statut/Issue).
- **Vérification opérationnelle de la procédure de provisioning — critère d'acceptation explicite
  de #161** : exécuter la procédure complète (association, sortie de mode kiosque par PIN,
  révocation) sur **au moins un device physique réel**, et consigner la date, le salon pilote et
  l'opérateur dans la check-list finale du document (§« Vérifications finales »). Sans cette
  vérification physique, l'issue n'est **pas** considérée close, quel que soit l'état du texte.
- **Non-régression documentaire** : vérifier qu'aucun lien relatif cassé n'est introduit
  (`docs/adr/0041-*.md`, `docs/adr/0042-*.md`, `docs/provisioning-borne-kiosque.md`, entrées `BACKLOG.md`/`prd-coiflink.md`
  référencées correctement les unes envers les autres).
- **Vérification différée (bloquée jusqu'à la fusion de #155-#160)** : la mise à jour de
  `BACKLOG.md`/`prd-coiflink.md` (partie D/E de *Proposed Implementation*) ne peut être vérifiée
  qu'une fois ces PR réellement mergées — à traiter comme une tâche de suivi de #161, pas comme un
  blocage de sa propre PR (le runbook — et toute ADR encore manquante à ce stade — peuvent être
  mergés avant la clôture complète du jalon, à la manière dont ADR-0039 a été rédigée avant
  #150-154).

## Documentation Updates

- **`docs/adr/0041-authentification-borne-kiosque.md`** et
  **`docs/adr/0042-file-attente-walkin-queue-ticket.md`** — committées avec les PR de #155 et #157
  respectivement ; #161 vérifie leur présence et leur complétude (et les écrit si elles manquent
  encore) — voir plan détaillé en *Proposed Implementation* §A.
- **`docs/adr/README.md`** — nouvelles lignes d'index pour ADR-0041 et ADR-0042 (§B).
- **`docs/provisioning-borne-kiosque.md`** (nouveau) — runbook de provisioning (§C).
- **`BACKLOG.md`** — suffixes « Livré » + liens de PR sur #155-#161, appliqués une fois le jalon
  effectivement livré (§D) ; cette mise à jour est elle-même un **livrable documenté** de #161, à
  exécuter en toute fin de jalon.
- **`prd-coiflink.md` §17** — note d'annotation renvoyant au sous-ensemble livré par M7 (§E), sans
  réécrire le corps existant du PRD.
- **`README.md`** (racine) — si le tableau des jalons ou la roadmap y mentionne M7, une phrase de
  statut « M7 livré : borne client kiosque libre-service » peut être ajoutée par cohérence avec le
  style déjà utilisé pour M4 (`specs/creation-fiche-client-gerant.md:399`) ; laissé à l'appréciation
  du porteur produit au moment de la clôture réelle du jalon, pas un livrable strict de #161.

## Risks and Open Questions

Cette section reprend uniquement les décisions de la liste des choix d'architecture retenus pour M7
qui concernent directement #161, à valider par le porteur produit avant l'implémentation réelle.

1. **Décision 1 (identité borne) — mécanisme exact du credential device.** La liste des décisions
   retenues pour M7 fixe le principe (« nouveau rôle KIOSK + credential de device par salon, jamais
   un JWT CLIENT/MANAGER personnel partagé »), mais ne fixe pas le mécanisme cryptographique exact
   (JWT signé à très longue durée, clé API opaque en base, certificat client, etc.). *Recommandation
   technique* : l'ADR-0041 étant committée **avec** la PR d'implémentation de #155 (plan ADR acté,
   voir *Goals*), elle documente fidèlement le mécanisme réellement retenu au moment où il est
   livré — un ADR qui décrirait un mécanisme différent de celui livré serait pire qu'une absence
   d'ADR. Le rôle de #161 se limite à **vérifier a posteriori** que l'ADR livrée reflète bien le
   code mergé (et à l'écrire si elle manque encore à ce stade) ; l'ancienne alternative « rédiger
   l'ADR avant ou après #155 » est ainsi résolue sans toucher à l'ordre de dépendance de #161, qui
   reste la **dernière** issue du jalon.
2. **Décision 8 (borne mono-salon) et décision 11 (sécurité opérationnelle) — surface exacte du
   provisioning côté dashboard gérant.** Les décisions retenues fixent le principe (`salon_id` figé
   à l'installation, sortie de mode kiosque protégée par PIN gérant, actions journalisées) mais ne
   fixent pas **où**, dans le dashboard web existant, un gérant génère un credential device
   (nouvel écran dédié sous `web-dashboard/app/(gerant)/gerant/...`, ou action rattachée à la
   section « Paramètres » existante). *Recommandation technique* : cette décision d'écran relève de
   l'implémentation de #155/#159, pas de #161 — le document de provisioning doit être écrit de
   façon à rester correct quel que soit l'écran retenu (décrire l'**action**, pas nécessairement le
   chemin de navigation exact), et être complété avec le chemin précis une fois connu. **À
   confirmer** par le porteur produit avant la rédaction finale du runbook.
3. **Décision 11 (sécurité opérationnelle) — mécanisme de journalisation de la sortie de mode
   kiosque.** La journalisation des actions de maintenance/sortie de mode kiosque peut réutiliser le
   port `AuditLog`/table `audit_logs` déjà existant (§11.4, patron #17/#28) si le device dispose
   d'une connectivité au moment de l'action, ou nécessiter un journal local synchronisé plus tard si
   l'action doit rester possible hors ligne. *Recommandation technique* : documenter dans l'ADR-0041
   le choix réellement fait par #155/#159, avec une préférence de principe pour la réutilisation
   d'`AuditLog` (cohérence avec le reste du dépôt, pas de nouvelle table dédiée sans nécessité
   démontrée) si la connectivité de la borne au moment de la sortie de mode kiosque le permet. **À
   confirmer** une fois #155/#159 implémentées.
4. **Une seule ADR pour #155 et #157, ou deux ADR séparées ? — Résolu : deux ADR séparées.** Le
   choix est tranché pour le jalon : une décision = une ADR —
   `docs/adr/0041-authentification-borne-kiosque.md` (committée avec la PR de #155) et
   `docs/adr/0042-file-attente-walkin-queue-ticket.md` (committée avec la PR de #157) —,
   conformément à la pratique du dépôt (ADR-0039 livrée avec #148, ADR-0040 avec #154), ce qui
   isole chaque décision pour une référence future indépendante (par exemple si #157 est révisée
   plus tard sans toucher à l'authentification, ou inversement). La formulation au singulier du
   texte de l'issue #161 (« une ADR », `BACKLOG.md:482-483`) se lit comme une exigence d'ADR, pas
   comme le mandat d'une ADR unique consolidée : #161 ne crée pas d'ADR consolidée, il vérifie et
   complète les deux ADR portées par #155/#157.

## Implementation Checklist

1. **Vérifier l'état d'avancement de #155 à #160** avant de commencer la rédaction : les
   ADR-0041/0042 et le runbook de provisioning doivent refléter fidèlement les mécanismes
   **réellement livrés**, pas des anticipations — relire les PR mergées de ces issues, pas
   seulement leurs specs de planification.
2. **Confirmer les prochains numéros d'ADR libres** par `ls docs/adr/*.md | sort` au moment de la
   rédaction réelle (peuvent avoir avancé au-delà de `0041`/`0042` si d'autres ADR ont été
   committées entretemps).
3. **Vérifier la présence et la complétude des deux ADR** (0041 committée avec la PR de #155, 0042
   avec celle de #157 — question §4 résolue en ce sens).
4. **Compléter, ou rédiger si elles manquent encore, les ADR** selon le plan détaillé en *Proposed
   Implementation* §A, en citant les fichiers/lignes réels du code livré par #155/#157 (pas les
   hypothèses de cette spec, qui datent d'avant leur implémentation).
5. **Ajouter les deux lignes d'index (0041, 0042) à `docs/adr/README.md`** dans le format exact des
   41 lignes existantes.
6. **Rédiger `docs/provisioning-borne-kiosque.md`** selon le plan détaillé en *Proposed
   Implementation* §C, en confirmant au préalable les questions ouvertes §2/§3 avec le porteur
   produit et avec l'implémentation réelle de #155/#159/#160.
7. **Exécuter et consigner la vérification physique** de la procédure de provisioning sur au moins
   un device réel (association, sortie de mode kiosque par PIN, révocation) — critère d'acceptation
   non négociable de #161.
8. **Une fois toutes les PR de #155 à #160 mergées sur `main`** : appliquer la mise à jour de
   `BACKLOG.md` (suffixes « Livré » + liens de PR, gabarit #148) et l'annotation de `prd-coiflink.md`
   §17, selon *Proposed Implementation* §D/§E.
9. **Marquer #161 elle-même comme « Livré »** dans `BACKLOG.md` une fois sa propre PR (runbook +
   compléments d'ADR éventuels) mergée, avec le lien vers cette PR.
10. **Vérification finale** : relire l'ensemble des documents produits pour confirmer qu'aucune PII,
    aucun secret réel et **aucune signature IA** n'apparaît nulle part (ADR, runbook, mise à jour de
    `BACKLOG.md`/`prd-coiflink.md`, message de commit, description de PR).
