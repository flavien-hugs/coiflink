# ADR-0041 : Rôle & authentification de la borne terminal — cinquième rôle `TERMINAL`, compte de service par salon, credential de device longue durée

- **Statut** : Accepté
- **Date** : 2026-08-10
- **Décideurs** : équipe CoifLink
- **Issue** : #155 (US-8.1 · Rôle & authentification borne) — jalon **M7** (Borne client, Épic 8)
- **Référence PRD** : §4.1 (permissions par rôle), §11.1 (authentification), §11.2 (isolation par
  salon), §11.3 (non-fuite PII), §11.4 (journalisation), §17 (Borne Intelligente d'Accueil)
- **S'appuie sur** : [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (#12, RBAC
  deny-by-default, rôle **relu en base**), [ADR-0016](./0016-comptes-employes-appartenance-salon.md)
  (#13, appartenance employé↔salon), [ADR-0012](./0012-hachage-argon2-strategie-otp.md) (#8, argon2id),
  [ADR-0013](./0013-connexion-jwt-refresh-anti-bruteforce.md) (#10, JWT + anti-bruteforce),
  [ADR-0026](./0026-fiche-client-portee-salon.md) (#28, anti-oracle fiche client — citée en référence
  par l'issue)

## Contexte et problème

Le jalon M7 (PRD §17) installe une **borne tactile en salon** sur laquelle un client **sans
rendez-vous** s'identifie par téléphone (ou crée une fiche), choisit une prestation et reçoit un ticket
de passage. Cette borne est un **terminal public partagé** : elle appelle le backend **en son nom
propre**, en continu, sans qu'aucun humain ne s'y connecte. Or **rien dans le dépôt ne permet
d'authentifier un terminal** :

- le RBAC est **fermé** sur exactement quatre rôles **personnels** (`CLIENT`, `HAIRDRESSER`,
  `MANAGER`, `ADMIN`) — un rôle absent de `ROLE_PERMISSIONS` n'a **aucune** permission ;
- **aucun rôle existant ne convient.** Créer une fiche exige `CUSTOMER_MANAGE` (MANAGER seul) — un
  credential `MANAGER` sur une borne publique exposerait caisse, fiches complètes et gestion du salon.
  Réserver exige `APPOINTMENT_BOOK` (CLIENT seul), et `client_id` provient toujours du `Principal` JWT —
  une session `CLIENT` partagée fusionnerait les parcours de tous les passants sur **un** compte ;
- l'authentification actuelle est **exclusivement personnelle** (compte + mot de passe → paire JWT
  courte) ; aucun mécanisme de clé API, de jeton « par salon » ou de compte « device » n'existe ;
- le **deny-by-default** est verrouillé : toute route publique doit être listée dans
  `PUBLIC_ROUTE_PATHS` (revue de sécurité) et l'invariant `unprotected_routes(app) == []` fait échouer la
  CI sur toute route ni publique-listée ni gardée.

#155 comble ce gap : **une identité de terminal** — rôle dédié, credential de device longue durée
provisionné par le gérant, portée figée sur **un** salon, permissions minimales — sur laquelle #156
(recherche téléphone + fiche walk-in), #157 (ticket de passage) et #159 (mode terminal de l'app) poseront
leurs gardes **sans jamais** accorder `CUSTOMER_MANAGE` ni `APPOINTMENT_BOOK`.

## Décision

### 1. Un cinquième rôle `TERMINAL`, le device étant un **compte de service** dans `users`

Deux options ont été évaluées :

- **Option 1 (retenue)** — étendre l'énumération fermée `Role` d'un membre `TERMINAL`, la borne étant un
  compte de service `users` (`role = 'TERMINAL'`) + un rattachement `salon_members`. La borne devient un
  `Principal` ordinaire : **toute** la chaîne existante est réutilisée sans duplication — émission JWT,
  garde globale, relecture base (`get_current_principal`), matrice `ROLE_PERMISSIONS`,
  `require_permission`, `require_salon_scope`, invariant `unprotected_routes`, audit
  (`actor_user_id` FK `users`).
- **Option 2 (écartée)** — un mécanisme d'authentification de device entièrement parallèle (table
  `terminal_devices` autonome, clé API, famille de gardes `require_terminal_device` distincte). Écartée car
  chaque brique de sécurité **centralisée et testée** du dépôt devrait être **dupliquée puis re-prouvée**
  (marquage `_PRINCIPAL_GUARD_ATTR` d'une seconde famille de gardes sous peine de rendre
  `unprotected_routes` aveugle ; droits hors `ROLE_PERMISSIONS`, en contradiction avec « l'unique source
  de vérité des droits » et la matrice négative dérivée ; audit et révocation immédiate à réinventer).
  Le risque de divergence de deux systèmes d'autorisation parallèles dépasse le gain de pureté du modèle.

Le compte de service `users` reste un **détail d'implémentation encapsulé** : le port
`TerminalDeviceRepository` cache que la borne vit dans `users` + `salon_members`, ce qui permettrait de
migrer plus tard vers une table propre sans toucher aux gardes ni aux cas d'usage.

### 2. Permissions minimales et dédiées — `TERMINAL` détient **exactement** trois droits

`Permission` gagne quatre membres ; `ROLE_PERMISSIONS[Role.TERMINAL]` détient **exactement**
`CUSTOMER_LOOKUP_TERMINAL` (recherche fiche par téléphone, restreinte au salon — #156),
`CUSTOMER_CREATE_WALKIN` (création de fiche nom/prénom/téléphone sans compte — #156) et
`QUEUE_TICKET_CREATE` (ticket de passage — #157). **Ni** `CUSTOMER_MANAGE`, **ni** `APPOINTMENT_BOOK`,
**ni** aucune lecture gérant. Le gérant gagne la seule permission `TERMINAL_PROVISION` (aucun retrait,
aucun élargissement d'un droit existant). Ces deux permissions consommatrices restent inertes tant que
#156/#157 ne posent pas leurs routes — comme `CUSTOMER_MANAGE` l'était avant #28.

La **lecture catalogue** exigée par l'issue est satisfaite par les routes **publiques** existantes
`/catalog/...` : accorder `SERVICE_READ` à la borne ouvrirait la vue **gérant** (prestations inactives
incluses) — refusé au titre du moindre privilège.

### 3. Portée mono-salon lue en base, jamais d'un paramètre de requête

La portée du device est son rattachement `salon_members` : `SqlSalonScopeRepository.salon_ids_for` et
`can_access_salon` traitent `TERMINAL` **exactement** comme `HAIRDRESSER` (lecture `salon_members` `ACTIVE`).
Le `salon_id` est figé **une fois**, au provisioning ; aucune sélection de salon à l'écran de la borne.
Un salon multi-bornes est supporté (plusieurs devices) ; une borne multi-salons ne l'est pas (assumé).

### 4. Identité du device : deux lignes atomiques + sentinelle `phone`

Un device provisionné = une ligne `users` (`role = 'TERMINAL'`, `status = 'ACTIVE'`, `full_name` = libellé,
`password_hash` = argon2id(secret), `email = NULL`) + une ligne `salon_members`
(`role = 'TERMINAL'`, `status = 'ACTIVE'`), créées dans la **même `Session`** (patron `CreateEmployee`).

`users.phone` est `NOT NULL UNIQUE` — un device n'a pas de téléphone. **Décision (Open Question tranchée)** :
V1 utilise une **valeur sentinelle** `phone = id.hex` (32 caractères hexa, tient dans `String(32)`,
unique par construction) plutôt qu'une migration rendant `phone` nullable. Innocuité **démontrable** :
`normalize_phone` produit **toujours** une chaîne commençant par `+`, et `classify_identifier` du login
ne résout que des téléphones normalisés ou des e-mails — la sentinelle est donc **inatteignable** depuis
`/auth/login`, le reset OTP et toute recherche par téléphone. La bascule `phone` nullable (index unique
partiel, patron `uq_users_email`) reste un **suivi** documenté (plus propre, plus invasif).

### 5. Credential longue durée, distinct des JWT personnels

La borne détient durablement `(device_id, secret)`. Le secret est **généré** au provisioning
(`secrets.token_urlsafe(32)`, 256 bits), affiché **une seule fois** (réponse `201`), stocké **uniquement**
en argon2id, jamais journalisé, jamais relisible. Il s'échange contre une paire JWT **standard et
courte** (accès 15 min, refresh 30 j — TTL applicatifs inchangés) via `POST /auth/terminal/login`, route
**publique-listée** (endpoint d'authentification), rate-limitée par `device_id`, réponse `401`
**générique constante** pour tout échec (device inconnu, secret faux, device révoqué — aucun oracle).
La réponse porte le `salon_id` du device (un APK unique pour toutes les bornes, #159 s'aligne).

**Ce qui est long est révocable, ce qui est porteur est court** : un jeton porteur long sur un terminal
public serait irrévocable pendant toute sa durée de vie (`_verify_access` est stateless) ; secret long
révocable + jetons courts + relecture du statut par requête donne une **révocation immédiate**.

### 6. Provisioning gérant + révocation logique à effet immédiat

Trois routes sous `POST/GET/DELETE /salons/{salon_id}/terminal-devices`, gardées par `require_salon_scope`
+ `require_permission(TERMINAL_PROVISION)` — **jamais** publiques. La révocation (`DELETE`) est **logique** :
`users.status → SUSPENDED` (coupe l'accès à la requête suivante via `get_current_principal`) **et**
`salon_members.status → INACTIVE` (vide la portée) — jamais une suppression physique (traçabilité).
Provisioning et révocation sont **journalisés** (`TERMINAL_DEVICE_PROVISIONED` / `TERMINAL_DEVICE_REVOKED`,
`metadata = {}` — ni secret, ni condensat, ni libellé).

### 7. Migration `0013` — aucune table, aucune colonne

Régénération des `CHECK` `ck_users_role` et `ck_salon_members_role` pour accepter `'TERMINAL'` (patron exact
de `0007`, downgrade symétrique, round-trip CI). C'est l'argument de poids de l'Option 1 : la borne
réutilise le schéma existant.

## Conséquences

- **Positif.** Un terminal public s'authentifie avec une portée limitée (lecture catalogue publique,
  recherche téléphone restreinte, création de ticket walk-in) sans jamais obtenir `CUSTOMER_MANAGE` ni
  `APPOINTMENT_BOOK` ; le refus est **figé** par la matrice fermée, les jeux exacts
  (`test_domain_permissions.py`) et la matrice négative rôle × route (`test_security_authz_matrix.py`,
  qui exerce mécaniquement `TERMINAL` en `403`). Rayon d'explosion d'un credential volé borné à **un** salon.
- **Positif.** Zéro duplication du socle de sécurité : émission JWT, deny-by-default, relecture base,
  audit et révocation immédiate sont réutilisés tels quels.
- **Compromis assumé.** `users.phone = id.hex` est une valeur non-téléphone dans une colonne nommée
  `phone` (dette lisible, innocuité démontrée §4) — bascule `phone` nullable en suivi.
- **Compromis assumé.** Deux des trois permissions `TERMINAL` sont inertes jusqu'à #156/#157 (droit sans
  route = droit inerte, risque faible).
- **Ce que #155 ne mitige pas (documenté).** Compromission physique du terminal (verrouillage Android +
  PIN gérant — #159/#161) ; **rotation périodique** du secret (un secret compromis se révoque et se
  re-provisionne en deux appels — une rotation imposée exigerait un état supplémentaire) ; **attestation**
  du device, mTLS, allowlist d'IP, MDM — hors MVP.
- **Suivi.** Le volet `QueueTicket` (ticket de passage) a sa **propre** ADR-0042, committée avec #157 ;
  #161 vérifie la présence des deux ADR du jalon, met à jour l'index et porte le runbook de provisioning.
  Une page dashboard de gestion des bornes (le provisioning V1 est API-first) est un suivi possible, non
  exigé par l'issue.
