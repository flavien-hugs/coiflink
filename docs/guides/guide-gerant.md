# Guide gérant — Piloter mon salon

> Guide utilisateur de l'**interface web** CoifLink (issue #53, parcours Must §5.2 et §5.3).
> Il décrit ce que vous pouvez faire **aujourd'hui** depuis votre espace gérant. Les étapes prévues
> mais pas encore visibles à l'écran sont regroupées dans des encadrés **« À venir »**.

Ce guide s'adresse aux **gérants de salon**. Il vous accompagne, tâche par tâche, pour configurer votre
salon, gérer le planning et les rendez-vous, encaisser un paiement, suivre vos clients et lire votre
tableau de bord. Vous travaillez dans un **navigateur web**. Les montants sont en **FCFA** et les
horaires suivent le fuseau **Africa/Abidjan**.

> **Ce que vous voyez.** Vous ne voyez que **votre** salon et ses données. Vous ne voyez jamais les
> salons ni les clients d'un autre gérant. C'est une règle de sécurité du produit.

---

## 1. Se connecter

1. Ouvrez la page de **connexion** dans votre navigateur.
2. Saisissez votre **identifiant** et votre **mot de passe** de gérant.
3. Cliquez sur **« Se connecter »**.

**Résultat attendu.** Vous arrivez sur votre **tableau de bord** (`/gerant`).

**Pour vous déconnecter.** Cliquez sur le bouton de **déconnexion** dans l'en-tête. Vous êtes renvoyé
vers la page de connexion.

> **Sécurité.** Votre session est protégée : si elle expire, vous êtes automatiquement renvoyé vers la
> page de connexion. Reconnectez-vous simplement pour continuer.

---

## 2. Configurer mon salon

**À faire en premier.** Tant que votre salon n'est pas configuré, il ne peut **pas** recevoir de
réservations. Cette section est donc le point de départ.

Rendez-vous dans la section **Paramètres**.

### 2.1 Créer le salon

Si vous n'avez pas encore de salon, un **formulaire de création** s'affiche.

1. Renseignez les **informations générales** (nom, description, téléphone) et la **localisation**.
2. Ajoutez, si vous le souhaitez, un **logo** et des **photos**.
3. Enregistrez.

**Résultat attendu.** Votre salon est créé et sa fiche « Informations générales / Localisation »
s'affiche.

### 2.2 Saisir les horaires d'ouverture

Tant que vous n'avez pas d'horaires valides, un **bandeau** vous invite à les configurer, et votre
salon **n'est pas encore réservable**.

1. Sous la fiche du salon, ouvrez l'**éditeur d'horaires**.
2. Pour chacun des 7 jours, indiquez si le salon est **fermé** ou **ouvert**, et sur quels
   **créneaux** (vous pouvez définir plusieurs plages horaires dans la journée pour gérer une pause).
3. Ajoutez au besoin des **jours exceptionnels** (une date fermée, ou avec des horaires ponctuels).
4. Enregistrez.

**Résultat attendu.** Dès que des horaires valides sont enregistrés, votre salon devient
**réservable** : le bandeau d'avertissement **disparaît** et le salon apparaît comme « Réservable »
côté client.

> Le fuseau horaire (**Africa/Abidjan**) n'est pas modifiable dans cette version.

### 2.3 Ajouter les prestations

Ouvrez la section **Prestations**.

1. Utilisez le **formulaire d'ajout** pour créer une prestation : **nom**, **prix** (FCFA), **durée**,
   catégorie et description.
