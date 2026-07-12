# ADR-0016 : Comptes employés — appartenance employé↔salon & création par le gérant

- **Statut** : Accepté
- **Date** : 2026-07-12
- **Décideurs** : équipe CoifLink
- **Issue** : #13 (US-1.4 — Création/invitation de comptes employés)
- **Référence PRD** : §6 (US-1.4), §4 / §4.1 (permission `EMPLOYEE_MANAGE`), §11.1 (anti-élévation de
  privilège), §11.2 (isolation par salon), §11.4 (audit — différé)
- **S'appuie sur** : [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default,
  gardes `require_permission` / `require_salon_scope`, portée salon), [ADR-0008](./0008-architecture-hexagonale.md)
  (hexagonal), [ADR-0009](./0009-orm-migrations-sqlalchemy-alembic.md) (SQLAlchemy 2.0 + Alembic),
  [ADR-0012](./0012-hachage-argon2-strategie-otp.md) (hachage argon2id)

## Contexte et problème

Après #12, le backend sait **authentifier** et **autoriser** (RBAC deny-by-default, isolation par
salon), mais **aucun gérant ne peut créer le compte d'un employé (coiffeur)** ni le rattacher à son
salon. Le rôle `HAIRDRESSER` existe dans le domaine et dans la matrice §4.1, mais l'inscription
(#8/#9) fixe le rôle à `CLIENT` ou `MANAGER` — jamais `HAIRDRESSER`.

Surtout, le schéma n'a **pas** de table d'appartenance employé↔salon. En attendant #13,
`SqlSalonScopeRepository` dérivait la portée d'un `HAIRDRESSER` des **rendez-vous qui lui sont
assignés** (ADR-0015, décision (e)) : un coiffeur **sans aucun RDV** avait une portée **vide** et « ne
voyait rien » — sûr, mais insuffisant pour un employé fraîchement créé. Ce suivi était **explicitement
rattaché à #13**.

L'US-1.4 demande donc : *« En tant que gérant, je veux inviter ou créer des employés afin de leur
donner accès au salon »*, avec pour **critère d'acceptation** : **un gérant crée un compte coiffeur ;
le coiffeur se connecte avec un périmètre restreint.**

## Options envisagées

- **Création directe avec mot de passe initial [retenue]** : le gérant fournit nom, téléphone et un
  mot de passe initial ; le compte `HAIRDRESSER` est créé et rattaché au salon. Satisfait l'AC sans
  dépendre d'un canal e-mail/SMS réel (différé M5).
- **Compte sans mot de passe utilisable + set-password via reset OTP (#11)** : plus proche d'une
  « invitation », mais l'infra SMS est un stub et le canal e-mail réel est différé (ADR-0006/0014) —
  le coiffeur ne pourrait pas fiablement recevoir son code au MVP.
- **Vrai flux d'invitation par jeton à usage unique envoyé par e-mail** : conforme au mot
  « invitation » du titre, mais **bloqué** par l'absence de canal e-mail transactionnel (M5).

## Décision

**(a) Nouvelle table d'appartenance `salon_members`** (migration `0002`, `down_revision="0001"`) :
`(id, salon_id, user_id, role, status, created_at, updated_at)`, FK `salons.id` / `users.id` en
`ON DELETE RESTRICT`, unicité `(salon_id, user_id)` (un compte n'est employé qu'une fois par salon) et
`(salon_id, id)` (cible de futures FK composites d'isolation), index sur `user_id` et `salon_id`. Le
`role` et le `status` sont stockés en `text` + `CHECK` **dérivé du domaine** (`Role` / `UserStatus`).
Elle devient la **source d'autorité de la portée** d'un employé.

**(b) La portée d'un `HAIRDRESSER` est lue depuis `salon_members`** (`WHERE user_id = … AND status =
'ACTIVE'`), **en remplacement** de la dérivation par RDV assignés. Conformément à l'invariant
d'ADR-0015, **seule la requête de `SqlSalonScopeRepository` change** : le port `SalonScopeRepository`
et toutes les gardes restent identiques. L'assignation d'un RDV reste gérée séparément par
`can_access_appointment` (inchangé). Un membre `INACTIVE` perd sa portée.

**(c) Endpoint protégé `POST /salons/{salon_id}/employees`**, gardé par la permission
`EMPLOYEE_MANAGE` (§4.1 — déjà attribuée au `MANAGER`, **pas** à l'`ADMIN`) **et** par la portée salon
(`require_salon_scope`). Un gérant ne crée un employé que sur **son** salon ; un accès hors périmètre
renvoie le `403` **générique** identique à un rôle insuffisant (aucun oracle d'existence). Le chemin
n'est **pas** ajouté à `PUBLIC_ROUTE_PATHS`.

**(d) Rôle `HAIRDRESSER` fixé côté serveur.** `CreateEmployeeRequest` ne déclare **aucun** champ
`role` ; le rôle est injecté au câblage du cas d'usage `CreateEmployee`, jamais lu du corps
(anti-élévation de privilège, PRD §11.1, cohérent avec `RegisterUser`). Le mot de passe initial est
**haché argon2id** ; jamais stocké/renvoyé/journalisé en clair.

**(e) Atomicité.** La création de l'utilisateur **et** l'écriture de l'appartenance passent par la
**même `Session`** (`flush` sans commit, commit piloté par `get_session`). Si `add_member` échoue
(doublon `(salon_id, user_id)` → `EmployeeAlreadyInSalon` → `409`), la requête est rollbackée →
**pas de compte orphelin** sans salon.

**(f) Connexion du coiffeur inchangée.** Aucune route dédiée : le flux existant `POST /auth/login`
(#10) authentifie tout compte `ACTIVE`. Le coiffeur peut changer son mot de passe via le reset OTP
(#11).

## Justification (compromis)

- **La création directe satisfait l'AC** (« crée un compte coiffeur ; le coiffeur se connecte ») sans
  dépendre d'un canal e-mail/SMS réel — le volet « invitation » (lien/jeton) reste une évolution
  documentée, réalisable quand l'e-mail transactionnel arrivera (M5).
- **L'appartenance fait autorité sur la portée**, pas les RDV : un employé « voit » son salon dès sa
  création (l'AC « périmètre restreint » devient vraie immédiatement), tout en restant **strictement
  isolé** — un coiffeur créé pour le salon A n'obtient **aucune** portée sur le salon B.
- **Aucune modification de contrat** : le port de portée et les gardes sont inchangés ; on réutilise
  `UserResponse` (aucun secret) et la traduction d'erreurs existante (`409`/`422`).

## Conséquences

- **Positives** : le rôle `HAIRDRESSER` reçoit enfin des comptes ; la portée d'un employé est
  **explicite et sûre** (deny-by-default) ; l'isolation inter-salons est écrite en base et appliquée
  au point unique existant ; le suivi « portée dérivée des RDV » d'ADR-0015 est **clos**.
- **Négatives / limites** :
  - un membre **`INACTIVE`** perd sa portée (le filtre exige `ACTIVE`) — retirer un employé d'un salon
    (statut d'appartenance) est distinct de désactiver son **compte** utilisateur ;
  - la **réutilisation d'un téléphone existant** (un client qui devient coiffeur) échoue en `409` : ni
    fusion ni ré-attribution silencieuse de rôle (éviterait une escalade) ;
  - le **cycle de vie complet** de l'employé (lister / modifier / désactiver / retirer) n'est **pas**
    couvert : `EMPLOYEE_MANAGE` le permettra à terme, mais l'AC de #13 se limite à la **création**.
- **Suivis** :
  - **journalisation d'audit persistée** des accès sensibles (PRD §11.4 « Création employé ») →
    **#52**. #13 émet au plus un log **non-PII** (id acteur, id salon, id compte créé, rôle) — jamais
    de secret ni de PII ;
  - **flux d'invitation par lien / jeton à usage unique** (e-mail) → différé à l'arrivée du canal
    e-mail transactionnel (M5, ADR-0006/0014) ;
  - **gestion (liste / modification / désactivation / retrait) d'employés** → issue de suivi
    ultérieure (hors AC #13).
