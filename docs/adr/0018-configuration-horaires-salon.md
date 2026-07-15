# ADR-0018 : Configuration des horaires d'ouverture — contrat JSONB & activation de la réservabilité

- **Statut** : Accepté
- **Date** : 2026-07-15
- **Décideurs** : équipe CoifLink
- **Issue** : #16 (US-2.2 — Configuration des horaires d'ouverture)
- **Référence PRD** : §6 (Épic 2, US-2.2), §4.1 (permission `SALON_UPDATE`), §7.2 (Paramètres :
  informations / **horaires** / jours fermés / photos / localisation), §8.3 (réservabilité : « sans
  horaire ⇒ non réservable »), §9.2 (colonne `opening_hours`), §11.2 (isolation par salon), §11.3
  (PII, non-journalisation), §12 (budget latence/stockage)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal — validation dans le
  domaine, pas en `CHECK` SQL), [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC
  deny-by-default), [ADR-0017](./0017-creation-salon-medias-et-reservabilite.md) (création du salon,
  `is_bookable` dérivé/jamais persisté, `opening_hours` laissé `NULL` à la création)

## Contexte et problème

La création d'un salon est livrée (#15) : le salon naît `status=ACTIVE` avec `opening_hours=NULL`, donc
`is_bookable=false` (§8.3). La colonne JSONB `salons.opening_hours` existe (schéma #3) et est déjà
**lue** par `GET /salons` / `GET /salons/{id}`, mais **aucune route ni cas d'usage ne permet de
l'écrire** : la colonne reste définitivement `NULL` et aucun salon ne peut devenir réservable, ce qui
bloque tout M3 (rendez-vous). Le PRD §9.2 nomme la colonne mais **ne spécifie pas sa structure
interne**.

US-2.2 demande de configurer les horaires (horaires par jour, jours fermés, pauses, jours
exceptionnels), avec pour critères : **(1)** horaires enregistrés par salon ; **(2)** un salon sans
horaire ne peut pas recevoir de réservation (§8.3).

## Décision

1. **Contrat JSONB fixé** (nouveau) : `opening_hours` sérialise une structure **versionnée** —
   `{ version, timezone, weekly, exceptions }`. `weekly` est un objet `{ jour: [intervalle] }` (clés
   ⊂ `mon..sun`, jour absent ⇒ fermé) ; chaque intervalle est `{ start, end }` en `HH:MM` 24h ;
   `exceptions` est une liste de surcharges **datées** `{ date, closed, intervals }`. Les **pauses**
   sont l'écart entre deux intervalles d'un même jour.

2. **Validation dans le domaine pur** (`domain/opening_hours.py`, ADR-0008), jamais en `CHECK` SQL :
   heures bien formées, `end > start` (pas de passage minuit au MVP), intervalles triés et **non
   chevauchants** (l'adjacence `end == start` est tolérée), dates d'exception **distinctes**,
   cohérence `closed`/`intervals`, **bornes de robustesse** (≤ 6 intervalles/jour, ≤ 366 exceptions),
   et **non-vacuité utile** (au moins un créneau d'ouverture). Toute incohérence → `InvalidOpeningHours`
   (→ `422`), message neutre (ni PII, ni détail SQL).

3. **`is_bookable` reste structurel & inchangé** : `ACTIVE et bool(opening_hours)` (ADR-0017). La règle
   de **non-vacuité** garantit qu'aucun JSONB « vide/faussement configuré » n'est persisté ; ce
   prédicat ne peut donc pas mentir. Aucune logique de *réservation* (créneaux, disponibilité) n'est
   ajoutée — cela relève de #21+.

4. **Route protégée, sémantique *replace*** : `PUT /salons/{salon_id}/opening-hours`, gardée par
   `require_permission(SALON_UPDATE)` **et** `require_salon_scope` (isolation §11.2, `403` générique
   hors périmètre). Un `PUT` remplace intégralement les horaires (idempotent). **Aucune** route
   publique, aucun ajout à `PUBLIC_ROUTE_PATHS`, aucune permission nouvelle.

5. **Fuseau mono-région** : `timezone` par défaut `Africa/Abidjan` (Côte d'Ivoire, UTC+00), stocké mais
   **non éditable dans l'UI** au MVP — le champ existe pour #21+.

## Conséquences

- **Aucune migration de structure** : la colonne existe déjà (#3) et était toujours `NULL` (aucune
  donnée à migrer ni rétro-valider).
- **Parité front/back** : un validateur TypeScript miroir (`web-dashboard`) reproduit les règles pour
  l'UX ; le **backend reste l'autorité**. Risque de divergence mitigé par des tests de parité.
- **Déconfiguration** (repasser un salon à non réservable) : **hors périmètre** — la désactivation d'un
  salon passe par `status` (M5/M6), pas par la suppression d'horaires.
- **Limites assumées** (à réévaluer si un cas réel l'exige) : pas de passage minuit (`22:00–02:00` se
  modélise en deux jours), pas de fermetures récurrentes annuelles (les exceptions sont **datées**).
