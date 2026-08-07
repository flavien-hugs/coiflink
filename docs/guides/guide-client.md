# Guide client — Réserver dans un salon

> Guide utilisateur de l'**application mobile** CoifLink (issue #53, parcours Must §5.1).
> Il décrit ce que vous pouvez faire **aujourd'hui** depuis l'application. Les étapes prévues mais
> pas encore visibles à l'écran sont regroupées dans des encadrés **« À venir »**.

Ce guide s'adresse aux **clients**. Il vous accompagne, tâche par tâche, pour trouver un salon,
réserver un rendez-vous, le modifier ou l'annuler, et consulter votre historique. Les montants sont
en **FCFA** et les horaires suivent le fuseau **Africa/Abidjan**.

---

## 1. Avant de commencer

L'application CoifLink est prévue d'abord pour les téléphones **Android**.

Pour réserver, vous devez être **connecté** avec un compte client.

**Pour vous connecter :**

1. Ouvrez l'application.
2. Sur l'écran de connexion, saisissez votre **identifiant** et votre **mot de passe**.
3. Touchez **« Se connecter »**.

**Résultat attendu.** L'application vous laisse continuer votre réservation.

**Si la connexion échoue.** Un message vous indique de vérifier vos informations. Recommencez avec le
bon identifiant et le bon mot de passe.

> **À venir.** Pour l'instant, l'application propose seulement l'écran de **connexion**. Il n'y a pas
> encore d'écran pour **créer un compte** ni pour **réinitialiser un mot de passe oublié** depuis
> l'application. Vous devez donc déjà disposer d'un compte pour vous connecter ; sa création se fait
> par un autre canal au lancement.

> **Bon à savoir.** Au lancement, votre session peut être perdue si vous fermez complètement puis
> rouvrez l'application. Il suffit alors de vous reconnecter.

---

## 2. Trouver un salon

L'écran d'accueil affiche la **liste des salons**.

**Pour trouver un salon :**

1. Saisissez un mot dans la **barre de recherche** (par exemple un nom de salon). La liste se met à
   jour au fur et à mesure.
2. Pour n'afficher que les salons d'une ville, utilisez le **filtre par ville**.
3. Faites défiler la liste : d'autres salons se chargent automatiquement quand vous atteignez le bas.

**Comprendre les badges.** Chaque salon porte une pastille :

- **« Réservable »** : le salon accepte les réservations, vous pouvez prendre rendez-vous.
- **« Bientôt disponible »** : le salon est présent mais ne prend pas encore de réservation (il n'a
  pas fini de configurer ses horaires).

**Résultat attendu.** Touchez un salon pour ouvrir sa fiche.

**Si la liste est vide.** Un message neutre s'affiche (aucun salon ne correspond à votre recherche).
Essayez un autre mot ou retirez le filtre de ville. En cas de problème de connexion, un message vous
propose de **réessayer**.

---

## 3. Consulter un salon

La **fiche d'un salon** rassemble tout ce qu'il faut savoir avant de réserver :

- son **logo**, son **nom** et sa **localisation** ;
- ses **horaires d'ouverture**, jour par jour ;
- ses **prestations** avec leur **prix** (en FCFA) ;
- son **numéro de téléphone** ;
- un bouton **« Réserver »**.

Le bouton **« Réserver »** est actif si le salon est réservable. S'il affiche **« Bientôt
disponible »**, le salon n'accepte pas encore de rendez-vous — repassez plus tard.

**Résultat attendu.** Touchez **« Réserver »** pour démarrer votre réservation (voir la section
suivante).

---

## 4. Réserver un rendez-vous

La réservation se fait **étape par étape**. À tout moment, vous pouvez revenir en arrière.

**Pour réserver un rendez-vous :**

1. **Choisissez une prestation** dans la liste du salon (par exemple « Coupe homme »).
2. **Choisissez une date**. Vous pouvez réserver dans les **30 prochains jours**.
3. **Choisissez un créneau** parmi les horaires libres proposés pour cette date.
4. **Ajoutez un commentaire** si vous le souhaitez (facultatif — par exemple une précision pour le
   salon).
5. **Confirmez** votre rendez-vous.

**Résultat attendu.** Votre rendez-vous est créé avec le statut **« En attente »** : le salon doit
encore le confirmer.

**À savoir sur cette version :**

- Vous choisissez **une seule prestation** par rendez-vous.
- La réservation se fait **au niveau du salon** : vous ne choisissez pas un coiffeur précis.
- Vous pouvez réserver jusqu'à **30 jours** à l'avance.

