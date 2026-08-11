# ADR-0042 : File d'attente walk-in — ticket de passage `QueueTicket` indépendant d'`Appointment`, numérotation par salon+jour & estimation d'attente V1

- **Statut** : Accepté
- **Date** : 2026-08-11
- **Décideurs** : équipe CoifLink
- **Issue** : #157 (US-8.3 · Ticket de passage walk-in & estimation d'attente) — jalon **M7** (Borne
  client, Épic 8)
- **Référence PRD** : §4.1 (permissions par rôle), §8.1 (rendez-vous ≥ 1 prestation), §11.2 (isolation
  par salon), §11.3 (non-fuite PII), §11.4 (journalisation), §17 (Borne Intelligente d'Accueil)
- **S'appuie sur** : [ADR-0041](./0041-authentification-borne-kiosque.md) (#155, rôle `KIOSK` +
  `QUEUE_TICKET_CREATE`), [ADR-0040](./0040-impression-recu-encaissement-gerant.md) (#154, numérotation
  séquentielle par salon — verrou consultatif transactionnel + `MAX+1`),
  [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (#12, RBAC deny-by-default),
  [ADR-0026](./0026-fiche-client-portee-salon.md) (#28, anti-oracle fiche client)
- **Spec de planification** : [`specs/us-8-3-ticket-passage-walkin-estimation-attente.md`](../../specs/us-8-3-ticket-passage-walkin-estimation-attente.md)

## Contexte et problème

Le jalon M7 (PRD §17) livre le parcours « client sans rendez-vous » : #155 dote la borne d'une identité
(`KIOSK`), #156 lui donne de quoi identifier un client (recherche téléphone / création walk-in). Il
manque la **pièce centrale** : délivrer au client identifié un **numéro de passage**, une **estimation
d'attente**, et le faire apparaître dans la file du personnel pour qu'il soit pris en charge.

Deux faits du dépôt (état vérifié au commit `4320171`) structurent la décision :

1. **`Appointment.client_id` est `NOT NULL` (FK `users`).** Un walk-in obtient, dans le cas général,
   une `CustomerProfile` **sans compte** (`user_id = NULL`) ; l'entité de domaine `Customer` n'expose
   même pas `user_id` (anti-oracle ADR-0026). Un ticket walk-in ne peut donc **pas** devenir une ligne
   `appointments` sans exiger un compte (contradiction avec le walk-in) ou assouplir le schéma.
2. **La seule « file d'attente » livrée (#150/#152) est un outil de pointage sur RDV déjà planifiés** :
   `domain/queue.py` dérive un statut d'un `Appointment` réel — aucune notion de numéro de passage,
   d'estimation d'attente ni de client sans RDV n'existe.

## Décision

### 1. Un domaine `QueueTicket` **indépendant d'`Appointment`**, migration additive dédiée

Nouvelle entité pure `domain/queue_ticket.py` + deux tables (`queue_tickets`, `queue_ticket_services`,
migration `0014` strictement **additive**). Aucune ligne `appointments`/`services`/`customer_profiles`
n'est modifiée. `QueueTicket.customer_profile_id` est **nullable** (ticket anonyme possible) ;
`hairdresser_id` référence `users.id` (identifiant de compte, appartenance salon vérifiée
**applicativement**, miroir exact d'`Appointment.hairdresser_id`). Cycle de vie fermé
`waiting → called → in_progress → done` (+ `expired`), machine à états pure miroir d'`AppointmentStatus`.

**Alternative écartée** : réutiliser `appointments` avec un pseudo-`client_id` (compte technique
« walk-in »). Rejetée — il polluerait toutes les lectures « mes rendez-vous » et casserait l'hypothèse
`client_id → un seul client réel` exploitée par stats/notifications/historique.

### 2. Numérotation séquentielle par salon **et** jour civil, sûre en concurrence (patron ADR-0040)

`ticket_number` redémarre à 1 chaque jour civil du salon (`Africa/Abidjan`). `SqlQueueTicketRepository.
create` décline exactement le patron `receipt_number` : `SELECT pg_advisory_xact_lock(hashtext(:key))`
(clé `salon_id:issued_date`) puis `MAX(ticket_number)+1` dans la **même** transaction, `flush` sans
`commit`. La contrainte `UNIQUE (salon_id, issued_date, ticket_number)` est le filet ultime (course
improbable → `IntegrityError`, jamais une corruption). Pas de nouvelle table de compteur, pas de job de
purge — le compteur reparte à 1 par la seule clé de verrou/`WHERE`.

**Alternative écartée** : une séquence PostgreSQL nommée par salon redémarrée par cron — DDL dynamique
par salon (potentiellement des milliers de séquences) + dépendance à un ordonnanceur absent du dépôt.

### 3. Formule V1 d'estimation d'attente, explicite et bornée

`estimate_wait_minutes(position, average_service_minutes, active_hairdresser_count)` =
`position × durée moyenne des prestations des tickets actifs (waiting + in_progress) ÷ coiffeuses
ACTIVE`, arrondie (jamais tronquée). Filets pour les cas dégénérés : aucune coiffeuse active →
constante documentée (`DEFAULT_WAIT_MINUTES_NO_STAFF = 30`, **jamais** de division par zéro) ; file
encore vide → repli sur la moyenne des prestations **de ce ticket** ; aucune durée exploitable → `0`.
L'estimation est **calculée une fois à l'émission** et **stockée telle quelle** (jamais recalculée en
lecture) : le ticket imprimé (#160) affiche une valeur **stable** même si la file évolue. Heuristique
**assumée perfectible** (pas de progression réelle des prestations en cours, pas de spécialité de
coiffeuse, aucune donnée historique).

### 4. Visibilité gérant par **fusion en lecture**, jamais en écriture

`GET /salons/{salon_id}/queue` **évolue** d'une `list[QueueEntryResponse]` vers un objet à deux clés
`{appointments, walk_in_tickets}`. `appointments` reprend **champ à champ** l'ancien contenu (aucune
régression du contrat RDV) ; `walk_in_tickets` compose une **troisième source**
(`QueueTicketRepository.list_active_for_salon`, tickets du jour hors `expired`) **sans jamais** créer,
mettre à jour ni référencer une ligne `appointments`. Les deux tableaux restent **distincts** (un
walk-in n'a ni `appointment_id` ni créneau ; tri par `ticket_number` vs `start_time`). Rupture de forme
**mineure et assumée** : le consommateur unique (`web-dashboard/.../queue-board.tsx`) est mis à jour
dans la même PR.

### 5. Gardes RBAC — **réutilisation**, aucune nouvelle permission

- « Rejoindre la file » (`POST /salons/{id}/queue/tickets`) : `require_salon_scope` +
  `require_permission(QUEUE_TICKET_CREATE)` — permission **déjà** détenue par le seul `KIOSK` (#155).
- Prise en charge / clôture (`.../start`, `.../complete`) : `require_salon_scope` +
  `require_permission(APPOINTMENT_UPDATE_STATUS)` — **mêmes acteurs** (coiffeuse + gérant) que le
  démarrage d'un RDV. Aucune permission dédiée `QUEUE_TICKET_MANAGE` créée : la matrice
  `ROLE_PERMISSIONS` n'est pas modifiée.

Aucune route n'entre dans `PUBLIC_ROUTE_PATHS` : « public/kiosk » qualifie l'usage (un terminal en
salle d'accueil), pas le régime d'authentification (deny-by-default inchangé).

### 6. Journalisation ciblée

`QUEUE_TICKET_STARTED`/`QUEUE_TICKET_COMPLETED` (entité `queue_ticket`, `metadata={}`) tracent les
**actions humaines** de prise en charge/clôture (miroir `APPOINTMENT_STARTED`). L'**émission** d'un
ticket par la borne n'est **pas** journalisée au journal d'audit gérant (aucune action humaine de
gestion, aucune PII propre au ticket).

## Conséquences

- **Positif** : parcours walk-in complet et cohérent sans toucher au chemin d'écriture éprouvé de la
  réservation (#21/#22) ; numérotation robuste réutilisant un patron déjà en production ; PII minimisée
  à l'écran partagé (prénom seul, aligné #156) ; aucune nouvelle frontière de transaction ni de droit.
- **Limites assumées (V1)** : l'estimation d'attente est heuristique ; le walk-in **ne pèse pas** dans
  les statistiques revenu/fréquentation (qui s'appuient sur `Appointment`/`Payment.appointment_id`) —
  un travail de schéma dédié serait nécessaire s'il le fallait, hors #157 ; l'**expiration** d'un ticket
  oublié (`waiting → expired`) est un statut **atteignable** mais non déclenché automatiquement (aucun
  ordonnanceur dans le dépôt) ; le **rate-limiting** de la création de tickets relève de la garde
  `KIOSK` (#155) ou d'un middleware transverse, à vérifier avant généralisation.
- **Suivis** : facturation liée au ticket (aucun `ticket_id` sur `Payment` — l'encaissement walk-in
  reste un encaissement `service_id`-only classique, déjà possible) ; notifications au client walk-in
  (M7 assume un ticket **papier** #160) ; affinage de l'ETA (données historiques).
