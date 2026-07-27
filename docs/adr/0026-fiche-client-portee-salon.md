# ADR-0026 : Fiche client — portée salon, genre optionnel & unicité du téléphone

- **Statut** : Accepté
- **Date** : 2026-07-24
- **Décideurs** : équipe CoifLink
- **Issue** : #28 (US-4.1 — Création d'une fiche client, gérant)
- **Référence PRD** : §6 Épic 4 (US-4.1), §7.2 (section « Clients » du dashboard gérant), §9.5
  (table `customer_profiles`), §11.2 (isolation par salon), §11.3 (données personnelles : collecte
  minimale, consentement, journalisation des accès sensibles, chiffrement « si nécessaire »),
  §11.4 (journalisation des actions importantes)
- **S'appuie sur** : [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0009](./0009-orm-migrations-sqlalchemy-alembic.md) (ORM & migrations),
  [ADR-0015](./0015-autorisation-rbac-deny-by-default.md) (RBAC deny-by-default, portée salon),
  [ADR-0019](./0019-journalisation-audit-et-prestations.md) (audit §11.4) et le **patron de ressource
  de salon livré par #17** (`/salons/{salon_id}/…` → portée → tranche hexagonale → audit)

## Contexte et problème

Le PRD (§6 Épic 4, US-4.1) demande : *« en tant que gérant, je veux créer une fiche client afin de
suivre ses visites »*, avec pour spécification *« nom, téléphone, genre optionnel, notes internes »*.
Le critère d'acceptation de #28 est : **le gérant crée une fiche rattachée à son salon ; isolation par
salon (§11.2)**. C'est le **premier module « gestion clients »** : #29 (historique), #31 (statistiques),
#32 (note privée) et #49 (campagnes) en dépendent.

L'état du dépôt avant #28 :

- la table **`customer_profiles` existe au schéma** (migration `0001`, PRD §9.5) — `salon_id`,
  `user_id` **nullable** (« supporte les clients walk-in »), `full_name`, `phone`, `notes`,
  `last_visit_at`, `total_visits` — mais **n'a jamais été écrite** : aucun writer dans le code ;
- il **manque la colonne `gender`**, exigée par l'issue ;
- la permission **`CUSTOMER_MANAGE` existe dans la matrice §4.1** (détenue par le seul `MANAGER`) mais
  **n'est câblée sur aucune route** ;
- la section web **« Clients » est `coming-soon`**, sans page.

Ce module manipule des **données personnelles** (nom, téléphone, genre, notes pouvant relever de la
santé — le PRD US-4.5 cite les allergies) : c'est sa principale sensibilité, et ce qui motive plusieurs
décisions ci-dessous.

## Décision

