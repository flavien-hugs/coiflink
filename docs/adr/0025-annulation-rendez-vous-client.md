# ADR-0025 : Annulation d'un rendez-vous côté client — transition d'état soft, motif optionnel & invariant CA

- **Statut** : Accepté
- **Date** : 2026-07-23
- **Décideurs** : équipe CoifLink
- **Issue** : #24 (US-3.3 — Annulation d'un rendez-vous, client)
- **Référence PRD** : §6 Épic 3 (US-3.3), §7.1 (parcours client), §8.1 (annulation selon la règle du
  salon ; RDV annulé exclu du chiffre d'affaires), §11.2 (anti-élévation), §11.3 (confidentialité),
  §11.4 (journalisation d'audit)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default),
  [ADR-0019](./0019-journalisation-audit-et-prestations.md) (audit §11.4),
  [ADR-0023](./0023-moteur-disponibilite-anti-double-reservation.md) (exclusion base = anti-doublon),
  [ADR-0024](./0024-reservation-cote-client.md) (tunnel & session cliente) et le **chemin de
  modification livré par #23** (ownership → verrou d'état → écriture conditionnelle → audit)

## Contexte et problème

Le PRD (§8.1) pose deux règles : *« un client peut annuler selon les règles définies par le salon »* et
*« un rendez-vous annulé ne doit pas être comptabilisé dans le chiffre d'affaires »*. Les critères
d'acceptation de #24 sont : **annulation avec motif optionnel** ; **RDV annulé exclu du CA**.

Le socle existe déjà (schéma #3) : la table `appointments` porte `status` (enum incluant `CANCELLED`),
**`cancellation_reason`** (`Text` nullable) et `updated_at` (`onupdate`). La contrainte d'exclusion
anti double-réservation **et** `booked_slots` ne portent que sur `status IN ('PENDING','CONFIRMED')` :
un RDV annulé **n'occupe plus** le créneau. Ce qui manquait : un **chemin d'annulation** (cas d'usage,
port, route), une action d'audit dédiée et l'affordance mobile. #24 comble ce gap **sans nouveau
schéma**.

## Décision

1. **Annulation = transition d'état *soft*, pas une suppression.** Un client authentifié fait passer
   **son** RDV **actif** (`PENDING`/`CONFIRMED`) à **`CANCELLED`** ; la ligne et ses jonctions
   `appointment_services` (prix figé) sont **conservées** (audit/historique/CA futur). La route est une
   **sous-ressource d'action** : `POST /appointments/{id}/cancellation`. Un `DELETE` serait trompeur
   (annulation ≠ suppression) et un `PATCH {status}` romprait l'anti-élévation — c'est **la route** qui
   décide de la transition, jamais un `status` soumis.

2. **Motif optionnel, persisté mais jamais journalisé (§11.3).** Le corps ne porte qu'un `reason`
   optionnel, normalisé (`normalize_cancellation_reason` : trim, vide → `None`, borne de robustesse
   **500** avec **troncature** silencieuse — le motif est un confort, jamais un blocage). Il est écrit
   dans `cancellation_reason` **sur la propre ligne du client** mais **jamais** journalisé (ni
   `logging`, ni message d'exception, ni **métadonnées d'audit**). Le contrat `AppointmentResponse`
   n'ajoute **pas** `cancellation_reason` (surface minimale — l'écho du motif relève d'un besoin futur).

3. **Verrou d'état ré-affirmé à l'écriture (garde TOCTOU).** Un RDV terminé/terminal (`COMPLETED`,
   déjà `CANCELLED`, `NO_SHOW`) est **non annulable par le client** → `AppointmentNotCancellable`
   (**409**). Le verrou est décidé par une règle de domaine **pure**
   (`is_client_cancellable`/`CLIENT_CANCELLABLE_STATUSES`, constante **distincte** de
   `CLIENT_MODIFIABLE_STATUSES` — deux règles métier séparées, même si le jeu d'états coïncide au MVP)
   **et** ré-affirmé par un **UPDATE conditionnel** `WHERE id = … AND status IN ('PENDING','CONFIRMED')`.
   Une double annulation est un **409** (cohérent avec le verrou), pas un `200` idempotent. L'exception
   gérant (annuler un RDV terminé) relève d'US-3.4/#25.

4. **Libération automatique du créneau (aucun code dédié).** Par construction, un RDV `CANCELLED` sort
   de l'ensemble actif de l'exclusion base **et** de `booked_slots` : son créneau **redevient
   disponible** dans le moteur de disponibilité (#21). L'annulation **libère** un créneau et ne peut
   donc jamais violer l'exclusion. Garantie **vérifiée par test** e2e (réservation d'un nouveau RDV sur
   le créneau libéré).

5. **« Exclu du CA » = invariant documenté, pas un calcul.** Aucun agrégat de chiffre d'affaires n'est
   livré au MVP (encaissement M4 #28–#38, KPI gérant M5 US-6.2). #24 **ne fabrique aucun calcul de CA** :
   il garantit l'état `CANCELLED` et **matérialise l'invariant** par un prédicat de domaine pur
   `counts_towards_revenue(status)` (retourne `False` pour `CANCELLED`/états non réalisés) que les
   issues M4/M5 devront réutiliser — le CA ne comptera **que** les RDV réalisés (`COMPLETED`) /
   paiements validés, **jamais** un RDV annulé.

6. **Permission réutilisée : `APPOINTMENT_BOOK`.** Cohérent avec la matrice §4.1 **inchangée** (« le
   client réserve/modifie/annule ses RDV ») et avec la modification #23. Route **protégée** (jamais
   ajoutée à `PUBLIC_ROUTE_PATHS`) ; un `CLIENT` n'ayant **aucune portée salon**, la route **n'utilise
   pas** `require_salon_scope` — l'appartenance (`client_id == principal.id`) est validée **dans le cas
   d'usage** (`get_owned`, isolation §11.2 en SQL). Un RDV inexistant **ou** d'autrui est un **404
   indiscernable** (aucun oracle).

7. **Journalisation `APPOINTMENT_CANCELLED` neutre (§11.4).** Chaque annulation écrit une `AuditEntry`
   (acteur = `client_id`, portée = `salon_id` du RDV chargé, entité = l'`appointment`) dans la **même**
   unité de travail que l'écriture métier (patron #17/#20/#23). Les `metadata` sont **neutres** :
   `{"reason_provided": bool}` (le *fait* qu'un motif ait été fourni n'est pas une PII ; son **contenu**,
   si — donc jamais tracé).

8. **Annulation toujours possible sur un RDV actif (§8.3).** Le cas d'usage n'exige **ni** catalogue
   **ni** portée : il ne re-valide **pas** la disponibilité et reste possible **même si le salon est
   devenu non réservable/inactif** — on n'empêche jamais un client d'annuler son RDV.

9. **« Selon les règles du salon » : au MVP, aucun cutoff.** Aucun champ de politique d'annulation
   (délai/pénalité/fenêtre) n'existe au schéma ni au PRD. Tout RDV **actif** est annulable. Une politique
   configurable relèverait d'une décision produit + configuration salon (hors périmètre S).

10. **Notification différée (§8.4 → Épic 7).** La table PRD §6 mentionne « Notification au salon » ; ce
    câblage relève de l'Épic 7 (#43+). #24 n'émet **aucune** notification : l'audit §11.4 est une
    **trace interne**, pas une notification.

11. **Mobile : affordance « Annuler » dans « Mes rendez-vous ».** Un bouton **désactivé** pour un RDV
    non annulable (miroir d'affichage `isClientCancellable` — le serveur reste juge) ouvre une
    **confirmation** avec un champ **motif facultatif** ; au succès, la liste se rafraîchit (le RDV
    annulé quitte la liste des RDV actifs). Nouvelle exception **neutre** `NotCancellableException`
    (`409`) ; le motif et le jeton ne sont **jamais journalisés**.

## Conséquences

- **Positives** : les critères d'acceptation de #24 (annulation avec motif optionnel ; RDV annulé exclu
  du CA) sont couverts **sans** nouveau schéma ; le créneau se libère **mécaniquement** (exclusion base) ;
  l'invariant CA est verrouillé par un prédicat de domaine réutilisable (M4/M5) ; le découpage hexagonal
  et les garde-fous §11.2/§11.3/§11.4 sont préservés ; le chemin d'écriture #23 est étendu, pas dupliqué.
- **Négatives / suivis** : un RDV annulé **disparaît** de « Mes rendez-vous » (`GET /appointments`
  filtre `PENDING`/`CONFIRMED`) — l'historique des RDV annulés relève d'US-4.4/#30 ; l'annulation est
  **terminale** côté client (reprogrammer = nouveau RDV) ; **aucune notification** (Épic 7) ; **aucun
  calcul de CA** n'est livré (invariant seulement) ; la **politique d'annulation configurable** par le
  salon reste ouverte ; la session mobile reste **en mémoire** (ADR-0024).