**Cas d'erreur visibles :**

- **« Ce créneau vient d'être pris ».** Quelqu'un a réservé le même horaire avant vous. L'application
  revient à la liste des créneaux, remise à jour : choisissez-en un autre.
- **Connexion requise.** Si vous n'êtes pas connecté au moment de confirmer, l'application vous
  demande de vous **connecter** (voir la section 1), puis vous pouvez terminer.

---

## 5. Après la réservation

Votre rendez-vous apparaît immédiatement dans **« Mes rendez-vous »** (voir la section 6), au statut
**« En attente »**, tant que le salon ne l'a pas confirmé.

> **À venir.** Au lancement, vous **ne recevez pas encore** de SMS ni de notification de
> **confirmation** ou de **rappel**. Ces messages sont bien enregistrés côté salon, mais ils ne sont
> **pas encore envoyés** sur votre téléphone. Pensez donc à **vérifier vous-même** vos rendez-vous
> dans l'application. L'envoi automatique des rappels arrivera dans une prochaine version.

---

## 6. Gérer mes rendez-vous

L'écran **« Mes rendez-vous »** liste vos rendez-vous **actifs** (à venir ou en attente). Chaque
rendez-vous propose deux actions : **Modifier** et **Annuler**.

> Ces actions sont **désactivées** pour un rendez-vous déjà terminé ou clôturé : on ne modifie ni
> n'annule un rendez-vous passé.

### Modifier un rendez-vous

1. Ouvrez **« Mes rendez-vous »**.
2. Sur le rendez-vous concerné, touchez **« Modifier »**.
3. Le parcours de réservation se rouvre, **pré-rempli** : ajustez la prestation, la date ou le
   créneau, puis confirmez.

**Résultat attendu.** Votre rendez-vous est mis à jour avec le nouveau créneau.

### Annuler un rendez-vous

1. Ouvrez **« Mes rendez-vous »**.
2. Sur le rendez-vous concerné, touchez **« Annuler »**.
3. Une fenêtre de confirmation s'ouvre. Vous pouvez saisir un **motif** (facultatif).
4. Confirmez l'annulation.

**Résultat attendu.** Le rendez-vous est annulé et **disparaît** de la liste des rendez-vous actifs.

**Cas d'erreur visibles :**

- Si le rendez-vous n'est plus annulable (par exemple parce que son statut a changé entre-temps), un
  message vous l'indique et la liste se met à jour.
- Si votre session a expiré, l'application vous demande de vous **reconnecter**.

---

## 7. Mon historique

L'écran **« Mon historique »** liste vos rendez-vous **terminés**, en **lecture seule**.

Pour chaque rendez-vous terminé, vous retrouvez :

- la **date** et les **horaires** ;
- le statut **« Terminé »** ;
- les **prestations** réalisées et leur **montant** (en FCFA), tels qu'ils étaient au moment du
  rendez-vous.

Un rendez-vous terminé ne peut plus être modifié ni annulé.

**Si vous n'avez pas encore de rendez-vous terminé.** Un message neutre s'affiche (« aucun rendez-vous
terminé ») — ce n'est pas une erreur.

> **À venir.** Le **reçu de paiement** n'est **pas encore consultable** dans l'application. Votre
> paiement est bien enregistré par le salon, mais l'écran qui vous montrera le reçu arrivera dans une
> prochaine version.

---

## D'où vient chaque fonctionnalité

Ce tableau relie chaque section à sa source produit, pour faciliter la maintenance de ce guide.

| Section du guide | Fonctionnalité produit | Source |
| --- | --- | --- |
| 1. Avant de commencer / se connecter | Connexion cliente minimale | #22 |
| 2. Trouver un salon | Recherche / liste des salons | #18 |
| 3. Consulter un salon | Fiche salon | #19 |
| 4. Réserver un rendez-vous | Tunnel de réservation | #22 (créneaux #21) |
| 5. Après la réservation (« À venir ») | Confirmation / rappel enregistrés, non envoyés | #45 / #46 |
| 6. Modifier un rendez-vous | Modification côté client | #23 |
| 6. Annuler un rendez-vous | Annulation avec motif facultatif | #24 |
| 7. Mon historique | Rendez-vous terminés (lecture seule) | #30 |
| 7. « À venir » : reçu | Reçu de paiement (côté serveur seulement) | #38 |
