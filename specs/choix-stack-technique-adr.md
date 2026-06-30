# Choix de la stack technique & ADR (issue #1)

> Spécification de planification pour l'issue GitHub **#1 — Choix de la stack technique & ADR**
> (`docs` `infra` · Must · Effort M · PRD §10 / §18 Sprint 0).
> **Cette spec ne produit pas de code.** Elle décrit la rédaction d'Architecture Decision
> Records (ADR) figeant chaque brique recommandée au §10 du PRD, à exécuter dans une phase
> d'implémentation ultérieure.
>
> Conventions : le dépôt est rédigé en **français** (PRD, BACKLOG, README, ADR). Les en-têtes de
> section ci-dessous sont conservés en anglais car ils sont attendus par le gabarit du pipeline ADW ;
> le contenu et les ADR livrés sont en français.

## Problem Statement

Le dépôt est à l'état **greenfield** : aucun code applicatif n'existe (`backend/`, `web-dashboard/`,
`app-mobile/` ne sont pas créés). Le PRD §10.2 ne fait que **recommander** une stack et laisse
plusieurs briques ouvertes sous forme d'alternatives (« Flutter *ou* React Native », « FastAPI *ou*
Django REST »). Le README §4 indique explicitement que la stack est « **à figer par l'ADR de
l'issue #1** avant tout code », et plusieurs issues du socle en dépendent directement :

- **#2** (initialisation du dépôt) — dépend de #1 ;
- **#3** (modèle de données / PostgreSQL) — dépend de #1, #2 ;
- **#6** (plan de tests & test gate `MX_AGENT_TEST_CMD`) — dépend de #1, #4.

Tant que ces choix ne sont pas tranchés et tracés, aucune issue de fonctionnalité (M1 →) ne peut
démarrer sans risque de retravail. Le besoin : **trancher chaque brique majeure et figer la décision
dans un ADR versionné**, avec la justification du compromis (coût, écosystème, cible Android entrée
de gamme), de sorte qu'**aucune décision de stack ne reste ouverte pour M1**.

## Goals

- Créer le répertoire `docs/adr/` (absent aujourd'hui) et y committer **un ADR par décision majeure**.
- Trancher et documenter les six briques recommandées au PRD §10 :
  1. **Application mobile** — Flutter vs React Native (Android prioritaire) → **Flutter**.
  2. **Interface web gérant/admin** — **Next.js / React**.
  3. **Backend** — FastAPI vs Django REST (API REST + JWT) → **FastAPI**.
  4. **Données** — **PostgreSQL** (relationnel) + **Redis** (cache / file / TTL).
  5. **Stockage fichiers** — **objet S3-compatible** (logos, photos salons).
  6. **Notifications** — **FCM** (push mobile) + **SMS** via agrégateur ; WhatsApp en V2.
- Pour chaque ADR : énoncer le contexte, les options envisagées, la décision, la **justification du
  compromis** (coût, écosystème, contraintes terrain / Android entrée de gamme) et les conséquences
  (positives, négatives/risques, issues impactées).
- Fixer un **gabarit ADR** et une convention de numérotation/statut réutilisables pour les futures
  décisions d'architecture.
- Mettre à jour le README §4 pour qu'il **référence les ADR** comme source de vérité de la stack.
- Garantir le critère d'acceptation : **aucune décision de stack listée au §10 ne reste « ouverte »**
  (statut « Proposé ») à la fin de l'issue, pour ne pas bloquer M1.

## Non-Goals

- **Écrire du code applicatif** (initialisation des paquets, scaffolding) — c'est l'issue **#2**.
- **Implémenter le schéma de données / les migrations** PostgreSQL — issue **#3**.
- **Configurer la CI/CD** et les images Docker — issue **#4**.
- **Mettre en place les environnements et la gestion des secrets** (dev/staging/prod) — issue **#5**.
- **Câbler le test gate** `MX_AGENT_TEST_CMD` dans `scripts/adw.env` — issue **#6** (la présente spec
  ne fixe que le langage/framework dont ce gate découlera).
- **Choisir l'hébergeur cloud / la plateforme de déploiement** et le fournisseur SMS local concret :
  ce sont des décisions de déploiement/opérations rattachées à #4/#5 (voir *Risks and Open
  Questions*). Le §10 fixe déjà Docker + GitHub Actions au niveau outillage ; la plateforme cible
  n'est **pas** une brique applicative bloquante pour M1 (auth).
