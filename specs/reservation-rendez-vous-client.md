# Réservation d'un rendez-vous côté client (US-3.1)

> Spécification de planification pour l'issue GitHub **#22 — US-3.1 : Réservation d'un rendez-vous
> (client)** (`feature` · Must · Effort M · PRD §6 Épic 3, §7.1, §8.1). **Dépend de #19** (consultation
> d'un salon côté client) **et de #21** (moteur de disponibilité & anti double-réservation).
> **Cette spec ne produit pas de code** : elle décrit l'approche à implémenter dans une phase ultérieure.
>
> Conventions du dépôt : contenu rédigé en **français** (PRD, README, ADR, commentaires Dart/Python),
> en-têtes de section en **anglais** (attendus par le gabarit ADW), identifiants techniques (noms de
> routes, champs JSON, symboles) inchangés. **Aucune signature IA** dans le code, les commits ou la PR.

## Problem Statement

Le PRD (§6 Épic 3, US-3.1) et le §7.1 posent le besoin : **« en tant que client, je veux réserver un
rendez-vous afin de garantir mon passage au salon »**, via un parcours guidé — **choix salon →
prestation → date → heure → commentaire optionnel → confirmation**. Les critères d'acceptation de
l'issue #22 sont : *un client réserve un créneau disponible ; statut initial `en attente` ; RDV lié à
un salon + ≥ 1 prestation*.

État actuel du dépôt :

- **Le socle base et le chemin d'écriture backend existent déjà.** L'issue #21 (US-3.7) a livré le
  moteur de disponibilité pur et le **chemin de réservation transactionnel** avec la garantie
  anti double-réservation portée par la contrainte d'exclusion PostgreSQL. Concrètement, l'API expose
  **déjà** les deux surfaces dont US-3.1 a besoin (voir *Relevant Repository Context*) :
  - `GET /catalog/salons/{salon_id}/availability?date=&service_id=&hairdresser_id=` (public) — créneaux
    **libres** ;
  - `POST /salons/{salon_id}/appointments` (client authentifié, `APPOINTMENT_BOOK`) — crée le RDV au
    statut **`PENDING`** (= « en attente »), lie ≥ 1 prestation, accepte un `client_note` optionnel.
  Les critères d'acceptation de #22 sont donc **déjà satisfaits au niveau du contrat HTTP** ; le
  backend ne requiert *en principe* aucune évolution (voir *API / Data Model* et *Open Questions*).
- **Côté client mobile, le parcours n'existe pas.** L'application Flutter (`app-mobile/`) sait
  aujourd'hui **rechercher/lister** les salons (#18) et **afficher la fiche** d'un salon (#19,
  horaires + prestations + badge `isBookable`). L'écran de fiche
  (`lib/adapters/ui/salon_detail_screen.dart`) contient un **point d'entrée honnête mais inerte** :
  le bouton « Réserver » n'ouvre **aucun flux** — il affiche un `SnackBar` « Réservation bientôt
  disponible ». Il n'y a **ni domaine rendez-vous, ni passerelle de réservation, ni écran de tunnel,
  ni couche d'authentification client** dans le paquet mobile.

Le gap que #22 comble : **le parcours de réservation côté client mobile** (§7.1) — brancher le bouton
« Réserver » sur un tunnel guidé (prestation → date → créneau → commentaire → confirmation) qui
**consomme les endpoints déjà livrés par #21**, gère les états (chargement, aucun créneau, conflit
`409`, erreur réseau) et affiche la confirmation avec le statut **« en attente »**. Ce parcours suppose
un **client authentifié** (le `POST` exige `APPOINTMENT_BOOK`) : la disponibilité ou non d'une couche
d'auth cliente dans le mobile est le principal point à trancher (voir *Risks and Open Questions*).

## Goals

