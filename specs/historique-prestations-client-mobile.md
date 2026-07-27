# Historique de prestations (côté client mobile) (US-4.4)

> Spécification de planification pour l'issue GitHub **#30 — US-4.4 : Historique de prestations
> (côté client mobile)** (`feature` · Should · Effort S · PRD §6 Épic 4, §11.2). **Dépend de #25**
> (cycle de statuts gérant : c'est le passage `CONFIRMED → COMPLETED` piloté par le gérant qui
> **produit** les RDV terminés que cet historique lit). S'appuie sur le chemin rendez-vous client
> livré par #21/#22/#23/#24 (moteur, réservation, « Mes rendez-vous », modification, annulation).
> **Cette spec ne produit pas de code** : elle décrit l'approche à implémenter dans une phase
> ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires Dart/Python),
> en-têtes de section en **anglais** (attendus par le gabarit ADW), identifiants techniques (noms de
> routes, champs JSON, symboles, enums) inchangés. **Aucune signature IA** dans le code, les commits
> ou la PR.

## Problem Statement

Le PRD (§6 Épic 4, US-4.4) pose le besoin : **« en tant que client, je veux consulter mon historique
de prestations depuis l'application mobile »**. Le critère d'acceptation de l'issue #30 est unique et
tranchant :

- **Le client voit son historique de RDV terminés (`COMPLETED`) et rien d'autre.**