1. **Ressource imbriquée sous le salon, portée imposée par le chemin.** Les routes vivent sous
   `/salons/{salon_id}/customers` pour hériter de `require_salon_scope` (isolation §11.2). Le
   `salon_id` provient **toujours du chemin validé**, jamais du corps : `CreateCustomerRequest` est
   `extra="ignore"` — un `salon_id`, `id`, `user_id`, `total_visits` ou `last_visit_at` présent dans le
   corps est **ignoré** (anti-élévation, miroir de #15/#17).

2. **Isolation en profondeur, sans oracle d'existence.** En plus de la garde de portée, le dépôt
   **refiltre `salon_id` en SQL** sur toute lecture d'une fiche existante : une fiche d'un autre salon
   est **indiscernable d'une fiche inexistante**. Un accès inter-salons reçoit le `403` **générique et
   constant** (`« Accès refusé. »`), identique à celui d'un rôle insuffisant ; le `404` n'est renvoyé
   qu'**après** validation de portée.

3. **Fiche walk-in : `user_id` reste `NULL` et n'est pas exposé.** #28 ne rattache **pas** la fiche à
   un compte utilisateur. Un rattachement automatique « par téléphone » est **écarté pour raison de
   sécurité** : interroger `users` par numéro transformerait la route en **oracle d'existence de
   compte** (§11.1/§11.3) — un gérant pourrait tester des numéros arbitraires et apprendre qui possède
   un compte CoifLink. Pour la même raison, `user_id` **n'apparaît pas** dans les réponses. L'index
   unique partiel `uq_customer_profiles_salon_user` (déjà au schéma) accueillera un rattachement
   **explicite** ultérieur.

4. **Genre = énumération fermée nullable (`FEMALE | MALE | OTHER`).** Le PRD ne fixe aucune liste :
   trois valeurs neutres et l'absence couvrent le besoin (« genre optionnel »). Stocké en `text` +
   `CHECK` **dérivé de `domain.enums.Gender`** (conventions `models.py` : jamais de type `ENUM`
   PostgreSQL — évolutif sans `ALTER TYPE`). **Pas** de valeur `UNSPECIFIED` : l'absence est portée par
   `NULL`, une seule représentation du « non renseigné ». Le texte libre est écarté (inexploitable pour
   les statistiques #31, qualité de donnée médiocre). Le genre n'est **jamais déduit** du prénom ni
   d'une autre donnée (collecte minimale §11.3).

5. **Téléphone optionnel, normalisé E.164.** L'énoncé (« nom, téléphone, genre optionnel, notes
   internes ») est ambigu ; le téléphone est retenu **optionnel** car la colonne est nullable, le modèle
   documente explicitement les **clients walk-in**, et l'exiger empêcherait de ficher un client de
   passage. Fourni, il est normalisé par `domain/phone.py::normalize_phone` (indicatif par défaut
   `+225`) — sans forme canonique, `0700000000` et `+2250700000000` créeraient deux fiches et
   **contourneraient** le refus de doublon. L'UI le présente comme **fortement recommandé**.

6. **Unicité `(salon_id, phone)` garantie en base, partielle.** Un index unique **partiel**
   `uq_customer_profiles_salon_phone … WHERE phone IS NOT NULL` (migration `0005`) refuse deux fiches
   pour le même numéro **dans un salon** — deux fiches fausseraient l'historique de visites (#29) et les
   statistiques (#31). Le pré-contrôle applicatif produit un `409` explicite dans le cas nominal, mais
   **la garantie est l'index** : en concurrence, l'`IntegrityError` du perdant est **retraduite** en
   `CustomerAlreadyExists` → `409` (TOCTOU couvert). L'unicité est **par salon** : deux salons peuvent
   ficher le même numéro (cloisonnement §11.2). **Compromis assumé** : un téléphone familial partagé ne
   peut porter deux fiches dans un même salon — échappatoire, créer la seconde fiche **sans téléphone**.

7. **Première mise en service de `CUSTOMER_MANAGE`, sans élargissement.** Toutes les routes déclarent
   `require_permission(Permission.CUSTOMER_MANAGE)` **et** `require_salon_scope`. La matrice
   `ROLE_PERMISSIONS` (§4.1) **n'est pas modifiée** : le `HAIRDRESSER` ne lit pas les fiches clients (il
   n'a que son planning) et l'`ADMIN` non plus (**supervision ≠ exploitation**, ADR-0015). **Aucun**
   chemin n'est ajouté à `PUBLIC_ROUTE_PATHS` : une fiche client n'est jamais lisible sans jeton, ni
   présente dans le catalogue public (#18/#19) ou la disponibilité (#21).

8. **Création journalisée `CUSTOMER_CREATED`, `metadata` vide.** La liste §11.4 du PRD ne cite pas
   explicitement la création de fiche client ; elle est journalisée au titre de **§11.3**
   (« journalisation des accès sensibles ») : créer une fiche est une **collecte de PII**. L'entrée
   porte `actor_user_id` (UUID opaque), `salon_id`, `entity_type="customer"`, `entity_id` et
   **`metadata = {}`** — **jamais** le nom, le téléphone, le genre ni les notes. Elle est écrite dans la
   **même unité de travail** que la mutation (patron #13/#17/#20). Les lectures ne sont **pas**
   journalisées (coût/bruit ; à réexaminer au durcissement #52).

9. **Lectures minimales incluses.** L'issue ne demande que la création, mais `GET` liste (paginée,
   `limit` défaut 50 / max 200, `offset`, plus récentes d'abord) et `GET` fiche sont livrés : sans elles
   la page « Clients » serait un formulaire aveugle, l'isolation §11.2 ne serait pas démontrable en
   lecture, et #29 n'aurait pas de point d'entrée. Elles n'ajoutent **aucun droit** (même permission,
   même portée). La **recherche** du PRD §7.2 (par nom/téléphone) reste un suivi : elle touche à la PII
   et mérite sa propre revue (fuite par temps de réponse, journalisation des critères).

10. **Notes internes : exposition strictement limitée, chiffrement applicatif différé.** Les notes
    peuvent contenir des informations de santé (allergies, US-4.5). Elles ne sont exposées qu'aux routes
    `CUSTOMER_MANAGE` du salon, **jamais** au client ni à l'application mobile, **jamais** journalisées ;
    l'UI web affiche la mention « visible uniquement par le salon ». Le **chiffrement applicatif au
    repos** (§11.3 « si nécessaire ») est **différé** : le chiffrement disque/sauvegardes de la
    plateforme reste couvert par ADR-0011, l'accès est restreint par la permission, et un chiffrement
    applicatif rendrait la future recherche sur notes impossible. Arbitrage à reprendre en M6 (#52).

11. **Bornes d'entrée explicites.** `full_name` ≤ 255 (aligné `String(255)`), `notes` ≤ 2000 (borne
    **applicative** — la colonne est `TEXT`), `phone` E.164 (≤ 15 chiffres), `gender` ∈ énumération
    fermée, `limit` ≤ 200 : ni stockage ni réponse non bornés (budget §12.1). La validation précède
    **toute** écriture — un champ invalide ne produit ni fiche, ni entrée d'audit.

12. **Compteurs de visites laissés à leurs défauts.** `last_visit_at` (`NULL`) et `total_visits` (`0`)
    existent au schéma mais ne sont **ni calculés ni mis à jour** par #28 : ils relèvent de l'historique
    des visites (US-4.2, #29). Aucun rendez-vous, prestation ou montant n'est agrégé ici.

## Conséquences

- **Positives** : le critère d'acceptation de #28 (fiche rattachée au salon, isolation §11.2) est
  couvert **en profondeur** (portée + filtre SQL) ; `CUSTOMER_MANAGE` entre en service **sans** élargir
  la matrice §4.1 ; l'unicité du téléphone est garantie **en base** (course concurrente incluse), ce qui
  protège l'historique #29 et les statistiques #31 ; la journalisation §11.4/§11.3 est en place **sans
  aucune PII** ; la section « Clients » du dashboard gérant est ouverte ; #29/#31/#32/#49 disposent d'un
  point d'entrée stable.
- **Négatives / suivis** : la migration `0005` **modifie le schéma** (colonne + `CHECK` + index) — le
  round-trip Alembic de la CI en est l'arbitre ; l'unicité `(salon_id, phone)` **refuse** deux fiches
  partageant un numéro (téléphone familial — échappatoire documentée) ; ni modification, ni suppression
  de fiche (l'édition de la **note privée** est US-4.5/#32) ; **aucun rattachement** à un compte
  utilisateur (anti-oracle — évolution ultérieure explicite) ; **pas de recherche** plein texte ni de
  filtres avancés ; le **chiffrement au repos des notes** reste ouvert (#52) ; le **recueil du
  consentement** (§11.3) est un **processus métier hors code** au MVP — aucune fonctionnalité
  d'effacement/droit à l'oubli n'est promise par cette issue (durcissement M6, #52).
