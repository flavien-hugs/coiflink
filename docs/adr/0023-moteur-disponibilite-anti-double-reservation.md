# ADR-0023 : Moteur de disponibilité & anti double-réservation — garantie portée par la contrainte d'exclusion base, moteur pur au-dessus

- **Statut** : Accepté
- **Date** : 2026-07-20
- **Décideurs** : équipe CoifLink
- **Issue** : #21 (US-3.7 — Moteur de disponibilité & anti double-réservation)
- **Référence PRD** : §8.1 (« un créneau ne peut pas être réservé deux fois pour le même coiffeur » ;
  « ≥ 1 prestation » par RDV), §6 Épic 3 (US-3.7), §8.3 (salon non réservable), §11.2/§11.3 (isolation,
  PII), §12 (budget latence)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0009](./0009-orm-migrations-sqlalchemy-alembic.md) (PostgreSQL 16, SQLAlchemy 2.0, psycopg 3),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, liste blanche testée),
  [ADR-0018](./0018-configuration-horaires-salon.md) (contrat JSONB des horaires),
  [ADR-0019](./0019-journalisation-audit-et-prestations.md) (prestations, durée),
  [ADR-0020](./0020-catalogue-salons-cote-client.md) / [ADR-0021](./0021-consultation-salon-cote-client.md)
  (ressource `/catalog`, port de lecture `ACTIVE`-only, route publique)

## Contexte et problème

