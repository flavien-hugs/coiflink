# ADR-0004 : Données — PostgreSQL + Redis

- **Statut** : Accepté
- **Date** : 2026-06-29
- **Décideurs** : équipe CoifLink
- **Issue** : #1
- **Référence PRD** : §10.2 (Base de données, cache/file), §9 (modèle de données), §8.1/§8.2 (règles
  métier), §11.1 (anti-bruteforce, OTP), §12 (performance)

## Contexte et problème

Le domaine CoifLink est fortement **relationnel** (§9 : User, Salon, Service, Appointment,
CustomerProfile, Payment, CashJournal, Notification) avec des **contraintes d'intégrité fortes** :
anti double-réservation d'un créneau (§8.1), paiement obligatoirement lié à une prestation / un
rendez-vous (§8.2). Le PRD §10.2 fixe **PostgreSQL** comme base principale et **Redis** comme
cache / file d'attente. Cette brique n'a pas d'alternative sérieuse à trancher ; l'ADR sert à
**formaliser le rôle de chaque magasin** et à l'ériger en décision *figée* (et non « recommandée »).

## Options envisagées

- **PostgreSQL** comme base relationnelle principale — retenu (pas d'alternative crédible compte
  tenu du modèle §9 et des contraintes §8).
- **Redis** comme cache + broker + magasin de clés à TTL — retenu.
- *(Écartée : une base NoSQL document comme magasin principal, inadaptée aux contraintes
  transactionnelles et d'intégrité relationnelle ci-dessus.)*

## Décision

- **PostgreSQL** est la **base de données relationnelle principale** (ACID, contraintes, transactions).
- **Redis** assure le **cache**, le **broker de tâches asynchrones** et le **stockage de clés à TTL**.

## Justification (compromis)

- **PostgreSQL** : le modèle de données est relationnel (§9) et exige des **garanties
  transactionnelles et des contraintes** pour des règles métier critiques — empêcher la **double
  réservation** d'un même créneau (§8.1), garantir qu'un **paiement est lié** à une prestation/RDV
  (§8.2). ACID, contraintes d'unicité/clés étrangères et transactions répondent directement à ce
  besoin.
- **Redis** sert plusieurs usages complémentaires :
  - **cache de lecture** pour tenir les budgets de performance (recherche salon < 2 s, dashboard
    < 3 s, §12) ;
  - **broker** des jobs asynchrones (notifications push/SMS — voir ADR-0006 et FastAPI async,
    ADR-0003) ;
  - **OTP** de réinitialisation stockés avec **TTL** (expiration automatique, §11.1) ;
  - **compteurs anti-bruteforce** sur les tentatives de connexion (§11.1) ;
  - **liste de révocation** des refresh tokens.
- **Compromis** : pas d'alternative à arbitrer — le PRD fige ces briques ; le coût est
  l'exploitation de deux magasins (Postgres + Redis), assumé car leurs rôles sont distincts et
  complémentaires.

## Conséquences

- **Positives** : intégrité forte côté Postgres ; latence et tâches asynchrones bien servies par
  Redis ; rôles clairement séparés.
- **Négatives / risques** : deux systèmes à exploiter et sauvegarder ; Redis n'est pas la source de
  vérité (données volatiles/à TTL uniquement).
- **Suivi / à confirmer (non bloquant)** :
  - **schéma et migrations** détaillés → issue #3 ;
  - **versions de référence** (p. ex. PostgreSQL 16, Redis 7) → à arrêter en #2/#3 ;
  - **ORM / outil de migrations** côté backend → voir ADR-0003 et #3 ;
  - **sauvegardes automatiques** (§10.2, §12.2) → environnements / #5.
