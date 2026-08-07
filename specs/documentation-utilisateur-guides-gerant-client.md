# Documentation utilisateur — Guides gérant et client (parcours Must)

> Issue GitHub **#53** — label `docs` · priorité **Should** · effort **M** · §18 Sprint 6 (M6).
> Ce document est une **spécification de plan** : il décrit **quoi** rédiger et **comment**, sans écrire
> les guides eux-mêmes. Aucune modification de code de production n'est prévue — le seul livrable sera
> de la **documentation Markdown** sous `docs/`.

## Problem Statement

Le MVP de CoifLink a livré, issue par issue (M1→M6), les fonctionnalités des trois **parcours critiques
Must** du PRD (§5) : réservation client (§5.1), gestion d'un rendez-vous côté gérant (§5.2) et
encaissement (§5.3). Aujourd'hui, **aucune documentation destinée aux utilisateurs finaux** n'existe :
`docs/` ne contient que des documents d'ingénierie (`adr/`, `environnements-et-secrets.md`,
`strategie-de-tests.md`). Les READMEs de paquet (`app-mobile/README.md`, `web-dashboard/README.md`)
décrivent l'architecture et le découpage hexagonal **pour les développeurs**, pas les gestes concrets
d'un gérant de salon ou d'un client depuis leurs écrans.

Or les personas cibles (PRD §2 : gérants de salon et clients en Afrique de l'Ouest, francophones, à
**faible littératie numérique** pour certains) ont besoin d'un accompagnement **pas à pas, en français,
orienté tâche**, pour prendre en main l'application mobile (client) et l'interface web (gérant). Le
lancement du **pilote 10 salons** (#55) suppose que ces salons puissent être formés sur une base écrite.

Le critère d'acceptation de #53 est : **« documentation des parcours Must publiée »**. Le trou à combler
est donc la rédaction et la publication (dans le dépôt, aux côtés des autres docs) de **deux guides
utilisateur** — un guide **gérant** et un guide **client** — couvrant les parcours Must **tels qu'ils
sont réellement livrés**.

## Goals

- Publier, sous `docs/guides/`, **deux guides utilisateur en français**, orientés tâche et pas à pas :
  - **Guide client** (application mobile Flutter) : trouver un salon, consulter sa fiche, réserver un
    rendez-vous, modifier/annuler un rendez-vous, consulter « Mes rendez-vous » (actifs) et « Mon
    historique » (terminés). Correspond au parcours §5.1 et aux US Must de l'Épic 3 côté client.
  - **Guide gérant** (interface web Next.js `/gerant`) : se connecter, créer et configurer son salon
    (informations, horaires, prestations → salon **réservable** §8.3), gérer le planning et le cycle de
    statuts d'un rendez-vous, tenir le fichier client, enregistrer un paiement et consulter l'historique
    des transactions, lire le tableau de bord (RDV du jour, chiffre d'affaires, prestations demandées,
    clients actifs, performance des coiffeurs). Correspond aux parcours §5.2/§5.3 et aux US Must des
    Épics 1, 2, 4, 5, 6 côté gérant.
- **Documenter uniquement le comportement réellement livré et accessible depuis l'IU**, en s'appuyant
  sur les écrans/pages effectivement présents (voir *Relevant Repository Context*), et **signaler
  explicitement** les étapes des parcours Must du PRD qui **ne sont pas encore exposées à
  l'utilisateur** (notifications non remises, écrans mobiles absents, journal de caisse/zone admin non
  livrés côté IU) au lieu de laisser croire qu'elles existent.
- Fournir un **index** (`docs/guides/README.md`) qui présente les deux guides, l'audience de chacun et
  le lien vers les prérequis d'accès (comptes, plateformes).
- **Relier** chaque section de guide à sa **source produit** (user story / issue / §PRD) de façon
  légère, pour faciliter la maintenance et éviter la dérive documentaire quand de nouvelles issues
  livrent des fonctionnalités.
- Mettre à jour le `README.md` racine (structure du dépôt §5 + références §9) pour référencer
  `docs/guides/`.

## Non-Goals