- **Tunnel de réservation client (mobile, §7.1)** partant de la fiche salon (#19) : sélection d'**une
  (≥ 1) prestation**, choix d'une **date**, choix d'un **créneau libre** (alimenté par
  `GET .../availability`), **commentaire optionnel**, puis **confirmation** créant le RDV via
  `POST /salons/{salon_id}/appointments`.
- **Statut initial « en attente »** affiché sans ambiguïté : mapper la valeur backend `PENDING` vers un
  libellé client « En attente ».
- **RDV lié salon + ≥ 1 prestation** : la sélection impose au moins une prestation avant de pouvoir
  réserver (le backend refuse déjà `< 1` prestation, mais l'UI doit l'empêcher en amont).
- **Gestion honnête des états** : aucun créneau disponible (jour fermé/complet), créneau devenu pris
  entre l'affichage et la réservation (**`409`** → message clair + rafraîchissement des créneaux),
  salon non réservable (`409`, §8.3), erreurs réseau/serveur neutres, succès avec récapitulatif.
- **Anti-élévation & confidentialité préservés** : le client mobile n'envoie **jamais** de `client_id`,
  `salon_id` ou `status` dans le corps ; il n'affiche que ses propres données de RDV et **jamais**
  l'identité de qui occupe les créneaux pris (la disponibilité ne renvoie que les créneaux libres).
- **Remplacement du placeholder** : le bouton « Réserver » de la fiche salon ouvre réellement le
  tunnel (au lieu du `SnackBar` « bientôt disponible »).
- **Couverture de tests** : unités de domaine/passerelle mobiles + tests de widgets du tunnel
  (parcours nominal, conflit `409`, aucun créneau, erreur), en réutilisant le patron de fakes du paquet.

## Non-Goals

- **Modification / annulation d'un RDV côté client** (US-3.2 #23, US-3.3 #24) et l'écran « Mes
  rendez-vous » complet avec historique — hors périmètre ; #22 ne livre que l'**acte de réservation**
  et son récapitulatif de confirmation.
- **Confirmer/refuser & cycle de statuts côté gérant** (US-3.4 #25), **planning salon/coiffeur**
  (US-3.5 #26, US-3.6 #27), et toute **réservation walk-in par le gérant** depuis le dashboard web.
- **Notifications** de confirmation/rappel/annulation (§8.4, Épic 7 — #43+) : aucun envoi n'est ajouté
  ici ; l'étape « Notification » du §7.1 relève de l'Épic 7. La confirmation #22 est **à l'écran**.
- **Modification du moteur de disponibilité ou du chemin d'écriture backend** (#21) : réutilisés tels
  quels. **Aucune nouvelle table, migration ni contrainte** (le socle `appointments` /
  `appointment_services` / `EXCLUDE` existe depuis #3).
- **Sélection d'un coiffeur par le client** et **capacité de salon sans coiffeur** : décision produit
  ouverte (voir *Open Questions*) ; par défaut le tunnel MVP réserve **au niveau salon** (sans
  `hairdresser_id`).
- **Interface web (Next.js)** : US-3.1 est un parcours **client** (mobile). Le `web-dashboard/` n'est
  pas touché.

## Relevant Repository Context

### Stack & architecture

- **Backend** : FastAPI · Python ≥ 3.12 (ADR-0003) ; PostgreSQL 16 + SQLAlchemy 2.0 + Alembic
  (ADR-0009) ; **architecture hexagonale** ports & adapters (ADR-0008) ; RBAC **deny-by-default**
  (ADR-0015). Tests `pytest`.
- **Mobile** : Flutter stable / Dart ^3.12 (ADR-0001, ADR-0007), **même découpage hexagonal** que le
  paquet — `lib/domain`, `lib/application` (ports + use_cases), `lib/adapters/data` (HTTP) et
  `lib/adapters/ui` (écrans/widgets). Tests `flutter test`.
- **Test gate** agrégé (#6) : `scripts/test-gate.sh` enchaîne `pytest` / `npm test` / `flutter test`.

### Backend déjà livré par #21 (à réutiliser sans modification)

- `coiflink_api/adapters/inbound/appointments.py` — router :
  - `GET /catalog/salons/{salon_id}/availability` (**public**, ajouté à `PUBLIC_ROUTE_PATHS`) →
    `AvailabilityResponse { slots: [{date, start, end}] }`. Refuse un salon non réservable (`409`),
    prestation inactive/hors salon (`404`), exclut les créneaux passés (`now` serveur, Africa/Abidjan
    UTC+0). **Ne renvoie que les créneaux libres** (§11.3).
  - `POST /salons/{salon_id}/appointments` (**client** `APPOINTMENT_BOOK`) →
    `AppointmentResponse { id, salon_id, client_id, hairdresser_id, date, start_time, end_time,
    status, client_note, services:[{service_id, price_at_booking}] }` au statut `PENDING`. Corps
    `BookAppointmentRequest { date, start_time, service_ids:[≥1], hairdresser_id?, client_note? }` avec
    `extra="ignore"` — `client_id`/`salon_id`/`status` **jamais** lus du corps. Traductions :
    `SlotAlreadyBooked`/`SlotUnavailable`/`SalonNotBookable` → **409** ; `AppointmentServiceRequired` →
    **422** ; `ServiceNotFound`/`SalonNotFound`/`HairdresserNotInSalon` → **404**.
- `coiflink_api/application/appointments.py` — `CheckAvailability`, `BookAppointment` (défense en
  profondeur `is_offered`, écriture transactionnelle, `salon_id`/`client_id` imposés serveur).
- `coiflink_api/domain/availability.py`, `domain/appointment.py`, `domain/enums.py`
  (`AppointmentStatus.PENDING = "PENDING"`), `adapters/outbound/persistence/appointment_repository.py`,
  `docs/adr/0023-moteur-disponibilite-anti-double-reservation.md`.

### Backend auth client (déjà disponible — #8/#10)

- `coiflink_api/adapters/inbound/auth.py` (`prefix="/auth"`) : `POST /auth/register` (client),
  `POST /auth/login` (téléphone/e-mail + mot de passe → **JWT + refresh**), `POST /auth/refresh`,
  `GET /auth/me`. Un client obtient donc un jeton d'accès qui porte `APPOINTMENT_BOOK` — mais **rien
  côté mobile ne consomme encore ces routes**.

### Mobile déjà livré (#18/#19 — patrons à calquer)

- `lib/adapters/data/api_config.dart` — `ApiConfig.fromEnvironment()` (`API_BASE_URL` via
  `--dart-define`, jamais de secret), helper `resolve(path, queryParameters)`.
- `lib/application/ports/salon_catalog_gateway.dart` — port + exceptions **neutres**
  (`SalonCatalogException`, `SalonNotFoundException`, **jamais** d'URL signée ni de PII).
- `lib/adapters/data/http_salon_catalog_gateway.dart` — adapter HTTP (mapping JSON → domaine, échecs
  retraduits en exceptions neutres, **aucune journalisation** d'URL/PII).
- `lib/application/use_cases/{search_salons,get_salon_detail}.dart` — use cases fins.
- `lib/adapters/ui/salon_detail_screen.dart` — **fiche salon** avec le placeholder `_BookingCta`
  (à remplacer), `SalonService { id, name, description, price, durationMinutes, category }`.
- `test/` — patron de fakes (`Fake*Gateway`) et de tests de widgets (`salon_detail_screen_test.dart`).

### Statut actuel du parcours

**Aucune** couche mobile d'authentification, de rendez-vous ou de réservation n'existe : la seule
affordance de réservation est un bouton inerte. #22 doit donc **construire le tunnel mobile** et lui
fournir un **contexte authentifié** (le point ouvert clé).

## Proposed Implementation

Périmètre recommandé : **livrer le parcours client mobile** au-dessus des endpoints #21, **sans**
modifier le backend (sauf éventuel ajustement mineur tranché en *Open Questions*). Découpage hexagonal
du paquet mobile respecté.

### 1. Prérequis — contexte authentifié client (mobile)

Le `POST /salons/{salon_id}/appointments` exige un JWT client (`APPOINTMENT_BOOK`). Deux stratégies
(à **confirmer**, voir *Open Questions*) :

- **(A, recommandée) Livrer une couche d'auth cliente minimale** dans #22 : écran **Connexion**
  (§7.1 : téléphone/e-mail + mot de passe → `POST /auth/login`), stockage **sécurisé** du jeton
  (paquet `flutter_secure_storage` — **décision de dépendance à confirmer** ; ne jamais journaliser le
  jeton), et un `AuthSession`/`TokenStore` injectable. Le tunnel de réservation exige une session ; si
  absente, il **redirige vers Connexion** puis revient. (L'inscription §7.1 peut réutiliser
  `POST /auth/register` mais peut être minimisée à la connexion pour le MVP #22.)
- **(B) Supposer une session existante** fournie par une issue d'auth mobile séparée. **Risque** :
  aucune issue de ce type n'est listée comme dépendance de #22 (dépend de #19 et #21 seulement), et le
  paquet mobile n'a **pas** de couche d'auth — #22 serait alors bloqué. → *privilégier (A)* ou faire
  trancher le porteur produit.

Quel que soit le choix, la **passerelle de réservation** doit envoyer l'en-tête
`Authorization: Bearer <token>` et gérer **`401`** (jeton absent/expiré → invalider la session,
rediriger vers Connexion). Le jeton n'est **jamais** logué (§11).

### 2. Domaine mobile (`lib/domain/appointment/`)

Value objects Dart immuables (pas d'I/O, ADR-0008) :

- `AvailabilitySlot { DateTime date; String start; String end; }` — créneau libre (`HH:MM`).
- `BookedService { String serviceId; String priceAtBooking; }` — prestation réservée (prix figé).
- `Appointment { String id; String salonId; String? hairdresserId; DateTime date; String startTime;
  String endTime; AppointmentStatus status; String? clientNote; List<BookedService> services; }`.
- `enum AppointmentStatus { pending, confirmed, cancelled, completed, noShow }` + mapping depuis la
  chaîne backend (`"PENDING" → pending`) et libellé d'affichage (`pending → "En attente"`). Valeur
  inconnue tolérée (défaut prudent) pour ne pas casser sur une évolution serveur.

### 3. Application mobile (`lib/application/`)

- **Port** `ports/appointment_gateway.dart` :
  - `Future<List<AvailabilitySlot>> availableSlots({required String salonId, required DateTime date,
    required String serviceId, String? hairdresserId});`
  - `Future<Appointment> book({required String salonId, required BookingDraft draft});`
  - `BookingDraft { DateTime date; String startTime; List<String> serviceIds (≥1); String?
    hairdresserId; String? clientNote; }`.
  - Exceptions **neutres** dédiées, calquées sur `SalonCatalogException` :
    `AppointmentGatewayException` (réseau/serveur), `SlotTakenException` (**409** — créneau déjà pris),
    `NotBookableException` (**409** — salon non réservable / créneau hors offre), `UnauthorizedException`
    (**401**). **Jamais** d'URL, de jeton ni de PII dans les messages.
- **Use cases** `use_cases/check_availability.dart`, `use_cases/book_appointment.dart` : validations
  amont légères (≥ 1 prestation, date non passée) puis délégation au port. Garde le tunnel testable sans
  UI.

### 4. Adapter data mobile (`lib/adapters/data/http_appointment_gateway.dart`)

`HttpAppointmentGateway implements AppointmentGateway`, sur `ApiConfig` + `http.Client`, calqué sur
`HttpSalonCatalogGateway` :

- `availableSlots(...)` → `GET /catalog/salons/{salonId}/availability` avec `date`, `service_id`,
  `hairdresser_id?` ; **public** (pas d'en-tête d'auth requis) ; mappe `slots[]` → `AvailabilitySlot`.
- `book(...)` → `POST /salons/{salonId}/appointments`, corps JSON `{date, start_time, service_ids,
  hairdresser_id?, client_note?}` (**jamais** `client_id`/`salon_id`/`status`), en-tête
  `Authorization: Bearer <token>` (jeton fourni par la session). Mapping des codes :
  `201 → Appointment` ; `401 → UnauthorizedException` ; `409 → SlotTakenException`/`NotBookableException`
  (selon le message/détail, sans exposer le détail brut) ; `404 → AppointmentGatewayException`
  (« salon/prestation introuvable ») ; autre non-2xx → `AppointmentGatewayException` générique.
- **Aucune journalisation** d'URL, de corps, de jeton ni de PII (mêmes garde-fous que le gateway
  catalogue).

### 5. UI mobile — tunnel de réservation (`lib/adapters/ui/booking/`)

Écran(s) de tunnel guidé (un `Stepper`/pages successives, au choix du patron Flutter), ouverts depuis
la fiche salon. Étapes §7.1 :

1. **Choix prestation** — liste des `services` de la fiche (déjà chargée) ; sélection d'**au moins une**
   (MVP : *une seule* recommandé, voir *Open Questions* sur la disponibilité multi-prestations). Bouton
   « Continuer » désactivé tant que `< 1` prestation.
2. **Choix date** — sélecteur de date (aujourd'hui → horizon borné) respectant le fuseau UTC+0.
3. **Choix créneau** — appelle `CheckAvailability` pour `(salonId, date, serviceId)` ; affiche les
   créneaux **libres** en puces horaires ; états *chargement* / *aucun créneau ce jour-là* / *erreur
   réseau (réessayer)*.
4. **Commentaire optionnel** — champ `client_note` (longueur bornée, trim).
5. **Confirmation** — récapitulatif (salon, prestation(s), date, créneau, note) + bouton « Confirmer » ;
   appelle `BookAppointment`. Sur succès → écran de **confirmation** affichant le statut **« En
   attente »** et le récapitulatif du RDV créé. Sur **`409`** → message « Ce créneau vient d'être pris,
   choisissez-en un autre » + **retour à l'étape 3 avec rafraîchissement** des créneaux. Sur **`401`** →
   redirection vers Connexion. Sur salon non réservable → message §8.3.

Modifier `salon_detail_screen.dart` : remplacer `_BookingCta` inerte par une navigation réelle vers le
tunnel (conservant le comportement désactivé quand `isBookable == false`). Câbler la composition
(gateways, session) dans `lib/adapters/ui/app.dart` / `lib/main.dart`.

### 6. Documentation & ADR

- **ADR** : rédiger **ADR-0024 — Réservation côté client (tunnel mobile & session cliente)** actant :
  réutilisation des endpoints #21 (backend inchangé), stratégie d'auth cliente retenue (A vs B) et
  stockage sécurisé du jeton, périmètre mono/multi-prestations et coiffeur du tunnel MVP, mapping du
  statut `PENDING → « En attente »`, gestion du `409`. Indexer dans `docs/adr/README.md`.
- **`app-mobile/README.md`** : section « Réservation » (parcours, `--dart-define` d'`API_BASE_URL`,
  prérequis d'auth). **`prd-coiflink.md` : ne pas modifier** (source de vérité).
- Mettre à jour le récit README §6 (M3 en cours) *si* la convention du dépôt le veut — sinon laisser au
  step `document`.

## Affected Files / Packages / Modules

**À créer (mobile) :**
- `app-mobile/lib/domain/appointment/appointment.dart`, `.../availability_slot.dart`,
  `.../appointment_status.dart` (value objects + enum + libellés).
- `app-mobile/lib/application/ports/appointment_gateway.dart` (port + exceptions neutres + `BookingDraft`).
- `app-mobile/lib/application/use_cases/check_availability.dart`, `.../book_appointment.dart`.
- `app-mobile/lib/adapters/data/http_appointment_gateway.dart`.
- `app-mobile/lib/adapters/ui/booking/` (écrans du tunnel + widgets de créneaux/récapitulatif).
- *(Si stratégie A)* couche d'auth minimale : `lib/domain/auth/…`, `lib/application/ports/auth_gateway.dart`
  + `token_store.dart`, `lib/adapters/data/http_auth_gateway.dart`, `lib/adapters/ui/auth/login_screen.dart`.
- `docs/adr/0024-reservation-cote-client.md` (+ entrée `docs/adr/README.md`).
- Tests (voir *Testing Plan*).

**À modifier (mobile) :**
- `app-mobile/lib/adapters/ui/salon_detail_screen.dart` — `_BookingCta` → navigation réelle vers le tunnel.
- `app-mobile/lib/adapters/ui/app.dart` et/ou `lib/main.dart` — composition (gateways, session, routes).
- `app-mobile/pubspec.yaml` — *(si retenu)* `flutter_secure_storage` (décision de dépendance).
- `app-mobile/README.md` — section réservation.

**À lire (contexte) :** `http_salon_catalog_gateway.dart`, `salon_catalog_gateway.dart`,
`api_config.dart`, `salon_detail_screen.dart`, `salon_service.dart`, `test/salon_detail_screen_test.dart`
(patrons) ; côté backend : `adapters/inbound/appointments.py`, `application/appointments.py`,
`adapters/inbound/auth.py`, `domain/enums.py`.

**Backend :** *aucune modification requise* pour satisfaire les critères de #22 (voir *Open Questions*
pour l'unique ajustement optionnel — disponibilité multi-prestations).

## API / Interface Changes

**Aucune nouvelle route backend n'est nécessaire.** #22 **consomme** les endpoints livrés par #21 et
l'auth livrée par #8/#10 :

- `GET /catalog/salons/{salon_id}/availability?date=YYYY-MM-DD&service_id=…&hairdresser_id=…` (public).
- `POST /salons/{salon_id}/appointments` (client `APPOINTMENT_BOOK`, corps sans
  `client_id`/`salon_id`/`status`) → `201` RDV `PENDING`.
- `POST /auth/login` → JWT (contexte authentifié du tunnel).

**Interfaces internes mobiles nouvelles** (paquet-privées, non publiques réseau) : port
`AppointmentGateway` (+ `BookingDraft`, exceptions), use cases `CheckAvailability`/`BookAppointment`,
et — selon la stratégie A — `AuthGateway`/`TokenStore`. Documentées par docstrings Dart.

**Ajustement backend optionnel (à trancher)** : si le tunnel MVP autorise **plusieurs** prestations, la
route de disponibilité (qui prend un **unique** `service_id`) devrait accepter plusieurs `service_id`
pour refléter la **durée cumulée**, sinon les créneaux proposés seraient trop courts. *Recommandation
MVP : restreindre le tunnel à une prestation* et **ne pas** modifier l'API (voir *Open Questions*).

## Data Model / Protocol Changes

**Aucune.** Les tables `appointments` / `appointment_services`, la colonne générée `slot tsrange`,
l'extension `btree_gist` et la contrainte d'exclusion `ex_appointments_hairdresser_slot` existent
depuis #3 et sont exploitées par le chemin d'écriture #21. #22 n'ajoute **ni table, ni migration, ni
colonne, ni contrainte**. Le contrat JSON (availability, appointment, login) est **inchangé** ; le
mobile n'ajoute que des modèles de désérialisation **côté client** (Dart), sans format de fil nouveau.

Le jeton d'accès (stratégie A) est stocké **localement sur l'appareil** via un magasin sécurisé
(Keychain/Keystore) — c'est un **stockage client**, pas un changement de schéma serveur.

## Security & Privacy Considerations

- **Anti-élévation (§11.2)** : le corps de réservation n'accepte **jamais** `client_id`, `salon_id` ni
  `status` — imposés serveur (déjà garanti par `extra="ignore"` côté backend #21). Le mobile ne les
  envoie pas et ne tente pas de les forcer.
- **Anti double-réservation = intégrité base (§8.1)** : la garantie reste portée par la contrainte
  d'exclusion PostgreSQL ; le mobile ne fait qu'une **aide UX** (n'affiche que des créneaux libres) et
  doit **traiter le `409`** comme le verdict final (créneau perdu) — jamais tenter de contourner.
- **Confidentialité (§11.3)** : la disponibilité ne renvoie que des créneaux libres ; le mobile
  n'affiche **jamais** l'identité de qui occupe un créneau. Le client ne voit que **ses** propres RDV.
- **Gestion du jeton (§11.1)** : le JWT est stocké dans un **magasin sécurisé** de la plateforme
  (jamais en clair dans les préférences), transmis en en-tête `Authorization`, et **jamais journalisé**.
  `401` → invalidation locale + reconnexion. `API_BASE_URL` reste injecté au build (`--dart-define`),
  **jamais un secret** (patron #18).
- **Messages neutres** : les exceptions mobiles (`AppointmentGatewayException`, `SlotTakenException`,
  `UnauthorizedException`, …) portent des messages génériques — **aucune** URL, jeton, corps de
  requête, détail de transport ni PII. Aucune journalisation de ces éléments (garde-fou identique au
  gateway catalogue).
- **§8.3 respecté** : le tunnel ne s'ouvre que sur un salon `isBookable` (fiche #19) et le backend
  refuse toute réservation sur un salon non `ACTIVE`/sans horaire (`409`).
- **Résidence/hébergement** : inchangés (ADR-0011) ; aucune donnée nouvelle exfiltrée.

## Testing Plan

Test gate mobile : `flutter test`. Convention du dépôt : fakes injectés, **aucun** appel réseau réel
en test (patron `Fake*Gateway`). Les tests existants (catalogue #18/#19, backend #21) doivent rester
verts et **ne pas** être modifiés.

- **Unit — domaine mobile** `test/appointment_domain_test.dart` : mapping `"PENDING" → pending` et
  libellé « En attente » ; valeur de statut inconnue tolérée ; construction/égalité des value objects ;
  désérialisation d'un `Appointment`/`AvailabilitySlot` depuis un JSON représentatif.
- **Unit — passerelle HTTP** `test/http_appointment_gateway_test.dart` (avec `http` mocké /
  `MockClient`) : `availableSlots` mappe `slots[]` ; `book` envoie l'en-tête `Authorization`, **omet**
  `client_id`/`salon_id`/`status`, mappe `201 → Appointment`, `409 → SlotTaken/NotBookable`,
  `401 → Unauthorized`, `404`/réseau → exception neutre ; **aucun** message ne contient jeton/URL/PII.
- **Unit — use cases** `test/book_appointment_test.dart`, `test/check_availability_test.dart` (fakes) :
  refus `< 1` prestation en amont ; propagation propre de `SlotTakenException` ; date passée refusée.
- **Widget — tunnel** `test/booking_flow_test.dart` : parcours nominal (prestation → date → créneau →
  note → confirmation « En attente ») ; **`409`** → message + retour à l'étape créneaux rafraîchie ;
  *aucun créneau* → état vide honnête ; erreur réseau → réessayer ; bouton « Confirmer » désactivé sans
  prestation. `salon_detail_screen_test.dart` : le bouton « Réserver » ouvre le tunnel (et reste
  désactivé si `isBookable == false`).
- *(Si stratégie A)* `test/login_flow_test.dart` : connexion émet/enregistre un jeton (fake `TokenStore`)
  et le tunnel redirige vers Connexion sans session ; **le jeton n'apparaît dans aucun log**.
- **Backend** : *pas de nouveau test requis* si le backend n'est pas modifié. Si l'ajustement
  « disponibilité multi-prestations » est retenu (*Open Questions*), ajouter les tests correspondants
  (`test_appointment_api.py`) — durée cumulée reflétée, rétro-compatibilité mono-`service_id`.
- **Documentation** : revue que `app-mobile/README.md` documente le parcours et le prérequis d'auth.

## Documentation Updates

- **`docs/adr/0024-reservation-cote-client.md`** (nouveau) + entrée **`docs/adr/README.md`** : stratégie
  d'auth cliente (A/B), backend inchangé, périmètre mono/multi-prestations & coiffeur du tunnel MVP,
  mapping `PENDING → « En attente »`, gestion `409`/`401`, stockage sécurisé du jeton.
- **`app-mobile/README.md`** : section « Réservation » (parcours §7.1, `--dart-define=API_BASE_URL`,
  prérequis session cliente, garde-fous de non-journalisation).
- **`README.md`** (récit §6, « M3 en cours ») : à compléter au step `document` une fois livré — **ne pas
  anticiper** de comportement non implémenté.
- **`prd-coiflink.md`** : **ne pas modifier** (source de vérité produit).
- **OpenAPI** : inchangé (aucune route backend nouvelle), sauf si l'ajustement multi-prestations est retenu.

## Risks and Open Questions

- **Auth cliente mobile (bloquant)** : la réservation exige un JWT client, or le paquet mobile n'a
  **aucune** couche d'auth et #22 ne dépend (backlog) que de #19 et #21. **Faut-il livrer une connexion
  cliente minimale dans #22 (stratégie A) ou existe-t-il/faut-il créer une issue d'auth mobile séparée
  (stratégie B) ?** *Recommandation : livrer une connexion minimale (A) réutilisant `POST /auth/login`,
  sinon #22 est bloqué.* **À confirmer (porteur produit).**
- **Mono- vs multi-prestations dans le tunnel** : le backend accepte `≥ 1` prestation (durée = somme),
  mais la route de disponibilité prend un **unique** `service_id`. Autoriser plusieurs prestations dans
  l'UI **sans** adapter la disponibilité proposerait des créneaux trop courts. *Recommandation MVP :
  **une seule** prestation par réservation cliente (cohérent avec la disponibilité, backend inchangé) ;*
  le multi-prestations viendrait avec un ajustement d'API ultérieur. **À confirmer.**
- **Sélection d'un coiffeur par le client** : §8.1 autorise un RDV lié à un coiffeur « si le salon
  active cette option », mais **aucun endpoint public ne liste les coiffeurs d'un salon**, et la
  garantie anti-doublon ne s'applique **qu'avec** un `hairdresser_id`. *Recommandation MVP : réserver
  **au niveau salon** (`hairdresser_id` nul), l'assignation d'un coiffeur relevant du gérant (US-3.4
  #25) ;* documenter que, sans coiffeur, la contrainte d'exclusion base ne s'applique pas (conforme
  §8.1). **À confirmer (décision produit).**
- **Récapitulatif de confirmation vs « Mes rendez-vous »** : #22 affiche la confirmation à partir de la
  **réponse du `POST`** (aucun besoin de lecture supplémentaire). Un écran « Mes rendez-vous » complet
  (lecture `APPOINTMENT_READ_OWN`) est **hors périmètre** (#23/#24 en auront besoin) — confirmer qu'il
  reste différé.
- **Dépendance `flutter_secure_storage`** (ou équivalent) pour le stockage sécurisé du jeton : nouvelle
  dépendance mobile — à valider (sécurité, poids, plateformes). Alternative : stockage en mémoire pour
  le MVP (session perdue au redémarrage). **À confirmer.**
- **Fuseau horaire** : le backend raisonne en Africa/Abidjan = **UTC+0** (schéma `tsrange`, #16/#21). Le
  mobile doit construire dates/heures dans ce repère (pas le fuseau du terminal) pour rester cohérent
  avec la disponibilité et éviter des décalages de créneaux. **À expliciter à l'implémentation.**
- **Horizon de réservation** (nombre de jours ouverts à la sélection de date) : non spécifié par le PRD ;
  choisir une borne raisonnable (p. ex. 30–60 j) et la documenter. **À confirmer.**
- **`class SalonService` mobile** : `durationMinutes`/`price` sont **nullables** dans le modèle actuel ;
  le tunnel doit gérer proprement une prestation sans durée/prix affichable (peu probable car le backend
  #17 impose durée + prix, mais défensif). **À vérifier.**

## Implementation Checklist

1. **Lire** : `http_salon_catalog_gateway.dart`, `salon_catalog_gateway.dart`, `api_config.dart`,
   `salon_detail_screen.dart`, `salon_service.dart`, `test/salon_detail_screen_test.dart` (patrons
   mobiles) ; backend `adapters/inbound/appointments.py`, `application/appointments.py`,
   `adapters/inbound/auth.py`, `domain/enums.py`.
2. **Trancher les Open Questions structurantes** (auth cliente A/B, mono vs multi-prestations, coiffeur,
   dépendance de stockage sécurisé, horizon de date) et les acter dans **ADR-0024** (+
   `docs/adr/README.md`).
3. *(Si stratégie A)* **Auth cliente minimale** : `AuthGateway` (`POST /auth/login`), `TokenStore`
   (magasin sécurisé, jeton jamais logué), écran **Connexion** (§7.1), gestion `401`.
4. **Domaine mobile** : `Appointment`, `AvailabilitySlot`, `BookedService`, `AppointmentStatus` +
   mapping `PENDING → « En attente »` (valeur inconnue tolérée).
5. **Port** : `AppointmentGateway` (`availableSlots`, `book`, `BookingDraft`) + exceptions **neutres**
   (`AppointmentGatewayException`, `SlotTakenException`, `NotBookableException`, `UnauthorizedException`).
6. **Use cases** : `CheckAvailability`, `BookAppointment` (validations amont ≥ 1 prestation / date non
   passée, délégation au port).
7. **Adapter data** : `HttpAppointmentGateway` — `GET .../availability` (public) + `POST
   .../appointments` (en-tête `Authorization`, corps sans `client_id`/`salon_id`/`status`), mapping des
   codes (`201`/`401`/`409`/`404`/réseau), **aucune journalisation** d'URL/jeton/PII.
8. **UI tunnel** : écrans prestation → date → créneau → commentaire → confirmation (états chargement /
   aucun créneau / `409` rafraîchi / `401` redirigé / succès « En attente »).
9. **Câblage** : remplacer `_BookingCta` inerte de `salon_detail_screen.dart` par la navigation réelle ;
   composition (gateways, session, routes) dans `app.dart`/`main.dart` ; conserver le bouton désactivé
   si `isBookable == false`.
10. **Tests** : domaine, passerelle HTTP (mock), use cases (fakes), tunnel (widget) et — si stratégie A
    — connexion ; asserter **anti-élévation** (corps sans champs privilégiés) et **non-journalisation**
    du jeton/PII. `flutter test` vert.
11. **Documentation** : ADR-0024 + `docs/adr/README.md` + section `app-mobile/README.md`.
12. **Garde-fous** : `flutter test` (et test gate agrégé) au vert ; aucun secret/jeton/PII journalisé ;
    corps de réservation sans `client_id`/`salon_id`/`status` ; contrainte d'exclusion base **jamais**
    contournée ; **aucune** signature IA dans le code/commits/PR.