2. La prestation apparaît dans le **catalogue** du salon.
3. Vous pouvez **modifier une prestation en ligne**, ou la **désactiver** (elle reste visible dans
   votre catalogue avec le badge « Désactivée », mais n'est plus proposée aux clients).

**Résultat attendu.** Vos prestations et leurs prix sont visibles par les clients sur la fiche du
salon, et disponibles à la réservation.

**Cas d'erreur visibles.** Si une saisie n'est pas valide (par exemple un prix négatif ou une durée
vide), un message vous l'indique avant l'enregistrement.

---

## 3. Gérer le planning et les rendez-vous

Ouvrez la section **Planning**. Elle affiche les rendez-vous de votre salon.

1. Choisissez la vue **Jour**, **Semaine** ou **Mois**.
2. Les rendez-vous sont regroupés **par statut** (par exemple en attente, confirmés, terminés).

**Pour traiter un rendez-vous, vous pouvez :**

- **Confirmer** un rendez-vous en attente ;
- **Refuser** un rendez-vous ;
- le marquer **Terminé** une fois la prestation réalisée ;
- le marquer **Absent** si le client ne s'est pas présenté ;
- **assigner un coiffeur** au rendez-vous.

**Résultat attendu.** Le statut du rendez-vous est mis à jour dans le planning.

> **À venir.** Le client n'est **pas encore prévenu automatiquement** (SMS / notification) quand vous
> confirmez, refusez ou modifiez son rendez-vous : le message est enregistré mais **pas encore
> envoyé**. De même, la **notification au salon** lors d'une nouvelle réservation est enregistrée mais
> n'apparaît pas encore dans une liste dédiée à l'écran.

---

## 4. Encaisser un paiement

Ouvrez la section **Encaissements**.

### 4.1 Enregistrer un paiement

1. Sélectionnez la **prestation à encaisser**.
2. Le **montant** est **pré-rempli** avec le prix de la prestation. C'est une aide à la saisie : le
   montant doit **correspondre** à la prestation.
3. Choisissez le **mode de paiement** (espèces, mobile money, carte ou autre).
4. Ajoutez une **référence** si vous le souhaitez (facultatif).
5. Enregistrez.

**Résultat attendu.** Le paiement est enregistré et validé, puis apparaît dans l'historique des
transactions (ci-dessous).

**Cas d'erreur visibles :**

- **« Le montant ne correspond pas à la prestation. »** Le montant saisi diffère du prix attendu :
  corrigez-le pour qu'il corresponde.
- **« Prestation ou rendez-vous introuvable pour ce salon. »** La prestation choisie n'appartient pas
  à votre salon : sélectionnez-en une de votre catalogue.

### 4.2 Consulter l'historique des transactions

Sous le formulaire, la vue **Historique des transactions** liste les paiements de votre salon, du plus
récent au plus ancien.

Vous pouvez **filtrer** la liste par :

- **date** (une plage de jours) ;
- **client** ;
- **montant** ;
- **mode de paiement**.

**Résultat attendu.** La liste affiche les transactions correspondant à vos filtres (date et heure au
fuseau Africa/Abidjan, client, montant en FCFA, mode et statut).

**Si aucune transaction ne correspond.** Un message neutre s'affiche (« Aucune transaction ne
correspond à ces filtres. ») — ce n'est pas une erreur.

> **À venir.** La consultation du **journal de caisse** et la **correction d'un écart** de caisse ne
> sont **pas encore disponibles** dans l'interface web (elles existent côté serveur). L'historique des
> transactions ci-dessus, lui, est bien disponible.

---

## 5. Suivre mes clients

Ouvrez la section **Clients**. Elle rassemble les fiches clients de **votre** salon.

### 5.1 Créer une fiche client

1. Ouvrez le **formulaire de création** de fiche.
2. Renseignez le **nom** (obligatoire), et si vous le souhaitez le **téléphone**, le **genre** et des
   **notes internes**.
3. Enregistrez.

**Résultat attendu.** La fiche apparaît dans votre fichier client. Vous pouvez rechercher une fiche
par nom, téléphone ou note.

**Cas d'erreur visible.** Si une fiche existe déjà avec le même numéro de téléphone dans votre salon,
un message vous l'indique (« Une fiche existe déjà pour ce numéro dans ce salon. »).

### 5.2 Consulter une fiche client

Depuis le fichier client, ouvrez une fiche via **« Voir l'historique »**. La page de détail présente :

- un **résumé** : nombre de visites terminées, dernière visite, total dépensé ;
- l'**historique des visites** : pour chaque visite terminée, la date, le créneau, les prestations et
  leur montant (FCFA) ;
- les **prestations préférées** : le classement des prestations les plus fréquentes de ce client
  (nombre de fois et montant cumulé) ;
- la **note privée** du salon (voir ci-dessous).

**Si le client n'a pas encore de visite terminée.** Un message neutre s'affiche (« Aucune visite
terminée pour ce client ») — ce n'est pas une erreur.

### 5.3 Tenir la note privée

Sur la fiche, le panneau **« Note privée »** vous permet de noter les préférences, allergies ou
habitudes du client.

1. Saisissez ou modifiez le texte dans la zone prévue.
2. Cliquez sur **« Enregistrer »** pour remplacer la note, ou sur **« Effacer »** pour la retirer.

> **Confidentialité.** La note privée est **visible uniquement par votre salon** — elle n'est
> **jamais** partagée avec le client. Cette garantie fait partie du produit ; ne notez rien que vous
> ne pourriez pas assumer en interne.

---