- **Aucune modification du code de production ou de test** (app-mobile, web-dashboard, backend). #53 est
  purement documentaire. Si la rédaction révèle un **écart** entre le comportement décrit par le PRD et
  le produit livré (p. ex. une étape de parcours non implémentée), on **documente le produit tel qu'il
  est** et on **signale l'écart** — on **n'implémente rien** et on ouvre au besoin un ticket distinct.
- **Pas de mise en place d'un site de documentation** (MkDocs, Docusaurus, GitHub Pages, etc.) : aucune
  chaîne d'outillage de ce type n'existe dans le dépôt. « Publiée » s'entend ici comme *committée dans
  le dépôt sous `docs/`*, à la manière des ADR et de `strategie-de-tests.md` (cf. décision ouverte 1).
- **Pas de guide administrateur CoifLink** en tant que guide d'IU : la zone web `/admin` **n'existe pas
  encore** (livraisons #37/#44 **backend-first**, sans IU). Tout au plus une mention « à venir ». (US-6.6
  KPI globaux et US-5.6 supervision sont livrées **côté backend seulement**.)
- **Pas de documentation d'API / de référence technique** (OpenAPI, endpoints, schémas) : ces guides
  s'adressent aux **utilisateurs finaux**, pas aux intégrateurs. La doc technique reste dans les READMEs
  de paquet et les ADR.
- **Pas de traduction** (anglais/autres langues) au MVP : le produit et sa cible sont **francophones**.
- **Pas de captures d'écran obligatoires** dans ce ticket : aucune infrastructure de capture n'existe et
  les apps ne sont pas rendues en CI. Recommandation : guides **texte d'abord**, emplacements de captures
  balisés pour un ajout ultérieur (cf. décision ouverte 3).