- Sélectionner des bibliothèques de second rang (ORM précis, runner de tâches async, libs UI) au-delà
  de ce qui est nécessaire pour rendre une décision majeure non ambiguë ; les sous-choix non
  bloquants sont signalés comme à confirmer plus tard.

## Relevant Repository Context

**Nature du dépôt.** Greenfield outillé pour une livraison agentique (pipeline ADW). Pas de code
applicatif ; le code sera produit issue par issue à partir de `BACKLOG.md` (55 issues, M0–M6).

**Source de vérité produit.** `prd-coiflink.md` — en particulier :
- **§10 Architecture technique** — recommandations de stack (frontend mobile/web, backend, BD, cache,
  stockage, notifications, déploiement) ; §10.4 liste des services backend logiques (Auth, Salon,
  Appointment, Customer, Payment, Notification, Analytics, Admin).
- **§11 Sécurité & conformité** — JWT + refresh token, OTP de réinitialisation, protection contre les
  tentatives répétées, RBAC strict avec isolation par salon, collecte minimale de données, consentement,
  journalisation des accès sensibles, chiffrement au repos « si nécessaire ».
- **§12 Non fonctionnel** — réponse API < 3 s, dashboard < 3 s, recherche salon < 2 s.
- **§18 Sprint 0** — livrable « Choix technologiques » + « Architecture technique ».

**Backlog.** `BACKLOG.md` (M0 — Socle) détaille l'issue #1 et **met en gras les choix retenus** :
app mobile (**Flutter** vs React Native), web (**Next.js / React**), backend (**FastAPI** vs Django
REST), données (**PostgreSQL + Redis**), stockage S3-compatible, notifications FCM + SMS. Acceptation :
*un ADR par décision majeure dans `docs/adr/` ; justification du compromis ; aucune décision ouverte
pour M1.* Les issues #2, #3, #6 dépendent de #1.

**README.** §4 contient un tableau « Stack recommandée … à figer par l'ADR #1 » ; §7 note que le test
gate (ex. `flutter test`, `pytest`) « reste à configurer une fois la stack tranchée par l'ADR #1 ».
L'historique git montre déjà une orientation : commits *« patient app test gate is `flutter test`
(ADR 0001 → Flutter) »* et *« record the chosen test gate now that stack (#1) is decided »*. Ces
commits **présupposent** Flutter et la numérotation `ADR 0001` mais **aucun fichier ADR n'existe
encore** — la présente issue doit matérialiser ces décisions.

**État des répertoires (vérifié).** `specs/` et `docs/` **n'existent pas** ; il n'y a **aucun ADR**.
Cette issue crée donc `docs/adr/` (et la présente spec crée `specs/`).

**Décisions encore ouvertes au démarrage** (à trancher par cette issue) : framework mobile,
framework web, framework backend, et formalisation de PostgreSQL+Redis / S3 / FCM+SMS comme décisions
*figées* (et non « recommandées »). Restent volontairement ouvertes après #1 (non bloquantes M1) :
plateforme d'hébergement, fournisseur SMS concret, versions précises, ORM/runner async — voir
*Risks and Open Questions*.

## Proposed Implementation

Approche : **un répertoire `docs/adr/`**, **un fichier ADR par décision majeure** au format Markdown
léger (style MADR simplifié), numérotés `NNNN`, en français, statut **Accepté**, datés du jour de la
décision (`2026-06-29` au moment de la rédaction de cette spec — l'agent d'implémentation utilisera la
date réelle de commit). Recommander aussi un **ADR-0000** définissant le processus/gabarit, et un
`docs/adr/README.md` servant d'index.

### Gabarit ADR (à placer dans ADR-0000 et réutiliser)

```markdown
# ADR-NNNN : <Titre court de la décision>

- **Statut** : Accepté
- **Date** : AAAA-MM-JJ
- **Décideurs** : équipe CoifLink
- **Issue** : #1
- **Référence PRD** : §10 (et §11/§12 si pertinent)

## Contexte et problème
Quel besoin, quelle contrainte, pourquoi décider maintenant.

## Options envisagées
- Option A — …
- Option B — …
(uniquement les options réellement plausibles)

## Décision
La brique retenue, en une phrase non ambiguë.

## Justification (compromis)
Coût · écosystème · talent disponible · cible Android entrée de gamme / contraintes
terrain (réseau, appareils) · alignement avec le PRD (§11 sécurité, §12 perf).

## Conséquences
- **Positives** : …
- **Négatives / risques** : …
- **Suivi** : sous-décisions différées et issues impactées (#2, #3, #4, #5, #6).
```

### Contenu attendu de chaque ADR

> Le texte ci-dessous est un **brief de contenu** pour l'agent d'implémentation, pas la prose finale.
> Chaque décision « majeure » correspond à un fichier afin de satisfaire « un ADR par décision ».

**`docs/adr/0000-processus-et-gabarit-adr.md` — Processus & gabarit ADR** *(fondation, recommandé)*
Définit : format MADR simplifié ci-dessus, numérotation `NNNN` croissante, statuts
(`Proposé` → `Accepté` → `Remplacé par ADR-XXXX`), langue (français), localisation `docs/adr/`,
règle « une décision majeure = un fichier ». Justifie le choix d'un format léger (faible coût de
rédaction, lisible par humains et agents).

