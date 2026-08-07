# Guides utilisateur CoifLink

> Issue GitHub **#53** — label `docs` · §18 Sprint 6 (M6).
> Ces guides couvrent les **parcours Must** du produit (PRD §5) : réservation client (§5.1),
> gestion d'un rendez-vous côté gérant (§5.2) et encaissement (§5.3). Ils décrivent **uniquement
> ce que l'application fait aujourd'hui**, écran par écran. Les étapes prévues mais pas encore
> visibles à l'écran sont signalées dans des encadrés **« À venir »**.

Bienvenue. Cette section rassemble les guides pas à pas, en français, pour prendre en main CoifLink.
Deux publics, deux guides :

| Guide | Pour qui | Sur quelle plateforme | Ce qu'il couvre |
| --- | --- | --- | --- |
| **[Guide client](./guide-client.md)** | Le client qui veut réserver | Application mobile (Android en priorité) | Trouver un salon, réserver, modifier ou annuler un rendez-vous, consulter son historique |
| **[Guide gérant](./guide-gerant.md)** | Le responsable d'un salon | Interface web (dans un navigateur) | Configurer son salon, gérer le planning et les rendez-vous, encaisser un paiement, suivre ses clients, lire son tableau de bord |

## Ce qu'il faut avant de commencer

**Pour le client (application mobile) :**

- Un téléphone Android (l'application est prévue d'abord pour Android).
- Un **compte client**. Au lancement, l'inscription depuis l'application n'est pas encore disponible :
  vous devez déjà disposer d'un compte pour vous connecter (voir l'encadré « À venir » du guide client).
- Une connexion Internet.

**Pour le gérant (interface web) :**

- Un ordinateur ou un téléphone avec un navigateur web récent.
- Un **compte gérant** fourni par CoifLink, avec lequel vous vous connectez à la page de connexion.
- Une connexion Internet.

> **Rôles et accès.** Chaque personne ne voit que ce qui la concerne : un client ne voit que ses
> propres rendez-vous, un gérant ne voit que **son** salon, et un coiffeur ne voit que **son**
> planning. C'est une règle de sécurité du produit — elle ne se contourne pas.

## Bon à savoir

- **Langue.** Les guides et l'application sont en **français**.
- **Monnaie.** Les montants sont en **FCFA**.
- **Heures.** Les dates et horaires suivent le fuseau **Africa/Abidjan**.
- **Exemples.** Les noms de salon, numéros de téléphone et montants cités en exemple sont **fictifs**.
- **Captures d'écran.** Ces guides sont **en texte d'abord** : ils ne contiennent pas de captures pour
  l'instant. Si des captures sont ajoutées plus tard, elles devront utiliser un **jeu de données de
  démonstration** — jamais de vraies coordonnées de clients.

## Pour les mainteneurs de la documentation

Ces guides décrivent le produit **tel qu'il est livré aujourd'hui**. Quand une nouvelle fonctionnalité
arrive (par exemple le reçu de paiement dans l'application, le journal de caisse côté web ou la zone
d'administration), pensez à **mettre à jour le guide concerné** et à retirer l'encadré « À venir »
correspondant. Chaque guide se termine par un tableau **« D'où vient chaque fonctionnalité »** qui relie
chaque section à sa source produit (user story / issue), pour retrouver rapidement quoi mettre à jour.

## Références

- [PRD — spécification produit](../../prd-coiflink.md)
- [README du dépôt](../../README.md)
- [Guide client](./guide-client.md)
- [Guide gérant](./guide-gerant.md)