- **Pas de guide coiffeur** développé : la zone `/coiffeur` (planning en lecture seule, #27) est `Should`
  et très réduite. Une **sous-section optionnelle** du guide gérant peut la mentionner ; un guide dédié
  est hors périmètre.

## Relevant Repository Context

**Nature du dépôt.** Monorepo produit CoifLink. Documentation existante : `README.md` (racine), READMEs
de paquet, `docs/adr/*` (ADR de socle), `docs/environnements-et-secrets.md`, `docs/strategie-de-tests.md`.
**Toute la documentation est en français**, en Markdown, **committée dans le dépôt** (pas de site
externe). Convention observée dans les specs et docs : un **en-tête en blockquote** rappelant l'issue et
le périmètre. **Aucune signature IA** n'est autorisée dans le code, les commits, les PR ou la doc
(préférence utilisateur globale) : aucune mention « généré par IA », « Claude », « Anthropic », etc.

**Stack (figée par ADR — rien d'ouvert ici).** App mobile **client** : Flutter/Dart (ADR-0001). Interface
**gérant/admin** : Next.js/React/TypeScript, **une seule application** à zones protégées par rôle
(`/gerant`, `/admin`), ADR-0002/0007. Backend FastAPI/PostgreSQL 16, RBAC deny-by-default (ADR-0015).
Fuseau **Africa/Abidjan (UTC+0)**. Monnaie **XOF / FCFA**, montants en `NUMERIC(12,2)`.

**Ce qui est réellement livré et accessible à l'utilisateur** (à documenter — vérifier au moment de la
rédaction contre les sources citées, ne rien inventer) :

*Côté client — application mobile (`app-mobile/`, cf. `app-mobile/README.md`) :*

- **Recherche / liste des salons** (#18) — `adapters/ui/salon_search_screen.dart` : recherche avec
  debounce, filtre ville, pagination, badges « Réservable » / « Bientôt disponible » (§8.3).
- **Fiche salon** (#19) — `adapters/ui/salon_detail_screen.dart` : logo/nom/localisation, horaires,
  prestations + prix, téléphone, bouton **« Réserver »** (désactivé si non réservable).
- **Tunnel de réservation** (#22) — `adapters/ui/booking/` : prestation → date → créneau → commentaire →
  confirmation ; statut initial affiché **« En attente »**. **Une seule prestation** par réservation,
  réservation **au niveau salon** (pas de choix de coiffeur), horizon **30 jours**.
- **Connexion cliente minimale** (#22) — `adapters/ui/auth/login_screen.dart` : `POST /auth/login`,
  jeton en mémoire (session perdue au redémarrage, MVP).
- **« Mes rendez-vous »** (RDV actifs) — `adapters/ui/appointments/my_appointments_screen.dart` :
  **modifier** (#23) et **annuler** avec motif facultatif (#24).
- **« Mon historique »** (RDV terminés `COMPLETED`) — `adapters/ui/appointments/appointment_history_screen.dart`
  (#30) : lecture seule, prestations + montants figés.

*Côté gérant — interface web (`web-dashboard/`, cf. `web-dashboard/README.md`) :*

- **Connexion / déconnexion** (#14) — `/login`, cookies httpOnly + garde deny-by-default (`GET /auth/me`).
- **Tableau de bord `/gerant`** — RDV du jour par statut (#39), chiffre d'affaires jour/semaine/mois
  (#40), prestations les plus demandées (#41), clients actifs (#42), performance des coiffeurs (#43).
- **Paramètres** (`/gerant/parametres`) — création/consultation du salon (#15), **horaires d'ouverture**
  (#16 ; bandeau §8.3 tant que le salon n'est pas réservable).
- **Prestations** (`/gerant/prestations`) — ajout, édition en ligne, désactivation (#17).
- **Planning** (`/gerant/planning`) — vues jour/semaine/mois (#26) et **cycle de statuts** d'un RDV
  (confirmer/refuser/terminé/absent, assignation d'un coiffeur) (#25).
- **Clients** (`/gerant/clients`, `/gerant/clients/[id]`) — fichier client + création de fiche (#28),
  historique des visites (#29), prestations préférées (#31), **note privée** salon-interne (#32).
- **Encaissements** (`/gerant/encaissements`) — enregistrement d'un paiement (#33, montant pré-rempli,
  cohérence contrôlée par le backend §8.2) et **historique des transactions filtrable** (#35).
- **Zone coiffeur** (`/coiffeur/planning`, #27) — planning assigné en **lecture seule** (rôle
  `HAIRDRESSER`).

**Étapes des parcours Must du PRD qui NE sont PAS exposées à l'utilisateur au MVP** (à **signaler**, pas
à décrire comme disponibles) :

- **Notifications non remises.** Les notifications de confirmation (#45), rappel (#46), notification au
  salon (#47) et annulation/modification (#48) sont **émises et tracées en base** mais **jamais
  réellement envoyées** (`sent_at = NULL`) : la remise proactive push/SMS est **différée M5+**
  (ADR-0006/0033-0036). Les étapes §5.1.8 « reçoit une notification de confirmation » et §5.1.9 « reçoit
  un rappel » **ne se matérialisent pas** côté client au MVP → à documenter comme **« à venir »**.
- **Inscription / réinitialisation de mot de passe côté mobile.** Le backend expose `POST /auth/register`
  (#8) et l'OTP (#11), mais l'app mobile ne porte **que** l'écran de **connexion** (#22) — **aucun écran
  d'inscription ni de mot de passe oublié**. L'étape §5.1.2 « crée un compte ou se connecte » est donc
  partiellement couverte côté IU → à signaler (le client doit disposer d'un compte ; création via un
  autre canal au MVP).
- **Reçu client dans l'app.** Le reçu est **généré/récupérable** côté backend (`GET /me/receipts`, #38)
  mais **aucun écran mobile** ne l'affiche ; la remise proactive est différée (ADR-0030). Étape §5.3.9
  « reçu généré ou envoyé » → à signaler comme partiellement couvert.
- **Journal de caisse & correction d'écart côté web.** Livrés **backend seulement** (#34) — « restent à
  livrer côté web » (README web) ; l'historique des transactions (#35) est, lui, disponible dans l'IU.
- **Zone admin.** `/admin` **n'existe pas** ; KPI globaux (#44) et supervision agrégée (#37) sont
  backend-only. **Aucun guide admin d'IU** possible.
- **Gestion des employés côté web.** La création de coiffeurs existe **côté backend** (`POST
  /salons/{id}/employees`, #13) ; aucune page `/gerant/employes` n'est listée dans les routes web → à
  vérifier et, si absente, ne pas documenter comme disponible.

**Sources de vérité à relire au moment de la rédaction** (pour garantir l'exactitude, écran par écran) :
`app-mobile/README.md`, `web-dashboard/README.md`, `prd-coiflink.md` (§5, §6, §7, §22), `BACKLOG.md`
(#53 et dépendances), et, si besoin de trancher un comportement d'écran, le code sous
`app-mobile/lib/adapters/ui/` et `web-dashboard/app/` / `web-dashboard/src/adapters/ui/`.

## Proposed Implementation

Créer un dossier `docs/guides/` contenant **trois fichiers Markdown en français** :

1. `docs/guides/README.md` — **index** : présentation, audience de chaque guide, prérequis d'accès
   (plateformes, comptes/rôles), lien vers chaque guide et vers le PRD/README. En-tête en blockquote
   (convention du dépôt) rappelant l'issue #53 et le périmètre « parcours Must ».
2. `docs/guides/guide-client.md` — **guide client (application mobile)**.
3. `docs/guides/guide-gerant.md` — **guide gérant (interface web)**.

**Principes de rédaction (transverses aux deux guides) :**

- **Français, ton simple et direct**, orienté tâche (« Pour réserver un rendez-vous… »), phrases courtes,
  vocabulaire non technique (pas de « endpoint », « JWT », « BFF », « hexagonal »).
- **Structure par tâche** : chaque tâche = un titre d'action + une liste numérotée d'étapes reflétant
  **exactement** les écrans/champs réels + le **résultat attendu** + les **cas d'erreur visibles** que
  l'utilisateur peut rencontrer (état vide, message neutre, créneau déjà pris, etc., tels que décrits
  dans les READMEs de paquet).
- **N'affirmer que le comportement réellement livré.** Chaque affirmation doit être traçable à un écran
  existant. Les étapes non exposées à l'IU sont regroupées dans un encadré **« À venir »** clairement
  distinct, formulé comme une limitation connue (« Au lancement, vous ne recevez pas encore de SMS de
  rappel ; la notification est enregistrée mais non envoyée. »), **sans** décrire d'UI inexistante.
- **Exemples fictifs uniquement** : noms de salon, numéros de téléphone (préfixe manifestement fictif),
  montants d'exemple. **Aucune donnée réelle, aucun identifiant, aucun secret, aucune capture contenant
  de la PII.**
- **Traçabilité de maintenance** : en fin de chaque guide, un petit tableau « Cette fonctionnalité vient
  de » reliant chaque section à sa user story / issue (léger, pour la maintenance ; pas de jargon dans le
  corps).
- **Rappels de confidentialité pertinents pour l'utilisateur** : p. ex. dans le guide gérant, la note
  client privée est **visible du seul salon, jamais du client** (§11.3) — reformuler la garantie déjà
  affichée dans l'IU, ne pas en inventer.

**Plan de contenu — `guide-client.md` (parcours §5.1) :**

1. **Avant de commencer** : plateforme (Android prioritaire), besoin d'un compte, se connecter (écran de
   connexion #22). Encadré **« À venir »** : création de compte / mot de passe oublié dans l'app.
2. **Trouver un salon** : recherche, filtre par ville, badges « Réservable » / « Bientôt disponible »
   (#18).
3. **Consulter un salon** : horaires, prestations et prix, localisation, bouton « Réserver » (#19).
4. **Réserver un rendez-vous** : prestation → date → créneau → commentaire facultatif → confirmation ;
   résultat « En attente » ; cas « créneau déjà pris » et « connexion requise » (#22). Rappeler : une
   prestation par réservation, pas de choix de coiffeur, 30 jours d'horizon.
5. **Après la réservation** : encadré **« À venir »** — confirmation/rappel enregistrés mais **non
   envoyés** au MVP (#45/#46, ADR-0006/0033-0034).
6. **Gérer mes rendez-vous** : « Mes rendez-vous » (actifs), **modifier** (#23), **annuler** avec motif
   facultatif (#24).
7. **Mon historique** : rendez-vous terminés, prestations et montants (#30). Encadré **« À venir »** :
   reçu de paiement dans l'app (#38 côté backend seulement).

**Plan de contenu — `guide-gerant.md` (parcours §5.2 et §5.3) :**

1. **Se connecter** : `/login`, session, déconnexion (#14).
2. **Configurer mon salon** (prérequis à tout le reste) : créer le salon (#15), saisir les **horaires**
   (#16) → le salon devient **réservable** (expliquer le bandeau §8.3), ajouter les **prestations** (#17).
3. **Gérer le planning et les rendez-vous** (§5.2) : consulter le planning jour/semaine/mois (#26), lire
   les statuts, **assigner un coiffeur**, **confirmer/refuser/terminer/absent** (#25).
4. **Encaisser un paiement** (§5.3) : sélectionner la prestation, montant **pré-rempli**, mode de
   paiement, référence ; message si le montant ne correspond pas (#33) ; consulter l'**historique des
   transactions** filtrable (#35). Encadré **« À venir »** : consultation du **journal de caisse** et
   correction d'écart dans l'IU (#34 backend seulement).
5. **Suivre mes clients** : créer une fiche (#28), consulter l'**historique des visites** (#29), les
   **prestations préférées** (#31), tenir la **note privée** — rappeler qu'elle est **interne au salon**
   (#32, §11.3).
6. **Lire mon tableau de bord** : RDV du jour (#39), chiffre d'affaires (#40), prestations demandées
   (#41), clients actifs (#42), performance des coiffeurs (#43). Expliquer les états vides légitimes.
7. **(Optionnel) Espace coiffeur** : brève mention du planning assigné en lecture seule (#27).
8. Encadrés **« À venir »** transverses : notification au salon à la réservation non remise (#47/#48),
   zone admin/KPI globaux (#37/#44 backend-only), gestion des employés dans l'IU (à vérifier, #13).

**En-têtes de sections requises par l'issue** : les guides sont des documents **utilisateur** (français,
titres orientés tâche) ; les *en-têtes anglais normalisés* (Problem Statement, Goals, …) restent propres
à **cette spec de plan**, pas aux guides livrés.

## Affected Files / Packages / Modules

**À créer :**

- `docs/guides/README.md` — index des guides utilisateur.
- `docs/guides/guide-client.md` — guide client (mobile).
- `docs/guides/guide-gerant.md` — guide gérant (web).

**À mettre à jour :**

- `README.md` (racine) — §5 « Structure du dépôt » (ajouter `docs/guides/`) et §9 « Références »
  (liens vers les deux guides). Éventuellement une phrase en §6 signalant #53 livrée (parité avec la
  façon dont les autres issues M6 y sont mentionnées).

**À lire (référence, non modifiés) — pour garantir l'exactitude :**

- `app-mobile/README.md`, `web-dashboard/README.md` — inventaire des écrans/pages réellement livrés.
- `prd-coiflink.md` — §5 (parcours), §6 (US + priorités Must), §7 (écrans), §22 (MoSCoW).
- `BACKLOG.md` — entrée #53 et périmètre M6.
- Si un comportement d'écran doit être tranché : `app-mobile/lib/adapters/ui/**`,
  `web-dashboard/app/**`, `web-dashboard/src/adapters/ui/**`.
- Specs par fonctionnalité déjà publiées sous `specs/` (p. ex. `reservation-rendez-vous-client.md`,
  `enregistrement-paiement-gerant.md`, `planning-salon-vue-calendrier.md`) — utiles pour reformuler un
  comportement en langage utilisateur.

## API / Interface Changes

**None.** Aucune commande, aucun endpoint, aucun schéma, aucune surface d'API n'est ajouté ou modifié.
Le livrable est exclusivement de la documentation Markdown. Les guides **décrivent** des interfaces
existantes (écrans mobiles, pages web) ; ils n'en créent aucune.

## Data Model / Protocol Changes

**None.** Aucun changement de schéma, de stockage, de persistance ou de sérialisation. Pas de migration.

## Security & Privacy Considerations

- **Aucun secret, identifiant ni PII** dans les guides. Les exemples (noms de salon, numéros de
  téléphone, montants, adresses) sont **fictifs** et manifestement non réels. Ne jamais inclure de
  jeton, mot de passe, clé, URL signée, ni numéro/nom d'une personne réelle. Cohérent avec la politique
  du dépôt (`docs/environnements-et-secrets.md`, `backend/tests/test_secrets_policy.py`, §11.3).
- **Captures d'écran** (si ajoutées ultérieurement — hors périmètre par défaut) : ne doivent contenir
  **aucune** donnée réelle (utiliser un jeu de données de démonstration fictif). À rappeler explicitement
  dans l'index si des captures sont introduites.
- **Confidentialité côté produit à refléter fidèlement, sans l'affaiblir** :
  - La **note client privée** est visible **du seul salon, jamais du client** (§11.3, #32) — l'énoncer
    tel quel.
  - Les guides ne doivent pas suggérer que le client voit des données de gestion, ni qu'un gérant voit
    les données d'un autre salon (**isolation par salon** §11.2) — ne rien décrire qui contredise le RBAC
    deny-by-default (ADR-0015).
  - Ne pas documenter les **routes internes BFF** (`/api/*` du web) ni les endpoints backend comme s'ils
    étaient des surfaces utilisateur : les guides restent au niveau **écran/page**.
- **Non-remise des notifications** : décrire l'état réel (enregistrées, non envoyées) évite de créer une
  **fausse attente de sécurité/opérationnelle** (« le client a forcément été prévenu »). Formuler comme
  une limitation connue du MVP.
- Le dépôt ne documente **aucune** contrainte de résidence/latence/taille applicable à un livrable
  purement documentaire au-delà de ce qui précède.

## Testing Plan

Livrable documentaire : « tests » = vérifications de conformité et de non-régression documentaire.

- **Revue d'exactitude, écran par écran** : pour chaque étape décrite, confirmer qu'elle correspond à un
  écran/champ **réellement présent** (croiser avec `app-mobile/README.md` / `web-dashboard/README.md` et,
  si besoin, le code d'IU). Aucune étape ne doit décrire une UI inexistante.
- **Vérification des liens Markdown** : tous les liens relatifs (vers ADR, PRD, README, entre guides)
  **résolvent**. Un passage manuel suffit au MVP ; un vérificateur de liens (p. ex. `lychee`) est
  **optionnel** et non outillé aujourd'hui (cf. décision ouverte 4).
- **Contrôle « aucune PII / aucun secret »** : relecture ciblée + `grep` de motifs à risque (numéros
  réels, adresses e-mail réelles, jetons) — aucune correspondance attendue.
- **Contrôle « aucune signature IA »** : `grep -riE "claude|anthropic|generated with|généré par (l'|l')?ia|🤖"`
  sur `docs/guides/` — aucune correspondance.
- **Cohérence terminologique** : rôles (« gérant », « client », « coiffeur »), monnaie (**FCFA**), fuseau
  (**Africa/Abidjan**), noms de sections d'IU identiques à ceux affichés (« Mes rendez-vous », « Mon
  historique », « Encaissements », « Prestations les plus demandées », …).
- **Test gate ADW / CI** : un changement `docs/` **n'exécute aucun test de code** ; le gate
  (`scripts/test-gate.sh`) et la CI applicative restent verts sans action (aucun code touché). Ne pas
  ajouter de dépendance de test pour ce ticket.

## Documentation Updates

- **Création** : `docs/guides/README.md`, `docs/guides/guide-client.md`, `docs/guides/guide-gerant.md`
  (le livrable principal).
- **`README.md` racine** : ajouter `docs/guides/` à la §5 (structure) et des liens en §9 (références) ;
  mention facultative en §6 que #53 est livrée (parité avec les autres issues M6).
- **ADR** : **aucun ADR requis** — #53 n'introduit aucune décision d'architecture (pure documentation
  utilisateur). Exception éventuelle (décision ouverte 1) : si l'on décidait d'introduire un **site de
  documentation** (outillage nouveau), un court ADR justifierait ce choix — **hors périmètre par
  défaut**.
- **`docs/strategie-de-tests.md`** : **pas de mise à jour attendue** (aucun test de code ajouté).

## Risks and Open Questions

1. **Sens de « publiée ».** Recommandation : *committée dans le dépôt sous `docs/guides/`*, cohérent avec
   ADR/`strategie-de-tests.md` (aucun site de doc n'existe). Un site (MkDocs/Docusaurus/Pages) serait un
   **nouvel outillage** → hors périmètre par défaut ; à confirmer si un rendu HTML public est réellement
   attendu pour le pilote (#55).
2. **Fidélité PRD ↔ produit livré.** Plusieurs étapes des parcours Must (§5) ne sont **pas exposées à
   l'IU** (notifications non remises, inscription/reçu mobiles absents, journal de caisse/admin/employés
   côté web non livrés). Recommandation : **documenter le produit tel qu'il est** + encadrés « À venir »
   explicites. À confirmer que c'est la posture attendue plutôt que de décrire la cible PRD complète.
3. **Captures d'écran.** Texte d'abord recommandé (pas d'infra de capture ; risque de PII ; les écrans
   évolueront). Si des captures sont voulues pour le pilote, décider **où** (dossier `docs/guides/img/`),
   **comment** (jeu de données fictif) et **qui** les produit. *À trancher.*
4. **Outillage de vérification des liens/Markdown.** Aucun linter Markdown ni link-checker n'est câblé.
   Vérification manuelle au MVP ; l'ajout d'un check CI dédié est **optionnel** et **hors périmètre**
   (n'introduire aucun nouvel outillage sans décision).
5. **Audience et niveau de détail.** Cible : gérants/clients **non techniques**, francophones, littératie
   numérique variable (PRD §2). Recommandation : langage très simple, une tâche par section, pas de
   jargon. À confirmer si un niveau « aide-mémoire » (une page) est aussi souhaité en complément.
6. **Maintenance / dérive.** Les guides risquent de vieillir à mesure que de nouvelles issues livrent des
   écrans (p. ex. reçu mobile, journal de caisse web, zone admin). Mitigation : tableau de traçabilité
   « section → issue/US » en fin de guide, et note de maintenance dans l'index invitant à mettre à jour
   le guide concerné quand l'issue correspondante est livrée.
7. **Nom du dossier/fichiers.** `docs/guides/` + `guide-client.md` / `guide-gerant.md` (kebab-case,
   français) recommandé ; alternative `docs/guides/client.md` / `gerant.md`. Sans impact fonctionnel.

## Implementation Checklist

1. **Relire les sources d'exactitude** : `app-mobile/README.md`, `web-dashboard/README.md`,
   `prd-coiflink.md` (§5, §6, §7, §22), `BACKLOG.md` (#53). Dresser la **liste des écrans/pages
   réellement livrés** et la **liste des étapes Must non exposées à l'IU** (section *Relevant Repository
   Context* ci-dessus comme point de départ, **à revérifier**).
2. **Créer `docs/guides/`** et l'**index** `docs/guides/README.md` : en-tête blockquote (#53, périmètre
   « parcours Must »), audience de chaque guide, prérequis d'accès, liens vers les deux guides et vers
   PRD/README, note de maintenance.
3. **Rédiger `docs/guides/guide-client.md`** (parcours §5.1) selon le plan de contenu : trouver → consulter
   → réserver → gérer (modifier/annuler) → historique, avec encadrés **« À venir »** (inscription/mot de
   passe mobiles, notifications non remises, reçu mobile). Exemples **fictifs** uniquement.
4. **Rédiger `docs/guides/guide-gerant.md`** (parcours §5.2/§5.3) selon le plan de contenu : se connecter →
   configurer le salon (salon réservable §8.3) → planning & statuts → encaissement & historique des
   transactions → clients (dont note privée §11.3) → tableau de bord, avec encadrés **« À venir »**
   (journal de caisse/admin/employés côté IU, notification salon non remise).
5. **Ajouter un tableau de traçabilité** « section → issue/US » en fin de chaque guide.
6. **Mettre à jour `README.md`** : §5 (ajouter `docs/guides/`), §9 (liens), mention facultative §6.
7. **Vérifier** : exactitude écran par écran ; **aucune** UI inexistante décrite ; liens relatifs
   résolus ; **aucune PII/secret** ; **aucune signature IA** (`grep`) ; terminologie et FCFA/fuseau
   cohérents.
8. **Ne modifier aucun code** de production ou de test. Si un écart PRD ↔ produit est constaté au-delà des
   « À venir » attendus, le **documenter comme limitation** et, si structurant, ouvrir un **ticket
   distinct** (ne rien implémenter sous couvert de #53).