Le socle base de données (#3, migration `0001_schema_initial`) porte **déjà** la règle d'intégrité
§8.1 : les tables `appointments`/`appointment_services`, la colonne générée `slot tsrange`, l'extension
`btree_gist` et la **contrainte d'exclusion** `ex_appointments_hairdresser_slot`
(`EXCLUDE USING gist (hairdresser_id WITH =, slot WITH &&) WHERE (hairdresser_id IS NOT NULL AND status
IN ('PENDING','CONFIRMED'))`). Mais **aucune couche applicative** n'exploitait ce socle : ni moteur de
disponibilité, ni chemin d'écriture de réservation, ni route HTTP. Le gap de #21 : la logique
domaine/application/adapters qui (1) calcule les créneaux libres et (2) crée un RDV en traduisant
proprement la course concurrente perdue.

## Décision

1. **La garantie anti double-réservation vient de la base, pas de l'application.** Le juge de dernier
   ressort est la contrainte d'exclusion `ex_appointments_hairdresser_slot`. Sous `READ COMMITTED`
   (défaut SQLAlchemy), deux INSERT concurrents de créneaux qui se chevauchent pour le **même
   coiffeur** déclenchent l'attente puis l'**échec** du second (SQLSTATE `23P01`). L'application ne
   « gagne » jamais la course : elle **traduit** l'échec en `SlotAlreadyBooked` → `409`. Aucune
   élévation à `SERIALIZABLE`, aucun verrou applicatif, aucun `check-then-insert` comme unique rempart.

2. **Moteur pur au-dessus (`domain/availability.py`).** Fonctions sans I/O (ADR-0008) : `SlotRange`,
   `overlaps`, `intervals_for_date`, `free_slots`, `is_offered`, `add_minutes`. Sémantique de
   chevauchement **fermé-ouvert** `[start, end)` — l'adjacence `end == start` **n'est pas** un conflit
   (miroir de `&&` sur `tsrange` et de l'adjacence tolérée des horaires #16). Une **exception datée**
   (#16) **prime** sur le programme hebdomadaire (fermée ⇒ aucun créneau ; ouverte ⇒ ses intervalles).
   Les créneaux **passés** sont exclus quand `now` est fourni.

3. **Fuseau Africa/Abidjan = UTC+0.** Cohérent avec le choix `tsrange` (non-`tstzrange`) du schéma et le
   défaut #16. `now` est un `datetime` **naïf** dans ce repère. Si un fuseau à décalage était introduit,
   le choix `tsrange`/`timestamp` du schéma devrait être revu (suivi).

4. **Granularité fixe MVP = 15 min, non exposée.** La grille de créneaux (`DEFAULT_GRANULARITY_MINUTES`)
   est un paramètre du domaine mais **n'est pas** exposée dans l'API : disponibilité **et** réservation
   partagent la même grille — un créneau réservé est nécessairement l'un de ceux que la disponibilité a
   proposés (`is_offered` rejette un créneau mal aligné). Cela ferme un contournement possible
   (réserver « entre » les créneaux) sans complexité produit supplémentaire.

5. **Multi-prestations : `end_time = start + Σ(durées)`.** Une réservation porte **≥ 1** prestation
   (`require_services`, §8.1) et occupe un créneau continu dont la longueur est la **somme** des durées
   (`compute_end_time`, refus si le créneau franchit minuit). Chaque `BookedService` fige
   `price_at_booking` (un changement de tarif ne réécrit pas l'historique).

6. **Frontière : moteur + chemin de réservation minimal.** #21 livre le **cas d'usage réutilisable**
   (`CheckAvailability`, `BookAppointment`) et **une** route de réservation qui rend l'anti-doublon
   testable — **pas** le tunnel client complet US-3.1 (choix guidé, confirmations/rappels), qui se
   **superposera** en réutilisant le cas d'usage.

7. **Coiffeur requis pour bénéficier de la garantie.** La contrainte d'exclusion ne s'applique qu'aux
   RDV `hairdresser_id NOT NULL`. Un RDV **sans coiffeur** est autorisé au MVP mais **sans** garantie de
   capacité (option (c) du spec). La gestion d'une capacité de salon sans coiffeur assigné relève d'une
   décision produit distincte (suivi).

8. **Surface & sécurité des routes.**
   - **Disponibilité** — `GET /catalog/salons/{salon_id}/availability` (date, service_id,
     hairdresser_id?) : **publique** (ajout **conscient et revu** à `PUBLIC_ROUTE_PATHS`, patron
     #18/#19). Lecture seule ; n'expose **que** les créneaux **libres**, **jamais** l'identité de qui
     occupe les créneaux pris (§11.3). Un salon non `ACTIVE`/inconnu → `404` (sans oracle) ; non
     réservable (§8.3) → `409` ; prestation inactive/hors salon → `404`.
   - **Réservation** — `POST /salons/{salon_id}/appointments` : **protégée** `APPOINTMENT_BOOK`
     (client). `client_id = principal.id`, `salon_id` du chemin — **jamais** du corps (anti-élévation,
     `extra="ignore"`). Un `CLIENT` n'ayant **aucune portée salon**, la route **n'utilise pas**
     `require_salon_scope` (qui renverrait `403`) : la validation « salon réservable » est faite par le
     cas d'usage.

9. **Codes HTTP.** `SlotAlreadyBooked` (course perdue) / `SlotUnavailable` (hors offre) /
   `SalonNotBookable` (§8.3) → **409** (conflit d'état) ; `AppointmentServiceRequired` → **422** ;
   `ServiceNotFound`/`SalonNotFound` → **404** (après portée). Erreurs de domaine **neutres** (ni PII ni
   détail SQL) ; l'`IntegrityError` psycopg brute **n'est jamais journalisée** (elle peut porter des
   identifiants de ligne) — on inspecte SQLSTATE `23P01` / le nom de contrainte puis on lève une erreur
   neutre.

**Aucune migration Alembic** : tout le schéma nécessaire existe (#3). L'index existant
`ix_appointments_salon_id (salon_id, appointment_date)` couvre la requête `booked_slots` ; aucun index
additif n'est ajouté tant qu'aucun besoin n'est démontré (budget §12).

## Conséquences

- **Positives** : la garantie d'unicité est **atomique et immunisée contre le TOCTOU** (portée base,
  testée en concurrence — deux transactions/HTTP simultanés → exactement une réussite) ; le moteur pur
  est testable sans base (jours fermés, pauses, exceptions, adjacence, créneaux passés) ; disponibilité
  et réservation partagent la même grille (pas de contournement d'alignement) ; le cas d'usage est
  réutilisable par le tunnel US-3.1 et par une réservation walk-in gérant.
- **Négatives / suivis** : le **tunnel client complet** (US-3.1) et les **transitions de statut**
  (US-3.2/3.3/3.4), les **plannings** (US-3.5/3.6) et les **notifications** (§8.4) restent hors
  périmètre ; la **capacité de salon sans coiffeur** est différée (option MVP : coiffeur requis pour la
  garantie) ; les **tests de concurrence** sont **spécifiques PostgreSQL** (`btree_gist` + `EXCLUDE`) et
  **skip** sans `DATABASE_URL` (ils ne peuvent pas s'exécuter sur SQLite) ; l'hypothèse **UTC+0** doit
  rester explicite si un fuseau à décalage est introduit plus tard.