**`docs/adr/0001-app-mobile-flutter.md` — Application mobile : Flutter** *(brique 1)*
- Options : **Flutter** vs **React Native**.
- Décision : **Flutter**.
- Justification : Android prioritaire et **cible entrée de gamme** → rendu natif compilé (AOT) et
  moteur graphique propre (rendu cohérent indépendant des surcouches OEM), bonnes performances et UI
  homogène sur appareils modestes ; base de code unique Android (+ iOS en second lot, §10.2) ;
  écosystème de widgets mature. Compromis : courbe Dart et moindre partage de code avec le web
  React/Next.js (vs RN qui partagerait l'écosystème JS) ; ce coût est accepté au profit de la
  performance/cohérence sur Android bas de gamme. Cohérent avec l'orientation déjà tracée
  (`flutter test` comme exemple de test gate, README §7).
- Conséquences : oriente le test gate mobile (`flutter test`, issue #6), l'arborescence `app-mobile/`
  (#2), et la CI mobile (#4).

**`docs/adr/0002-web-gerant-admin-nextjs.md` — Interface web gérant/admin : Next.js (React)** *(brique 2)*
- Options : **Next.js** vs **React SPA** (Vite/CRA pur).
- Décision : **Next.js (React, TypeScript)** pour les interfaces gérant **et** admin.
- Justification : rendu serveur/statique pour tenir les budgets de chargement (dashboard < 3 s,
  §12.1), routage par fichiers, DX et écosystème React larges, interface responsive adaptée à des
  gérants non techniques (§10.2). Compromis : surcoût d'un framework par rapport à une SPA simple,
  accepté pour la perf et la structuration.
- À confirmer (non bloquant) : **une application Next.js unique** avec zones par rôle vs **deux
  applications séparées** (gérant / admin) — décision d'arborescence renvoyée à #2 ; à signaler dans
  la section *Conséquences* de l'ADR.

**`docs/adr/0003-backend-fastapi.md` — Backend : FastAPI** *(brique 3)*
- Options : **FastAPI** vs **Django REST Framework**.
- Décision : **FastAPI** (Python), API REST, authentification **JWT**.
- Justification : nature asynchrone native (jobs async pour notifications, §10.2), bonnes
  performances (budget API < 3 s, §12.1), légèreté, **documentation OpenAPI auto-générée** (sert
  l'exigence « documenter les API publiques »), validation Pydantic. Compromis : contrairement à
  Django REST « batteries incluses », il faut assembler explicitement ORM + migrations + auth ;
  ce coût est accepté pour la légèreté/perf et le découplage des services logiques du §10.4.
- À confirmer (non bloquant, signalé en *Conséquences*) : ORM + outil de migrations (p. ex.
  SQLAlchemy + Alembic, ou SQLModel) → précisé en #3 ; runner de tâches async (Celery / arq / RQ)
  → précisé en #5/#6 ; bibliothèques JWT/hash (p. ex. passlib + argon2/bcrypt, python-jose).

**`docs/adr/0004-donnees-postgresql-redis.md` — Données : PostgreSQL + Redis** *(brique 4)*
- Décision : **PostgreSQL** comme base relationnelle principale ; **Redis** pour cache, file de
  tâches et clés à expiration.
- Justification : modèle de données relationnel (§9) et contraintes d'intégrité fortes (anti
  double-réservation §8.1, paiement lié à une prestation/RDV §8.2) → PostgreSQL (ACID, contraintes,
  transactions). Redis sert : cache de lecture (perf §12), **broker** des jobs async (notifications),
  **OTP** à TTL et **anti-bruteforce** sur les connexions (§11.1), liste de révocation de refresh
  tokens. Pas d'alternative sérieuse — le PRD fige ces briques ; l'ADR formalise le rôle de chacune.
- À confirmer (non bloquant) : versions de référence (p. ex. PostgreSQL 16, Redis 7) → à arrêter en
  #2/#3.

**`docs/adr/0005-stockage-objet-s3-compatible.md` — Stockage fichiers : objet S3-compatible** *(brique 5)*
- Décision : **stockage objet via une API S3-compatible** pour logos et photos de salons (§10.2),
  accédé par une bibliothèque cliente standard (p. ex. boto3) afin de rester **agnostique du
  fournisseur** (AWS S3, MinIO auto-hébergé, Cloudflare R2, bucket de la plateforme d'hébergement…).
- Justification : ne pas stocker les binaires en base, compatibilité CDN, coût maîtrisé, portabilité.
  Compromis : un fournisseur concret reste à choisir au déploiement (#4/#5) — l'ADR fixe **l'interface
  (S3-compatible)**, pas le fournisseur.
- Sécurité (renvoi §11) : buckets privés par défaut, accès par URL signées à durée limitée, **aucune
  PII dans les noms d'objets/chemins**, identifiants d'accès gérés hors dépôt (#5).

**`docs/adr/0006-notifications-fcm-sms.md` — Notifications : FCM + SMS** *(brique 6)*
- Décision : **Firebase Cloud Messaging** pour le push mobile et **SMS** via agrégateur pour les
  messages hors-app et l'OTP ; **WhatsApp Business API différé en V2** (PRD §16). Envois traités en
  **asynchrone** via la file Redis (cohérent avec ADR-0004 et FastAPI async).
- Justification : FCM = standard push gratuit/scalable côté Android (cible prioritaire) ; SMS = canal
  de repli universel (clients sans app, OTP, §8.4 / Épic 7). Compromis : dépendance à un fournisseur
  SMS payant ; le **fournisseur concret** (agrégateur local Côte d'Ivoire / Afrique de l'Ouest) est
  une décision opérationnelle différée (#5) — l'ADR fixe les **canaux**, pas le fournisseur.
- Sécurité (renvoi §11) : **ne jamais journaliser** le corps des messages, les OTP ni les
  numéros/identifiants (PII) ; clés FCM et identifiants SMS stockés hors dépôt (#5).

### Index et cohérence

- Créer `docs/adr/README.md` : tableau index `ADR | Titre | Statut | Issue` listant 0000–0006.
- Mettre à jour `README.md` §4 : remplacer la mention « Stack recommandée … à figer par l'ADR #1 »
  par « Stack figée par les ADR (`docs/adr/`) » avec liens, en gardant le tableau comme résumé.
- Vérifier l'absence de toute mention « générée par IA » dans les ADR, commits et PR (préférence
  utilisateur durable).

## Affected Files / Packages / Modules

À **créer** (cette issue) :
- `docs/adr/0000-processus-et-gabarit-adr.md` *(recommandé)*
- `docs/adr/0001-app-mobile-flutter.md`
- `docs/adr/0002-web-gerant-admin-nextjs.md`
- `docs/adr/0003-backend-fastapi.md`
- `docs/adr/0004-donnees-postgresql-redis.md`
- `docs/adr/0005-stockage-objet-s3-compatible.md`
- `docs/adr/0006-notifications-fcm-sms.md`
- `docs/adr/README.md` (index)

À **lire** pour rédiger juste :
- `prd-coiflink.md` — §10, §11, §12, §18, §16 (WhatsApp V2).
- `BACKLOG.md` — entrée #1 et items M0 (#2–#6) pour les renvois « Dépend de ».
- `README.md` — §4 (tableau stack) et §7 (test gate).

À **modifier** :
- `README.md` — §4 (référencer les ADR comme source de vérité de la stack).

À **ne pas toucher** : `adw_sdlc/`, `adw/`, `scripts/`, `.github/workflows/` (hors périmètre #1).

## API / Interface Changes

**None.** L'issue ne produit que de la documentation (ADR + index + mise à jour README). Aucune API
en ligne de commande, réseau ou publique n'est ajoutée ni modifiée. Les ADR **fixent** toutefois les
décisions dont découleront de futures interfaces (API REST + JWT du backend, etc.), implémentées par
d'autres issues.

## Data Model / Protocol Changes

**None.** Aucune modification de schéma, de format de stockage ou de sérialisation. L'ADR-0004
**documente** le choix PostgreSQL + Redis, mais le schéma et les migrations relèvent de l'issue #3.

## Security & Privacy Considerations

Les ADR n'introduisent aucun traitement de données, mais ils **doivent refléter et préserver** les
invariants de sécurité du PRD §11 (sans jamais les affaiblir) :

- **Authentification/autorisation** : ADR-0003 ancre JWT + refresh token, hachage de mot de passe par
  algorithme robuste (argon2/bcrypt), OTP de réinitialisation, protection anti-bruteforce (§11.1),
  RBAC strict avec isolation par salon (§11.2). L'ADR énonce ces exigences comme contraintes, leur
  implémentation revenant à M1 (#10, #12).
- **Secrets/credentials** : aucun secret (clé FCM, identifiants SMS, accès S3, DSN BD/Redis) n'est
  écrit dans les ADR ni dans le dépôt ; ils sont injectés hors dépôt (#5). À rappeler explicitement
  dans ADR-0005 et ADR-0006.
- **PII & journalisation** : ADR-0005 (pas de PII dans les clés d'objet, buckets privés, URL signées)
  et ADR-0006 (**ne jamais logger** OTP, corps de message, numéros de téléphone). Journalisation des
  accès sensibles conservée comme exigence (§11.4) à porter par le backend.
- **Données au repos** : mentionner le chiffrement au repos « si nécessaire » (§11.3) comme suivi,
  sans le surengager.
- **Résidence/hébergement** : le PRD **ne documente aucune contrainte de résidence** des données ;
  cible Afrique de l'Ouest / Côte d'Ivoire → la **latence** et le choix de région d'hébergement sont
  des considérations renvoyées à l'ADR de déploiement (#4/#5), à signaler comme question ouverte et
  **non** comme décision M1.
- **Préférence utilisateur** : aucun marqueur « généré par IA » dans les ADR/commits/PR.

## Testing Plan

Aucun code → pas de tests unitaires/intégration/e2e. La « validation » est documentaire et porte sur
les critères d'acceptation :

- **Présence & couverture** : vérifier qu'il existe un ADR pour chacune des 6 briques majeures
  (mobile, web, backend, BD+cache, stockage, notifications). Un contrôle simple (grep/script de revue,
  exécuté manuellement ou en CI ultérieure) peut confirmer que `docs/adr/` contient les fichiers
  `0001`–`0006`.
- **Complétude de chaque ADR** : chaque fichier comporte les sections du gabarit (Statut, Contexte,
  Options, Décision, Justification, Conséquences) et une **justification du compromis** explicite
  (coût/écosystème/Android entrée de gamme).
- **Aucune décision ouverte (acceptation clé)** : vérifier qu'aucun ADR de stack n'est en statut
  `Proposé`/`Ouvert` (tous `Accepté`) — p. ex. un grep sur `Statut :` ne doit pas renvoyer
  « Proposé » pour 0001–0006. Les sous-décisions différées sont explicitement marquées « à confirmer »
  et rattachées à une issue ultérieure, donc ne comptent pas comme décision majeure ouverte.
- **Liens** : l'index `docs/adr/README.md` et le README §4 pointent vers des fichiers existants
  (pas de lien mort).
- **Doc** : optionnellement, un lint Markdown (si introduit en #4) ; non bloquant ici.

## Documentation Updates

- **Nouveaux** : 0000–0006 sous `docs/adr/` + `docs/adr/README.md` (index).
- **README.md §4** : référencer les ADR comme source de vérité de la stack (garder le tableau comme
  résumé, ajouter les liens). §7 inchangé ici (le test gate concret reste à #6) mais peut renvoyer à
  ADR-0001/0003 pour expliquer d'où viennent `flutter test` / `pytest`.
- **BACKLOG.md** : pas de modification de contenu requise ; l'issue #1 reste la définition.
- **specs/** : la présente spec (`specs/choix-stack-technique-adr.md`).

## Risks and Open Questions

- **Sign-off Flutter vs React Native** : la décision Flutter est cohérente avec le backlog (gras) et
  l'orientation `flutter test` déjà tracée ; à confirmer formellement par l'équipe (compétences Dart
  disponibles ?). Ce n'est pas une question bloquante pour rédiger l'ADR, mais l'ADR doit acter le
  compromis.
- **Une vs deux applications web** (gérant / admin) : sous-décision d'arborescence renvoyée à #2 ;
  signalée dans ADR-0002 sans bloquer le choix Next.js.
- **Sous-choix backend** : ORM + migrations, runner de tâches async, libs JWT/hash → différés à
  #3/#5/#6 ; à lister en *Conséquences* d'ADR-0003/0004, non bloquants pour M1.
- **Fournisseur SMS concret** (agrégateur local CI/Afrique de l'Ouest) et **fournisseur de stockage
  objet** : décisions opérationnelles différées à #5/#4 ; les ADR fixent **canal/interface**, pas le
  prestataire.
- **Plateforme d'hébergement & région / résidence des données** : non documentée par le PRD ; renvoyée
  à un ADR de déploiement (#4/#5). L'outillage du dépôt expose une intégration **Railway** (skill +
  MCP) : candidat plausible à évaluer, mais **ne pas présumer** le choix dans #1.
- **Versions de référence** (Flutter/Dart, Python, PostgreSQL, Redis, Node) : à arrêter en #2 ;
  les ADR peuvent indiquer une fourchette sans la figer prématurément.
- **Confirmation de cadrage** : faut-il un ADR-0000 (processus) ? Recommandé ici ; si l'équipe préfère
  s'en passer, le gabarit peut vivre dans `docs/adr/README.md`.

## Implementation Checklist

1. Créer le répertoire `docs/adr/`.
2. Rédiger `docs/adr/0000-processus-et-gabarit-adr.md` (format MADR simplifié, numérotation, statuts,
   langue française) — *recommandé*.
3. Rédiger `docs/adr/0001-app-mobile-flutter.md` : options Flutter vs React Native, décision Flutter,
   justification (Android prioritaire, cible entrée de gamme, rendu cohérent, perf), conséquences
   (test gate mobile, `app-mobile/`, CI mobile).
4. Rédiger `docs/adr/0002-web-gerant-admin-nextjs.md` : Next.js (React/TS) pour gérant + admin,
   justification (SSR/perf, écosystème, responsive), question ouverte « 1 app vs 2 apps » renvoyée à #2.
5. Rédiger `docs/adr/0003-backend-fastapi.md` : FastAPI vs Django REST → FastAPI, API REST + JWT,
   justification (async, perf, OpenAPI, légèreté), sous-choix différés (ORM/migrations, runner async,
   libs JWT/hash) listés en conséquences ; ancrer les exigences §11.1.
6. Rédiger `docs/adr/0004-donnees-postgresql-redis.md` : PostgreSQL (relationnel, contraintes §8) +
   Redis (cache, broker, OTP/TTL, anti-bruteforce, révocation refresh) ; versions à confirmer.
7. Rédiger `docs/adr/0005-stockage-objet-s3-compatible.md` : API S3-compatible agnostique du
   fournisseur ; sécurité (buckets privés, URL signées, pas de PII en clé, secrets hors dépôt).
8. Rédiger `docs/adr/0006-notifications-fcm-sms.md` : FCM (push) + SMS (agrégateur, OTP) async via
   Redis ; WhatsApp en V2 ; ne jamais logger OTP/PII ; fournisseur SMS différé à #5.
9. Créer `docs/adr/README.md` : index `ADR | Titre | Statut | Issue` (0000–0006).
10. Mettre à jour `README.md` §4 pour référencer `docs/adr/` comme source de vérité de la stack
    (conserver le tableau résumé + liens).
11. Vérifier les critères d'acceptation : un ADR par décision majeure ; justification du compromis
    présente ; statut `Accepté` partout ; aucune décision de stack majeure laissée ouverte pour M1 ;
    liens valides ; aucun marqueur « généré par IA ».