## 6. Lire mon tableau de bord

Le **tableau de bord** (page d'accueil `/gerant`) résume l'activité de votre salon. De haut en bas :

- **Rendez-vous du jour**, par statut : **Total**, **Confirmés**, **Annulés**, **Terminés**,
  **Absents**.
- **Chiffre d'affaires** : **Jour**, **Semaine** (du lundi au dimanche) et **Mois** (mois civil), en
  FCFA.
- **Prestations les plus demandées** : un classement de vos prestations, avec une bascule
  **Volume / Revenu** (le nombre de fois réalisées, ou le montant généré).
- **Clients actifs** : la répartition de vos clients sur le mois en cours — **Nouveaux**,
  **Récurrents** et **Inactifs**.
- **Performance des coiffeurs** : une ligne par coiffeur — prestations réalisées, chiffre d'affaires
  généré et taux d'annulation.

**États vides légitimes.** Si votre salon n'a pas encore d'activité sur la période, les tuiles
affichent **0** et les classements indiquent un message du type « Aucune prestation réalisée sur la
période » ou « Aucun coiffeur assigné sur la période ». C'est normal — ce n'est pas une erreur.

---

## 7. (Optionnel) Espace coiffeur

Si vous avez des coiffeurs, chacun dispose de son propre espace **« Mon planning »**, séparé du vôtre.
Un coiffeur y consulte **son** planning assigné, en **lecture seule** : il voit ses rendez-vous
(vues jour / semaine / mois) mais ne peut pas en changer le statut. La gestion des statuts reste de
votre ressort (section 3).

---

## 8. Ce qui n'est pas encore dans l'interface

Pour éviter toute confusion, voici les étapes prévues par le produit qui **ne sont pas encore
visibles** dans l'interface web au lancement :

> **À venir.**
>
> - **Notifications.** Les messages au client (confirmation, rappel, annulation) et la notification au
>   salon à chaque nouvelle réservation sont **enregistrés** mais **pas encore envoyés / affichés**.
> - **Journal de caisse.** La consultation du journal de caisse et la correction d'écart ne sont pas
>   encore dans l'interface web (l'historique des transactions, lui, l'est — voir la section 4.2).
> - **Zone d'administration.** Il n'y a pas encore d'espace d'administration de la plateforme
>   (indicateurs globaux, supervision) dans l'interface web.
> - **Gestion des employés.** Il n'y a pas encore de page pour créer ou gérer vos coiffeurs depuis
>   l'interface web.

---

## D'où vient chaque fonctionnalité

Ce tableau relie chaque section à sa source produit, pour faciliter la maintenance de ce guide.

| Section du guide | Fonctionnalité produit | Source |
| --- | --- | --- |
| 1. Se connecter | Connexion / déconnexion gérant | #14 |
| 2.1 Créer le salon | Création / consultation du salon | #15 |
| 2.2 Horaires (salon réservable) | Horaires d'ouverture (§8.3) | #16 |
| 2.3 Prestations | Gestion des prestations | #17 |
| 3. Planning et rendez-vous | Planning jour/semaine/mois | #26 |
| 3. Statuts et assignation | Cycle de statuts d'un rendez-vous | #25 |
| 4.1 Enregistrer un paiement | Enregistrement d'un paiement | #33 |
| 4.2 Historique des transactions | Historique filtrable des transactions | #35 |
| 4. « À venir » : journal de caisse | Journal de caisse / correction (côté serveur) | #34 |
| 5.1 Créer une fiche client | Création de fiche client | #28 |
| 5.2 Historique des visites | Historique des visites terminées | #29 |
| 5.2 Prestations préférées | Prestations préférées du client | #31 |
| 5.3 Note privée | Note privée éditable (interne au salon) | #32 |
| 6. Rendez-vous du jour | Décompte des RDV du jour par statut | #39 |
| 6. Chiffre d'affaires | Chiffre d'affaires jour/semaine/mois | #40 |
| 6. Prestations les plus demandées | Prestations les plus demandées | #41 |
| 6. Clients actifs | Segmentation des clients actifs | #42 |
| 6. Performance des coiffeurs | Performance des coiffeurs | #43 |
| 7. Espace coiffeur | Planning assigné en lecture seule | #27 |
| 8. « À venir » : notifications | Notifications émises, non remises | #45 / #46 / #47 / #48 |
| 8. « À venir » : zone admin | KPI globaux / supervision (côté serveur) | #44 / #37 |
| 8. « À venir » : employés | Création de coiffeurs (côté serveur) | #13 |