C'est la **contrepartie cliente** de l'historique salon-scopé livré au gérant en #29
(`GET /salons/{salon_id}/customers/{customer_id}/appointments`, RDV `COMPLETED` d'une fiche client) :
là où le gérant consulte l'historique d'**une fiche de son salon**, le client consulte **son propre**
historique, **tous salons confondus**, borné à ses seuls RDV **réalisés**.

### État actuel du dépôt (après #21–#29)

- **Le vocabulaire et le filtre par statut existent déjà côté backend.**
  - `GET /appointments` (adapters/inbound/appointments.py) liste les RDV du client mais **force**
    `statuses=CLIENT_MODIFIABLE_STATUSES` (`PENDING`, `CONFIRMED`) — **RDV actifs uniquement**. Son
    docstring réserve **explicitement** le reste à #30 : *« Alimente le flux de modification (#23) ;
    l'historique complet (RDV terminés + montants) relève de US-4.4 (#30). »*
  - Le cas d'usage `ListMyAppointments.execute(client_id, *, statuses=None)`
    (application/appointments.py) **accepte déjà** un filtre `statuses` optionnel et délègue à
    `AppointmentRepository.list_for_client(client_id, statuses)`.
  - L'adapter `SqlAppointmentRepository.list_for_client` **applique déjà** `status.in_(statuses)`
    quand `statuses` est fourni, charge les prestations (`_load_services`, avec `price_at_booking`
    figé) et **trie chronologiquement croissant** (`appointment_date.asc(), start_time.asc()`).
  - `REVENUE_STATUSES = (AppointmentStatus.COMPLETED.value,)` (domain/appointment.py) matérialise déjà
    l'invariant « seul un RDV `COMPLETED` est réalisé ». Aucune constante « historique client » dédiée
    n'existe encore.
  - Le rôle **`CLIENT`** détient la permission **`APPOINTMENT_READ_OWN`** (domain/permissions.py),
    déjà câblée sur `GET /appointments`. **Aucune** portée salon n'est requise (route
    d'**appartenance** : `client_id = principal.id` imposé serveur).
- **Côté application mobile (Flutter), le chemin « Mes rendez-vous » existe mais ne montre que les RDV
  actifs.**
  - Port `AppointmentGateway.myAppointments({accessToken})` → `GET /appointments` (renvoie les actifs,
    tels que filtrés serveur). Adapter `HttpAppointmentGateway.myAppointments`, cas d'usage
    `ListMyAppointments`, écran `MyAppointmentsScreen` (liste + actions modifier/annuler).
  - Le **domaine client** porte déjà tout le nécessaire à un rendu d'historique : `Appointment`
    (`status`, `date`, `startTime`/`endTime`, `services` avec `BookedService.priceAtBooking`),
    `AppointmentStatus` (dont `completed` → libellé « **Terminé** ») et `AppointmentStatus.fromApi`
    (tolérante aux valeurs inconnues). `Appointment.isClientModifiable`/`isClientCancellable`
    renvoient **`false`** pour un RDV `COMPLETED` — un historique est **en lecture seule**.
  - La session cliente (`AuthSession` + `TokenStore` en mémoire au MVP), le flux `onRequireLogin` et
    la traduction des échecs en exceptions **neutres** (`UnauthorizedException`,
    `AppointmentGatewayException`) sont établis et réutilisables.
- **Ce qui manque (le gap de #30) :**
  1. **Backend** — aucune route ne renvoie au **client** ses RDV **`COMPLETED`** (le seul chemin,
     `GET /appointments`, est verrouillé sur les actifs). Il faut **exposer** l'historique client, en
     réutilisant le filtre `statuses` déjà présent — **sans** permettre au client de choisir un statut
     arbitraire (l'acceptation dit « **et rien d'autre** »).
  2. **Mobile** — aucun port/cas d'usage/écran ne consomme cet historique ni ne l'affiche.

## Goals

- **Backend : lecture d'historique client bornée `COMPLETED`.** Exposer une lecture qui renvoie **les
  RDV `COMPLETED` du client authentifié**, tous salons confondus, avec leurs prestations et montants
  figés (`price_at_booking`). Le filtre `COMPLETED` est **décidé serveur** (jamais un statut soumis
  par le client) — l'acceptation « rien d'autre » est garantie par construction, pas par confiance
  dans le client.
- **Isolation par appartenance (§11.2/§11.3).** La route est une route d'**appartenance**
  (`client_id = principal.id` imposé serveur, `APPOINTMENT_READ_OWN`) : un client ne voit **que ses
  propres** RDV — jamais ceux d'un tiers, jamais de donnée de gestion.
- **Mobile : écran « Mon historique » en lecture seule.** Un client authentifié ouvre un écran qui
  liste ses RDV terminés (date, horaires, statut « Terminé », prestations + montants), **sans** action
  de modification/annulation (RDV terminal, §8.1). Réutilise la session, `onRequireLogin`, le
  pull-to-refresh et les états vides/erreur du patron `MyAppointmentsScreen`.
- **Réutiliser le chemin existant.** Étendre le port/adapter/cas d'usage/écran par **addition**, sans
  dupliquer la logique réseau ni casser « Mes rendez-vous ». Aucun nouveau schéma de données.
- **Confidentialité & neutralité.** Le jeton n'est **jamais** journalisé (§11.1) ; aucune PII ni URL
  ni corps n'est journalisé ; les erreurs restent **neutres** (patron `AppointmentGatewayException`).
- **Couverture de tests.** Backend (route/permission/filtre `COMPLETED`/appartenance) et mobile
  (adapter HTTP, cas d'usage, écran : chargement, liste, vide, non-authentifié, `401`, erreur réseau).

## Non-Goals

- **Statistiques / agrégats client (nombre de visites, dernière visite, total dépensé).** Le résumé
  dérivé livré au **gérant** en #29 n'est **pas** exigé par l'acceptation de #30 (« voit son historique
  … et rien d'autre »). Un éventuel résumé côté client relève des **statistiques par client (#31)** ou
  d'une itération ultérieure — **recommandation : ne pas le livrer dans #30** (voir Open Questions).
- **Facturation / encaissement / reçus.** Les montants affichés sont les **prix figés à la
  réservation** (`price_at_booking`) déjà portés par le domaine ; #30 **ne calcule aucun total**, ne
  produit **aucun reçu** ni justificatif (Encaissement M4 #33+, KPI M5).
- **Filtre de statut libre côté client.** #30 n'ouvre **pas** au client la possibilité de filtrer par
  un statut arbitraire (`CANCELLED`/`NO_SHOW`/`PENDING`…). L'historique est **`COMPLETED` seul**,
  serveur-forcé. (Une éventuelle vue « RDV annulés/absents » serait une autre décision produit.)
- **Pagination / filtres de plage de dates.** L'acceptation n'exige ni pagination ni bornes de dates.
  Le volume d'historique d'un client au MVP est faible ; **recommandation : lecture simple non
  paginée** (voir Open Questions sur une future pagination).
- **Interface web gérant.** #30 est un parcours **client mobile**. Le paquet `web-dashboard/` n'est
  **pas** touché ; l'historique gérant est déjà livré (#29).
- **Nouveau schéma, migration, colonne ou contrainte.** Toutes les colonnes (`status`,
  `appointment_date`, jonction `appointment_services.price_at_booking`) existent depuis #3.
- **Modification du comportement de `GET /appointments`.** La route « Mes rendez-vous » (actifs)
  **reste inchangée** (le flux de modification #23 en dépend) ; #30 **ajoute** un chemin d'historique
  distinct.

## Relevant Repository Context

### Stack & architecture

- **Backend** : FastAPI · Python ≥ 3.12 (ADR-0003) ; PostgreSQL 16 + SQLAlchemy 2.0 + Alembic +
  psycopg 3 (ADR-0009) ; **architecture hexagonale** ports & adapters (ADR-0008) — `domain/` et
  `application/` n'importent **jamais** FastAPI ni SQLAlchemy ; RBAC **deny-by-default** (ADR-0015).
  Tests `pytest` (`backend/pyproject.toml`, `testpaths=["tests"]`).
- **Mobile** : Flutter stable / Dart ^3.12 (ADR-0001, Android prioritaire), architecture hexagonale
  (`domain/` → `application/` → `adapters/{ui,data}`). Tests `flutter test`. La couche data lit
  l'URL d'API via `--dart-define` (`API_BASE_URL`, `ApiConfig.fromEnvironment`), **jamais** codée en
  dur.
- **Test gate** agrégé (#6) : `scripts/test-gate.sh` enchaîne `pytest` / `npm test` / `flutter test`.

### Backend rendez-vous déjà livré (à réutiliser)

- `coiflink_api/domain/enums.py` — `AppointmentStatus`
  (`PENDING|CONFIRMED|CANCELLED|COMPLETED|NO_SHOW`, hérite de `str`).
- `coiflink_api/domain/appointment.py` — `Appointment`, `BookedService`,
  `CLIENT_MODIFIABLE_STATUSES`, `REVENUE_STATUSES = (COMPLETED,)`, `counts_towards_revenue`,
  machine à états gérant (#25). **#30 peut y ajouter une constante `CLIENT_HISTORY_STATUSES`**
  (voir Open Questions sur la réutilisation de `REVENUE_STATUSES`).
- `coiflink_api/domain/permissions.py` — `CLIENT` détient `APPOINTMENT_READ_OWN` (+ `APPOINTMENT_BOOK`,
  `APPOINTMENT_READ_OWN`, `APPOINTMENT_MODIFY_OWN`, `APPOINTMENT_CANCEL_OWN`). **Aucune** nouvelle
  permission n'est requise.
- `coiflink_api/application/appointments.py` — `ListMyAppointments.execute(client_id, *,
  statuses=None)` **déjà paramétré par statut** ; délègue à `list_for_client`.
- `coiflink_api/application/ports/appointment_repository.py` — `list_for_client(client_id, statuses)`.
- `coiflink_api/adapters/outbound/persistence/appointment_repository.py` —
  `SqlAppointmentRepository.list_for_client` (filtre `status.in_(statuses)`, `_load_services` avec
  `price_at_booking`, tri `appointment_date.asc(), start_time.asc()`).
- `coiflink_api/adapters/inbound/appointments.py` — router : `GET /appointments`
  (`APPOINTMENT_READ_OWN`, filtre forcé `CLIENT_MODIFIABLE_STATUSES`), DI surchargeable
  `get_appointment_repository`, réponse commune `_appointment_response(...)` /
  `AppointmentResponse` (porte déjà `status`, `services[].price_at_booking`).
- `coiflink_api/adapters/inbound/security.py` — `require_permission`, `PUBLIC_ROUTE_PATHS`
  (n'y **rien** ajouter — route **protégée**), invariant `unprotected_routes(app)`.

### Mobile rendez-vous déjà livré (à étendre)

- `app-mobile/lib/domain/appointment/{appointment,appointment_status,availability_slot}.dart` —
  entités **pures** ; `AppointmentStatus.completed` → « Terminé » ; `BookedService.priceAtBooking`.
- `app-mobile/lib/application/ports/appointment_gateway.dart` — port `AppointmentGateway`
  (`availableSlots`/`book`/`myAppointments`/`modify`/`cancel`) + exceptions **neutres**
  (`UnauthorizedException`, `AppointmentGatewayException`, …). **#30 y ajoute `myHistory`.**
- `app-mobile/lib/application/use_cases/list_my_appointments.dart` — `ListMyAppointments` (délègue au
  port). **#30 ajoute un cas d'usage d'historique** (ou un paramètre — voir Open Questions).
- `app-mobile/lib/adapters/data/http_appointment_gateway.dart` — `HttpAppointmentGateway` :
  `myAppointments` (patron `GET /appointments` + `Authorization: Bearer`, `200/401/défaut`,
  `_appointmentFromJson`, jamais de journalisation de jeton/URL/PII). **#30 ajoute `myHistory`.**
- `app-mobile/lib/adapters/ui/appointments/my_appointments_screen.dart` — patron d'écran (chargement,
  `onRequireLogin`, `401` → `session.clear()` + reconnexion, états vide/erreur, pull-to-refresh,
  cartes RDV avec `status.label`). **#30 ajoute un écran d'historique en lecture seule.**
- `app-mobile/lib/adapters/ui/app.dart` — **composition root** : instancie gateways/use cases,
  bouton « Mes rendez-vous » sur l'accueil. **#30 y câble l'historique** (use case + écran + bouton
  « Mon historique »).

### Confidentialité & permissions (ADR-0015, §11.2/§11.3)

- **Route d'appartenance** (pas de portée salon) : `require_permission(APPOINTMENT_READ_OWN)` puis
  filtre serveur `client_id = principal.id`. Un `CLIENT` ne voit **que** ses RDV ; le statut renvoyé
  est **forcé `COMPLETED`** côté serveur. Refus `401`/`403` **constants et génériques** (aucun oracle).

## Proposed Implementation

Périmètre : **une lecture backend d'historique client bornée `COMPLETED`** + **le câblage mobile**
(port → adapter → cas d'usage → écran → composition root). Extension **additive** du chemin
rendez-vous existant, **sans nouveau schéma** et **sans toucher** `GET /appointments` (actifs).

### Backend

#### 1. Domaine (`domain/appointment.py`)

- Introduire une constante **`CLIENT_HISTORY_STATUSES: tuple[str, ...] = (AppointmentStatus.
  COMPLETED.value,)`** — le jeu de statuts que l'**historique client** expose. Elle **coïncide** au MVP
  avec `REVENUE_STATUSES` mais on la **nomme distinctement** (le concept « historique client visible »
  et le concept « comptabilisé au CA » sont deux décisions métier séparées, susceptibles de diverger —
  même posture que `CLIENT_MODIFIABLE_STATUSES` vs `CLIENT_CANCELLABLE_STATUSES`). *(Alternative :
  réutiliser `REVENUE_STATUSES` directement — voir Open Questions.)* Documenter que le filtre est
  **décidé serveur** (l'acceptation « rien d'autre »).

#### 2. Adapter entrant (HTTP) — nouvelle route protégée

- **Router** `adapters/inbound/appointments.py` — ajouter une route d'**appartenance** :
  - `GET /appointments/history` — **client** (`require_permission(APPOINTMENT_READ_OWN)`). **Aucune**
    portée salon (route d'appartenance, `client_id = principal.id`). **Aucun** paramètre de statut
    accepté du client (filtre forcé serveur). DI : `get_appointment_repository`.
  - Handler : `result = ListMyAppointments(appointments).execute(principal.id, statuses=
    CLIENT_HISTORY_STATUSES)` puis `return [_appointment_response(a) for a in result]`.
  - Réponse `200` : `list[AppointmentResponse]` (schéma existant — porte `status`, `date`, horaires,
    `services[].price_at_booking`). `401` jeton absent/expiré ; `403` rôle insuffisant (lecture
    réservée au client) — **identiques et génériques** (aucun oracle). Docstring OpenAPI + `responses`.
  - **Ordre d'affichage.** L'historique se lit naturellement **du plus récent au plus ancien**
    (descendant), alors que `list_for_client` trie **croissant** (`GET /appointments` liste les RDV
    « à venir »). Options (voir Open Questions & Data Model) : (a) trier côté client mobile (aucun
    changement backend) ; (b) paramétrer l'ordre dans `list_for_client` / ajouter une lecture dédiée
    descendante. **Recommandation : ordre descendant côté serveur** pour l'historique, via un paramètre
    d'ordre optionnel sur `list_for_client` (défaut inchangé = croissant, `GET /appointments`
    préservé) **ou** une méthode de port dédiée. **À confirmer.**
- **Placement de la route.** Déclarer `GET /appointments/history` **avant** toute route paramétrée
  concurrente pour éviter qu'un segment `history` soit capté comme un identifiant ; les routes
  existantes sont `GET /appointments` et `GET /appointments/assigned` (chemins **statiques**
  distincts), donc aucun conflit — vérifier néanmoins l'ordre de déclaration au moment de l'implé.
- **Composition root** `coiflink_api/main.py` : router déjà monté ; la nouvelle route en hérite. **Ne
  rien ajouter à `PUBLIC_ROUTE_PATHS`** (route **protégée**). Vérifier que `unprotected_routes(app)`
  reste vide (test existant).

#### 3. (Si option d'ordre serveur retenue) Port & adapter

- **Port** `application/ports/appointment_repository.py` : ajouter un paramètre d'ordre optionnel à
  `list_for_client` (p. ex. `newest_first: bool = False`) **ou** une méthode dédiée
  `list_history_for_client(client_id, statuses)`. **Recommandation : paramètre optionnel** (moins de
  surface, défaut = comportement actuel).
- **Adapter** `SqlAppointmentRepository.list_for_client` : appliquer `desc()` quand `newest_first`
  (sinon `asc()` inchangé). Aucune autre modification.

### Mobile (Flutter)

#### 1. Port (`application/ports/appointment_gateway.dart`)

- Ajouter au contrat `AppointmentGateway` : **`Future<List<Appointment>> myHistory({required String
  accessToken})`** — « Liste les RDV **terminés** (`COMPLETED`) du client via
  `GET /appointments/history` (`Authorization: Bearer`). Ne renvoie que ses propres RDV réalisés
  (§11.2/§11.3). Lève `UnauthorizedException` (`401`), `AppointmentGatewayException` (réseau/réponse
  invalide). » Aucune nouvelle exception nécessaire.

#### 2. Adapter data (`adapters/data/http_appointment_gateway.dart`)

- Implémenter `myHistory` en **miroir strict** de `myAppointments` : `GET /appointments/history` avec
  l'en-tête `Authorization: Bearer <accessToken>` ; `200` → `jsonDecode` liste →
  `_appointmentFromJson` (réutilisé) ; `401` → `UnauthorizedException` ; défaut →
  `AppointmentGatewayException('Impossible de charger votre historique.')` ; corps illisible →
  message neutre. **Ne journalise jamais** URL/jeton/corps/PII.

#### 3. Cas d'usage (`application/use_cases/`)

- Ajouter **`ListMyAppointmentHistory`** (nouveau fichier, patron `ListMyAppointments`) délégant à
  `_gateway.myHistory(accessToken: …)`. *(Alternative : ajouter un paramètre `history: bool` à
  `ListMyAppointments` — moins clair ; **recommandation : cas d'usage dédié**, voir Open Questions.)*
  Orchestration **pure** (aucune dépendance Flutter). Documenter : ne renvoie que les RDV terminés du
  client ; jeton jamais journalisé.

#### 4. Écran (`adapters/ui/appointments/appointment_history_screen.dart`)

- Nouvel écran `AppointmentHistoryScreen` (patron `MyAppointmentsScreen`, **en lecture seule**) :
  - Titre « Mon historique » ; charge via `ListMyAppointmentHistory` + `AuthSession` ; gère
    `onRequireLogin`, `401` → `session.clear()` + reconnexion, états **vide** (« Vous n'avez aucun
    rendez-vous terminé. »), **erreur** (réessayer), **chargement** (spinner), **pull-to-refresh**.
  - Cartes : `formatFullDate(date)`, `startTime – endTime`, `Chip(status.label)` (« Terminé »), et la
    **liste des prestations** avec leur **montant figé** (`BookedService.priceAtBooking`, XOF) —
    **aucun** bouton modifier/annuler (RDV terminal). Réutiliser `booking_labels.dart`
    (`formatFullDate`) et un rendu de montant cohérent avec l'UI existante.
  - Extraire, si pertinent, les petits widgets communs (`_CenteredMessage`, `_CenteredAction`) — soit
    en les partageant, soit en les redéfinissant localement (le patron actuel les garde privés à
    l'écran ; **recommandation : dupliquer légèrement** plutôt que d'introduire un module partagé pour
    #30, sauf si `/simplify` le justifie).

#### 5. Composition root (`adapters/ui/app.dart`)

- Instancier `listMyAppointmentHistory = ListMyAppointmentHistory(appointmentGateway)`.
- Ajouter un lanceur `openMyHistory(BuildContext)` poussant `AppointmentHistoryScreen`
  (`listMyAppointmentHistory`, `session`, `onRequireLogin`).
- Ajouter un **bouton « Mon historique »** sur `AccueilEcran` (à côté de « Mes rendez-vous »), câblé
  par un `onOpenMyHistory` optionnel (masquable, patron `onOpenMyAppointments`).

### Documentation & ADR

- **ADR** : décider si #30 justifie un ADR propre (numéro libre suivant — **vérifier** au step
  `document`) ou une **extension** de l'ADR rendez-vous/consultation existant. **Recommandation : un
  ADR court** actant : historique client = route d'**appartenance** `GET /appointments/history`,
  filtre **`COMPLETED` forcé serveur** (jamais soumis client), lecture seule (RDV terminal §8.1),
  montants = `price_at_booking` figés (aucun calcul), **sans nouveau schéma**, résumé/statistiques
  différés (#31). Indexer dans `docs/adr/README.md`. **À confirmer** (voir Open Questions).
- **`backend/README.md`** : documenter `GET /appointments/history` (client, `COMPLETED` seul,
  appartenance).
- **`app-mobile/README.md`** (et READMEs de couche `adapters/ui`, `adapters/data`) : mentionner
  l'écran d'historique et le nouveau chemin gateway.
- **`prd-coiflink.md` : ne pas modifier**. Récit `README.md` §6 (« M4 amorcé ») : à compléter au step
  `document` **une fois livré** — sans anticiper de comportement non implémenté (pas de statistiques
  client fabriquées).

## Affected Files / Packages / Modules

**Backend — à modifier :**
- `backend/coiflink_api/domain/appointment.py` — `CLIENT_HISTORY_STATUSES` (+ `__all__` si exporté).
- `backend/coiflink_api/adapters/inbound/appointments.py` — route `GET /appointments/history`
  (`APPOINTMENT_READ_OWN`, filtre `CLIENT_HISTORY_STATUSES`), docstring/`responses`.
- *(Si ordre serveur descendant retenu)* `backend/coiflink_api/application/ports/
  appointment_repository.py` et `backend/coiflink_api/adapters/outbound/persistence/
  appointment_repository.py` — paramètre d'ordre optionnel sur `list_for_client`.

**Backend — à lire (contexte) :** `adapters/inbound/appointments.py::list_my_appointments` (patron
route d'appartenance + `APPOINTMENT_READ_OWN`) ; `application/appointments.py::ListMyAppointments` ;
`adapters/outbound/persistence/appointment_repository.py::list_for_client` ;
`adapters/inbound/security.py` (`require_permission`, `PUBLIC_ROUTE_PATHS`, `unprotected_routes`) ;
`domain/permissions.py` (matrice `CLIENT`) ; `domain/appointment.py` (`REVENUE_STATUSES`).

**Mobile — à modifier :**
- `app-mobile/lib/application/ports/appointment_gateway.dart` — méthode `myHistory`.
- `app-mobile/lib/adapters/data/http_appointment_gateway.dart` — implémentation `myHistory`.
- `app-mobile/lib/application/use_cases/list_my_appointment_history.dart` — **nouveau** cas d'usage.
- `app-mobile/lib/adapters/ui/appointments/appointment_history_screen.dart` — **nouvel** écran.
- `app-mobile/lib/adapters/ui/app.dart` — instanciation, lanceur, bouton « Mon historique ».
- *(Éventuel)* `app-mobile/lib/adapters/ui/booking/booking_labels.dart` — réutilisation
  `formatFullDate` (+ helper de montant si mutualisé).

**Mobile — à lire (contexte) :** `adapters/ui/appointments/my_appointments_screen.dart` (patron
écran) ; `adapters/data/http_appointment_gateway.dart::myAppointments` (patron gateway) ;
`application/use_cases/list_my_appointments.dart` ; `domain/appointment/{appointment,
appointment_status}.dart` ; `application/auth_session.dart`.

**Docs :** ADR (numéro/forme à confirmer) + `docs/adr/README.md`, `backend/README.md`,
`app-mobile/README.md` (+ READMEs de couche). **`prd-coiflink.md` : ne pas modifier.** Récit
`README.md` §6 : à compléter au step `document` **après** livraison.

**Non touchés :** `web-dashboard/` (historique gérant déjà livré #29), schéma de données (aucune
migration).

## API / Interface Changes

**Nouvelle route backend** (protégée, jamais publique, route d'**appartenance**) :

- `GET /appointments/history` — **client** (`APPOINTMENT_READ_OWN`). **Aucun** paramètre de statut
  accepté (filtre `COMPLETED` **forcé serveur**). Réponse `200` : `list[AppointmentResponse]` (RDV
  `COMPLETED` du client, prestations + `price_at_booking`) ; `401` jeton absent/invalide/expiré ;
  `403` rôle insuffisant (identiques, aucun oracle). Documentation OpenAPI (docstring + `responses`).
  *(Ordre d'affichage : voir Data Model / Open Questions.)*

**Réutilisé tel quel :** `AppointmentResponse` (porte déjà `status`, `date`, horaires,
`services[].price_at_booking`). **Aucune modification** des routes client existantes (`GET /appointments`
reste « actifs »).

**Interface mobile (Flutter) — surface interne au paquet :** ajout de `AppointmentGateway.myHistory`,
du cas d'usage `ListMyAppointmentHistory`, de l'écran `AppointmentHistoryScreen` et d'un bouton
d'accueil. Aucune interface publiée hors du paquet.

**Alternative d'API (Open Questions) :** paramètre `?status=COMPLETED` (ou `?history=true`) sur
`GET /appointments` au lieu d'une route dédiée. **Recommandation : route dédiée** (filtre serveur
non négociable — l'acceptation « rien d'autre » —, pas de statut arbitraire côté client).

## Data Model / Protocol Changes

**Aucune.** Les colonnes `appointments.status` (`CHECK` enum incluant `COMPLETED`),
`appointments.appointment_date`/`start_time`/`end_time`, et la jonction `appointment_services.
price_at_booking` **existent depuis #3**. #30 **lit** ces lignes filtrées par `status = 'COMPLETED'`
et `client_id = principal.id` — **ni table, ni migration, ni colonne, ni contrainte**. Le contrat de
fil (`AppointmentResponse`) est **inchangé**.

**Ordre de lecture (protocole d'affichage, pas de schéma).** `list_for_client` trie **croissant**
aujourd'hui. Si l'historique doit s'afficher **du plus récent au plus ancien**, l'ordre est soit
appliqué **côté mobile** (aucun changement de protocole), soit paramétré côté serveur (paramètre
d'ordre optionnel, défaut inchangé). **À trancher** (voir Open Questions) — aucun impact sur les
données persistées.

## Security & Privacy Considerations

- **Appartenance & isolation (§11.2/§11.3).** Route d'**appartenance** : `require_permission(
  APPOINTMENT_READ_OWN)` puis filtre serveur `client_id = principal.id`. Un client ne voit **que ses
  propres** RDV — jamais ceux d'un tiers, jamais `owner_id`/donnée de gestion (l'`AppointmentResponse`
  ne porte que les données du RDV du client). Aucun paramètre client ne peut élargir la portée.
- **Filtre serveur non contournable (acceptation « rien d'autre »).** Le statut `COMPLETED` est
  **imposé serveur** (`CLIENT_HISTORY_STATUSES`) : le client ne soumet **aucun** statut. Impossible,
  par construction, d'obtenir un RDV `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` via cette route.
- **Deny-by-default (ADR-0015).** Route **protégée** (jamais dans `PUBLIC_ROUTE_PATHS`) ; refus
  `401`/`403` **constants et génériques** (aucun oracle d'existence). Invariant `unprotected_routes(
  app)` reste vide (test existant).
- **Jeton & journalisation (§11.1).** Côté mobile, le jeton transite en en-tête `Authorization` et
  n'est **jamais** journalisé ; l'adapter data ne journalise **ni** URL, **ni** corps, **ni** PII ;
  les échecs deviennent des exceptions **neutres** (`UnauthorizedException`,
  `AppointmentGatewayException`). Côté backend, aucun log ne porte de PII.
- **Montants.** Les montants affichés sont les `price_at_booking` **figés** (déjà persistés) — donnée
  du RDV du client, pas un secret ; aucun calcul, aucun agrégat, aucun reçu.
- **Budgets §12.** Lecture indexée (`ix_appointments_client_id`) + jonction prestations ; volume
  d'historique faible au MVP — bien en deçà du budget API (< 3 s). *(Si le volume croît, la pagination
  est une évolution — voir Open Questions.)*
- **Résidence/hébergement** : inchangés (ADR-0011). Aucun secret manipulé ni journalisé.

## Testing Plan

Test gate : `pytest` (backend) + `flutter test` (mobile). Les tests existants restent **verts**
(extensions **additives**). Convention backend : tests **Postgres** *skip proprement* sans
`DATABASE_URL` ; unitaires via **fakes** (`app.dependency_overrides`). Convention mobile : **faux**
gateway/use case injectés, aucun accès réseau réel.

**Backend :**
- **API/HTTP** `tests/test_appointment_api.py` (étendre, `TestClient` + fakes) :
  - `GET /appointments/history` : `200` **ne renvoie que** les RDV `COMPLETED` du client (jamais un
    `PENDING`/`CONFIRMED`/`CANCELLED`/`NO_SHOW` — acceptation « rien d'autre ») ; le corps porte
    `status="COMPLETED"`, prestations et `price_at_booking`.
  - **Appartenance** : les RDV d'un **autre** client ne remontent **jamais** (fake filtrant par
    `client_id`).
  - **RBAC** : `401` sans jeton ; `403` pour un rôle non-`CLIENT` (gérant/coiffeur) — messages
    **identiques** aux autres refus (aucun oracle).
  - **Non-régression** : `GET /appointments` continue de ne renvoyer **que** les actifs
    (`PENDING`/`CONFIRMED`).
  - **Invariant deny-by-default** : `unprotected_routes(app)` reste **vide**, **sans** ajouter le
    chemin à `PUBLIC_ROUTE_PATHS`.
- **Unit — domaine** `tests/test_domain_appointment.py` (étendre) : `CLIENT_HISTORY_STATUSES ==
  (COMPLETED,)` (et, si distincte, cohérente avec `REVENUE_STATUSES`).
- **Intégration Postgres** `tests/test_appointment_*` (skip sans `DATABASE_URL`, si un e2e est jugé
  utile) : semer un client avec des RDV de statuts variés → `GET /appointments/history` ne renvoie que
  les `COMPLETED`, prestations/`price_at_booking` corrects, ordre attendu (selon décision d'ordre).

**Mobile :**
- **Adapter** `test/http_appointment_gateway_test.dart` (étendre) : `myHistory` → `200` mappe la liste
  (statut/prestations/montants) ; `401` → `UnauthorizedException` ; non-2xx → `AppointmentGateway
  Exception` ; corps illisible → message neutre ; l'en-tête `Authorization: Bearer` est posé ; le
  jeton n'apparaît dans **aucune** exception.
- **Cas d'usage** `test/list_my_appointment_history_test.dart` (**nouveau**) : délègue au faux gateway,
  propage la liste et les exceptions neutres.
- **Écran** `test/appointment_history_screen_test.dart` (**nouveau**, patron des widget tests
  existants) : chargement (spinner) → liste (cartes « Terminé » + prestations/montants) ; **vide**
  (message dédié) ; **non authentifié** → `onRequireLogin` déclenché ; `401` → invalidation session +
  invite à se reconnecter ; **erreur réseau** → message + réessayer ; **aucun** bouton
  modifier/annuler rendu (lecture seule).
- **Non-régression** : les tests de `MyAppointmentsScreen`/`myAppointments` restent verts.

## Documentation Updates

- **ADR** (numéro/forme à **confirmer** au step `document`) + entrée `docs/adr/README.md` : route
  d'appartenance `GET /appointments/history`, filtre `COMPLETED` **forcé serveur**, lecture seule,
  montants figés (aucun calcul), sans nouveau schéma, résumé/statistiques différés (#31), frontière
  avec l'historique **gérant** #29.
- **`backend/README.md`** : entrée `GET /appointments/history` (client, `COMPLETED` seul,
  appartenance, RBAC).
- **`app-mobile/README.md`** (+ READMEs `adapters/ui`, `adapters/data`) : écran « Mon historique »,
  chemin gateway `myHistory`.
- **`README.md`** (récit §6, « M4 amorcé ») : compléter au step `document` **après** livraison —
  **ne pas anticiper** de comportement non implémenté (ni statistiques client, ni reçu).
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).
- **OpenAPI** : docstring + `responses` sur la nouvelle route (généré par FastAPI).

## Risks and Open Questions

- **Forme d'API : route dédiée vs paramètre.** *Recommandation : route dédiée `GET
  /appointments/history` à filtre serveur.* Alternative : `GET /appointments?status=COMPLETED` (ou
  `?history=true`). Le risque du paramètre : ouvrir un **filtre de statut arbitraire** au client
  (contraire à « rien d'autre » si mal borné). **À confirmer.**
- **Ordre d'affichage (récent → ancien).** `list_for_client` trie **croissant**. Options : (a) trier
  côté mobile (aucun changement backend) ; (b) paramètre d'ordre optionnel sur `list_for_client`
  (défaut inchangé) ; (c) méthode de port dédiée. *Recommandation : (b) ordre descendant serveur pour
  l'historique.* **À confirmer.**
- **Constante `CLIENT_HISTORY_STATUSES` vs réutilisation `REVENUE_STATUSES`.** Les deux valent
  `(COMPLETED,)` au MVP. *Recommandation : constante nommée distincte* (les concepts « visible dans
  l'historique client » et « comptabilisé au CA » peuvent diverger). **À confirmer.**
- **Cas d'usage mobile dédié vs paramètre `history`.** *Recommandation : `ListMyAppointmentHistory`
  dédié* (lecture claire, symétrie du port). Alternative : `ListMyAppointments(history: true)`. **À
  confirmer.**
- **Résumé/statistiques côté client.** L'acceptation n'exige **que** la liste (« rien d'autre »). Un
  résumé (nombre de visites, dernière visite, total) — comme #29 côté gérant — relève de #31.
  *Recommandation : hors périmètre #30.* **À confirmer.**
- **Pagination / bornes de dates.** Non exigées ; volume faible au MVP. *Recommandation : lecture
  simple non paginée*, pagination = évolution ultérieure si nécessaire. **À noter.**
- **Point d'entrée UI.** Bouton « Mon historique » distinct sur l'accueil (recommandé) vs onglet/
  filtre au sein de « Mes rendez-vous ». *Recommandation : écran distinct* (lecture seule, sémantique
  claire). **À confirmer.**
- **ADR propre vs extension.** `docs/adr/` s'arrête à `0026` (à **vérifier** au step `document`) — un
  ADR court est recommandé mais une extension d'ADR rendez-vous existant est acceptable. **À
  confirmer.**
- **Reflet du passage `COMPLETED` (dépendance #25).** L'historique **n'a de contenu** que si des RDV
  ont été passés à `COMPLETED` par le gérant (#25). En l'absence de tels RDV, l'écran montre un état
  **vide** légitime — à **couvrir par test** (vide ≠ erreur). **À noter.**

## Implementation Checklist

1. **Lire** : `adapters/inbound/appointments.py::list_my_appointments` (route d'appartenance +
   `APPOINTMENT_READ_OWN`) ; `application/appointments.py::ListMyAppointments` ;
   `adapters/outbound/persistence/appointment_repository.py::list_for_client` ;
   `adapters/inbound/security.py` ; `domain/{appointment,permissions}.py` ;
   côté mobile `adapters/ui/appointments/my_appointments_screen.dart`,
   `adapters/data/http_appointment_gateway.dart::myAppointments`,
   `application/use_cases/list_my_appointments.dart`, `adapters/ui/app.dart`,
   `domain/appointment/{appointment,appointment_status}.dart`.
2. **Trancher les Open Questions structurantes** (forme d'API, ordre d'affichage, constante dédiée,
   cas d'usage mobile, résumé hors périmètre, point d'entrée UI, ADR) et les acter (ADR +
   `docs/adr/README.md`).
3. **Backend — domaine** : `CLIENT_HISTORY_STATUSES = (COMPLETED,)` (`domain/appointment.py`,
   `__all__` si exporté).
4. **Backend — route** : `GET /appointments/history` (`require_permission(APPOINTMENT_READ_OWN)`,
   filtre `CLIENT_HISTORY_STATUSES`, docstring/`responses`) ; **ne rien ajouter à
   `PUBLIC_ROUTE_PATHS`**. *(Si ordre serveur retenu : paramètre d'ordre optionnel sur
   `list_for_client` + `SqlAppointmentRepository`.)*
5. **Backend — tests** : API (filtre `COMPLETED` seul, appartenance, `401`/`403`, non-régression
   `GET /appointments`, `unprotected_routes` vide), domaine (constante), e2e Postgres optionnel.
6. **Mobile — port** : `AppointmentGateway.myHistory({accessToken})`.
7. **Mobile — adapter** : `HttpAppointmentGateway.myHistory` (miroir `myAppointments` : `GET
   /appointments/history`, `Authorization: Bearer`, `200/401/défaut`, `_appointmentFromJson`, jamais
   de journalisation jeton/URL/PII).
8. **Mobile — cas d'usage** : `ListMyAppointmentHistory` (`application/use_cases/`).
9. **Mobile — écran** : `AppointmentHistoryScreen` (lecture seule : date/horaires/statut « Terminé »/
   prestations + montants ; états chargement/vide/erreur/`401` ; pull-to-refresh ; **aucun** bouton
   modifier/annuler).
10. **Mobile — composition root** (`adapters/ui/app.dart`) : instancier le use case, lanceur
    `openMyHistory`, bouton « Mon historique » sur l'accueil.
11. **Mobile — tests** : adapter (`myHistory`), cas d'usage, écran (liste/vide/non-auth/`401`/erreur,
    lecture seule) ; non-régression `MyAppointmentsScreen`.
12. **Documentation** : ADR (+ `docs/adr/README.md`), `backend/README.md`, `app-mobile/README.md`
    (+ READMEs de couche).
13. **Garde-fous** : `pytest` + `flutter test` (et test gate agrégé) au vert ; filtre `COMPLETED`
    **forcé serveur** (aucun statut soumis client) ; route d'appartenance (`client_id` serveur) ;
    aucun secret/PII/jeton journalisé ; `unprotected_routes(app)` **vide** ; **aucune** statistique ni
    reçu fabriqués ; **aucune** signature IA dans le code/commits/PR.
