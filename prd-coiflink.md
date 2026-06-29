# Document d’Exigences Produit — PRD

## Projet : CoifLink — Plateforme digitale de gestion pour salons de coiffure

**Statut :** Version initiale
**Date :** Juin 2026
**Auteur :** Product Team
**Marché cible :** Afrique de l’Ouest, avec priorité sur la Côte d’Ivoire
**Plateformes :** Application mobile client, interface web salon, interface admin CoifLink
**Type de produit :** SaaS métier pour salons de coiffure

---

# 1. Vision du Produit & Objectifs Stratégiques

## 1.1 Vision

CoifLink a pour ambition de devenir la plateforme de référence pour la digitalisation des salons de coiffure en Afrique de l’Ouest.

La plateforme permet aux salons de gérer leurs rendez-vous, leurs clients, leurs prestations, leurs encaissements, leurs employés et leurs statistiques depuis une interface simple et moderne.

Pour les clients, CoifLink permet de trouver un salon, consulter les disponibilités, réserver un rendez-vous, recevoir des rappels et réduire le temps d’attente sur place.

À long terme, CoifLink doit évoluer vers un écosystème complet intégrant le paiement Mobile Money, la fidélisation, la vente de produits de beauté, la gestion des stocks, la gestion multi-salons et une borne intelligente d’accueil.

---

## 1.2 Problème à résoudre

De nombreux salons de coiffure fonctionnent encore avec des méthodes manuelles : carnet papier, WhatsApp, appels téléphoniques, caisse non contrôlée et absence de suivi client.

Cela entraîne plusieurs problèmes :

* Mauvaise organisation des rendez-vous.
* Files d’attente longues et imprévisibles.
* Clients oubliés ou mal planifiés.
* Difficulté à savoir quel coiffeur est disponible.
* Fraudes ou écarts de caisse.
* Absence d’historique client.
* Faible capacité à fidéliser les clients.
* Manque de visibilité sur les revenus réels du salon.
* Difficulté à mesurer les prestations les plus rentables.

CoifLink répond à ces problèmes en centralisant la gestion du salon dans une solution numérique simple, rapide et adaptée au terrain.

---

## 1.3 Objectif principal

Digitaliser la gestion opérationnelle, commerciale et financière des salons de coiffure.

---

## 1.4 Objectifs spécifiques

* Faciliter la prise de rendez-vous à distance.
* Réduire les files d’attente.
* Réduire les fraudes liées aux encaissements.
* Améliorer l’expérience client.
* Structurer la gestion des employés.
* Fidéliser les clients grâce à l’historique et aux rappels.
* Fournir des statistiques fiables aux gérants.
* Préparer l’intégration future des paiements digitaux et de la borne intelligente.

---

# 2. Utilisateurs Cibles & Personas

## 2.1 Client

Le client est une personne qui souhaite réserver une prestation dans un salon sans devoir appeler, se déplacer ou attendre longtemps.

### Besoins principaux

* Trouver un salon disponible.
* Consulter les prestations et les prix.
* Réserver un rendez-vous.
* Modifier ou annuler un rendez-vous.
* Recevoir des notifications.
* Voir l’historique de ses visites.
* Réduire son temps d’attente.

### Persona

**Aïcha, 27 ans — Cliente active**

Aïcha travaille à Abidjan et se coiffe régulièrement. Elle veut pouvoir réserver un créneau depuis son téléphone, savoir si le salon est disponible et éviter de perdre du temps en file d’attente.

---

## 2.2 Gérant du salon

Le gérant est le propriétaire ou responsable du salon. Il veut contrôler l’activité, les employés, les revenus et la satisfaction client.

### Besoins principaux

* Créer et configurer son salon.
* Gérer les horaires d’ouverture.
* Gérer les prestations et les prix.
* Suivre les rendez-vous.
* Suivre les encaissements.
* Contrôler les opérations de caisse.
* Consulter les statistiques.
* Gérer les employés.
* Réduire les fraudes.

### Persona

**M. Kouadio, 38 ans — Gérant de salon**

M. Kouadio possède un salon avec 5 coiffeurs. Il constate souvent des écarts entre les prestations réalisées et l’argent en caisse. Il veut une solution simple pour suivre les rendez-vous, les paiements et les performances du salon.

---

## 2.3 Coiffeur

Le rôle coiffeur est facultatif dans le MVP. Il peut être activé pour les salons structurés ayant plusieurs employés.

### Besoins principaux

* Consulter son planning.
* Voir les rendez-vous qui lui sont assignés.
* Valider une prestation réalisée.
* Indiquer sa disponibilité.
* Signaler un retard ou une annulation.

### Persona

**Serge, 31 ans — Coiffeur**

Serge travaille dans un salon très fréquenté. Il veut voir rapidement ses rendez-vous du jour et savoir quel client il doit prendre en charge.

---

## 2.4 Administrateur CoifLink

L’administrateur CoifLink supervise la plateforme, les salons inscrits et le support utilisateur.

### Besoins principaux

* Gérer les comptes salons.
* Voir les salons actifs/inactifs.
* Suivre l’usage de la plateforme.
* Aider les utilisateurs.
* Gérer les abonnements.
* Superviser les incidents.
* Contrôler la qualité du service.

---

# 3. Périmètre du MVP

## 3.1 Objectif du MVP

Livrer une première version fonctionnelle permettant à un salon de :

* Créer son compte.
* Configurer son salon.
* Ajouter ses prestations.
* Gérer ses rendez-vous.
* Gérer ses clients.
* Enregistrer ses encaissements.
* Suivre son activité via un tableau de bord.
* Envoyer des notifications de rendez-vous.

---

## 3.2 Modules MVP

Le MVP est composé de 7 modules principaux :

1. Authentification
2. Gestion des salons
3. Rendez-vous
4. Gestion clients
5. Encaissement
6. Tableau de bord
7. Notifications

---

# 4. Rôles & Permissions

| Rôle           | Description                                  | Permissions principales                                               |
| -------------- | -------------------------------------------- | --------------------------------------------------------------------- |
| Client         | Utilisateur final qui réserve une prestation | Réserver, modifier, annuler, consulter l’historique                   |
| Coiffeur       | Employé du salon, facultatif dans le MVP     | Voir planning, confirmer prestation, mettre à jour statut             |
| Gérant         | Responsable du salon                         | Gérer salon, employés, prestations, rendez-vous, caisse, statistiques |
| Admin CoifLink | Super administrateur de la plateforme        | Gérer salons, support, abonnements, supervision globale               |

---

## 4.1 Permissions détaillées

### Client

* Créer un compte.
* Se connecter.
* Consulter les salons.
* Voir les prestations.
* Réserver un rendez-vous.
* Modifier un rendez-vous.
* Annuler un rendez-vous.
* Recevoir une notification.
* Consulter son historique.

### Coiffeur

* Se connecter.
* Voir son planning.
* Voir les clients assignés.
* Marquer une prestation comme réalisée.
* Signaler un client absent.
* Signaler un retard.
* Consulter son historique de prestations.

### Gérant

* Créer un salon.
* Modifier les informations du salon.
* Gérer les horaires.
* Ajouter/modifier/supprimer une prestation.
* Gérer les employés.
* Gérer les rendez-vous.
* Créer une fiche client.
* Enregistrer un paiement.
* Consulter le journal de caisse.
* Voir les statistiques.
* Gérer les notifications.
* Exporter les données essentielles.

### Administrateur CoifLink

* Voir tous les salons inscrits.
* Activer ou désactiver un salon.
* Gérer les comptes utilisateurs.
* Consulter les statistiques globales.
* Gérer les demandes de support.
* Gérer les offres d’abonnement.
* Superviser l’usage de la plateforme.

---

# 5. Parcours Utilisateurs

## 5.1 Parcours client — Réservation de rendez-vous

1. Le client ouvre l’application mobile.
2. Il crée un compte ou se connecte.
3. Il recherche un salon.
4. Il consulte les prestations disponibles.
5. Il choisit une prestation.
6. Il sélectionne une date et une heure.
7. Il confirme la réservation.
8. Il reçoit une notification de confirmation.
9. Il reçoit un rappel avant le rendez-vous.
10. Il se rend au salon.
11. Le salon confirme que la prestation a été réalisée.
12. Le rendez-vous passe dans l’historique du client.

---

## 5.2 Parcours gérant — Gestion d’un rendez-vous

1. Le gérant se connecte à l’interface web.
2. Il consulte le planning du jour.
3. Il voit les rendez-vous confirmés, en attente, annulés ou terminés.
4. Il assigne éventuellement un coiffeur.
5. Il confirme l’arrivée du client.
6. Il marque la prestation comme réalisée.
7. Il enregistre le paiement.
8. Le chiffre d’affaires est automatiquement mis à jour.
9. Le rendez-vous est archivé dans l’historique client.

---

## 5.3 Parcours encaissement

1. Un client termine une prestation.
2. Le gérant ou le caissier sélectionne le rendez-vous.
3. Il choisit le mode de paiement : espèces, Mobile Money manuel, carte ou autre.
4. Il saisit le montant payé.
5. Le système vérifie que le montant correspond à la prestation.
6. Le paiement est enregistré.
7. Une transaction est ajoutée au journal de caisse.
8. Le tableau de bord est mis à jour.
9. Un reçu peut être généré ou envoyé au client.

---

# 6. Exigences Fonctionnelles — Épics & User Stories

## Épic 1 — Authentification

| ID     | User Story                                                                                                | Priorité | Spécifications fonctionnelles                                               |
| ------ | --------------------------------------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------- |
| US-1.1 | En tant que client, je veux créer un compte avec mon numéro de téléphone afin de réserver un rendez-vous. | Must     | Inscription par nom, téléphone, mot de passe. Vérification OTP recommandée. |
| US-1.2 | En tant qu’utilisateur, je veux me connecter à mon compte afin d’accéder à mes informations.              | Must     | Connexion par téléphone/email et mot de passe.                              |
| US-1.3 | En tant qu’utilisateur, je veux réinitialiser mon mot de passe si je l’oublie.                            | Must     | Réinitialisation par OTP SMS ou email.                                      |
| US-1.4 | En tant que gérant, je veux inviter ou créer des employés afin de leur donner accès au salon.             | Should   | Création de comptes employés avec rôles.                                    |

---

## Épic 2 — Gestion des salons

| ID     | User Story                                                                                                                       | Priorité | Spécifications fonctionnelles                                             |
| ------ | -------------------------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------- |
| US-2.1 | En tant que gérant, je veux créer mon salon afin de le rendre visible sur CoifLink.                                              | Must     | Nom, logo, description, téléphone, localisation, photos.                  |
| US-2.2 | En tant que gérant, je veux configurer les horaires d’ouverture afin que les clients réservent uniquement sur les bons créneaux. | Must     | Horaires par jour, jours fermés, pauses, jours exceptionnels.             |
| US-2.3 | En tant que gérant, je veux ajouter mes prestations afin que les clients puissent choisir un service.                            | Must     | Nom prestation, durée, prix, description, catégorie.                      |
| US-2.4 | En tant que client, je veux consulter les informations d’un salon avant de réserver.                                             | Must     | Affichage des horaires, prestations, prix, localisation et disponibilité. |
| US-2.5 | En tant que gérant, je veux modifier les informations du salon à tout moment.                                                    | Should   | Mise à jour des informations depuis le dashboard.                         |

---

## Épic 3 — Rendez-vous

| ID     | User Story                                                                                 | Priorité | Spécifications fonctionnelles                                |
| ------ | ------------------------------------------------------------------------------------------ | -------- | ------------------------------------------------------------ |
| US-3.1 | En tant que client, je veux réserver un rendez-vous afin de garantir mon passage au salon. | Must     | Choix salon, prestation, date, heure, commentaire optionnel. |
| US-3.2 | En tant que client, je veux modifier mon rendez-vous si j’ai un empêchement.               | Must     | Modification possible selon règle du salon.                  |
| US-3.3 | En tant que client, je veux annuler mon rendez-vous.                                       | Must     | Annulation avec motif optionnel. Notification au salon.      |
| US-3.4 | En tant que gérant, je veux confirmer ou refuser un rendez-vous.                           | Must     | Statuts : en attente, confirmé, annulé, terminé, absent.     |
| US-3.5 | En tant que gérant, je veux voir le planning du jour.                                      | Must     | Vue calendrier jour/semaine/mois.                            |
| US-3.6 | En tant que coiffeur, je veux consulter les rendez-vous qui me sont assignés.              | Should   | Planning personnel du coiffeur.                              |
| US-3.7 | En tant que gérant, je veux éviter les doubles réservations.                               | Must     | Vérification automatique des créneaux disponibles.           |

---

## Épic 4 — Gestion clients

| ID     | User Story                                                                     | Priorité | Spécifications fonctionnelles                                              |
| ------ | ------------------------------------------------------------------------------ | -------- | -------------------------------------------------------------------------- |
| US-4.1 | En tant que gérant, je veux créer une fiche client afin de suivre ses visites. | Must     | Nom, téléphone, genre optionnel, notes internes.                           |
| US-4.2 | En tant que gérant, je veux voir l’historique des visites d’un client.         | Must     | Liste des rendez-vous passés, prestations, montants.                       |
| US-4.3 | En tant que gérant, je veux connaître les prestations préférées d’un client.   | Should   | Statistiques par client.                                                   |
| US-4.4 | En tant que client, je veux consulter mon historique de prestations.           | Should   | Historique depuis l’application mobile.                                    |
| US-4.5 | En tant que gérant, je veux ajouter une note client.                           | Could    | Notes privées : préférences, allergies, habitudes, demandes particulières. |

---

## Épic 5 — Encaissement

| ID     | User Story                                                                                                        | Priorité | Spécifications fonctionnelles                                     |
| ------ | ----------------------------------------------------------------------------------------------------------------- | -------- | ----------------------------------------------------------------- |
| US-5.1 | En tant que gérant, je veux enregistrer un paiement après une prestation.                                         | Must     | Montant, mode de paiement, prestation liée, client lié.           |
| US-5.2 | En tant que gérant, je veux consulter l’historique des transactions.                                              | Must     | Liste filtrable par date, client, montant, mode de paiement.      |
| US-5.3 | En tant que gérant, je veux avoir un journal de caisse pour contrôler les entrées.                                | Must     | Journal horodaté, utilisateur ayant enregistré l’opération.       |
| US-5.4 | En tant que gérant, je veux détecter les écarts de caisse.                                                        | Should   | Comparaison entre prestations réalisées et paiements enregistrés. |
| US-5.5 | En tant que client, je veux recevoir une preuve de paiement.                                                      | Could    | Reçu numérique ou notification.                                   |
| US-5.6 | En tant qu’admin CoifLink, je veux superviser les transactions globales sans voir les détails sensibles inutiles. | Should   | Statistiques agrégées par salon.                                  |

---

## Épic 6 — Tableau de bord

| ID     | User Story                                                                | Priorité | Spécifications fonctionnelles                                  |
| ------ | ------------------------------------------------------------------------- | -------- | -------------------------------------------------------------- |
| US-6.1 | En tant que gérant, je veux voir le nombre de rendez-vous du jour.        | Must     | Total, confirmés, annulés, terminés, absents.                  |
| US-6.2 | En tant que gérant, je veux voir mon chiffre d’affaires.                  | Must     | CA journalier, hebdomadaire, mensuel.                          |
| US-6.3 | En tant que gérant, je veux voir les prestations les plus demandées.      | Must     | Classement par volume et revenu généré.                        |
| US-6.4 | En tant que gérant, je veux voir le nombre de clients actifs.             | Must     | Clients nouveaux, récurrents, inactifs.                        |
| US-6.5 | En tant que gérant, je veux suivre la performance des coiffeurs.          | Should   | Nombre de prestations réalisées, CA généré, taux d’annulation. |
| US-6.6 | En tant qu’admin CoifLink, je veux voir les KPI globaux de la plateforme. | Must     | Salons inscrits, abonnements, rendez-vous, revenus plateforme. |

---

## Épic 7 — Notifications

| ID     | User Story                                                                    | Priorité | Spécifications fonctionnelles                                    |
| ------ | ----------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------- |
| US-7.1 | En tant que client, je veux recevoir une confirmation de rendez-vous.         | Must     | Notification push, SMS ou WhatsApp selon disponibilité.          |
| US-7.2 | En tant que client, je veux recevoir un rappel avant mon rendez-vous.         | Must     | Rappel automatique configurable : 24h, 2h ou 30 min avant.       |
| US-7.3 | En tant que salon, je veux être notifié lorsqu’un client réserve.             | Must     | Notification dashboard + option email/SMS.                       |
| US-7.4 | En tant que client, je veux être notifié en cas d’annulation ou modification. | Must     | Notification automatique après changement de statut.             |
| US-7.5 | En tant que gérant, je veux envoyer un message à mes clients.                 | Could    | Campagnes simples : rappel, promotion, fermeture exceptionnelle. |

---

# 7. Écrans du Produit

## 7.1 Application mobile client

### Écran d’accueil

Contenu :

* Logo CoifLink.
* Bouton connexion.
* Bouton inscription.
* Mise en avant des salons populaires.
* Recherche rapide de salon.

### Inscription / Connexion

Champs :

* Nom complet.
* Numéro de téléphone.
* Email optionnel.
* Mot de passe.
* Confirmation OTP si activée.

### Recherche de salons

Fonctionnalités :

* Recherche par nom.
* Filtre par zone.
* Filtre par disponibilité.
* Filtre par type de prestation.
* Affichage liste ou carte.

### Détail salon

Contenu :

* Nom du salon.
* Photos.
* Adresse.
* Horaires.
* Prestations.
* Prix.
* Durée estimée.
* Disponibilités.
* Bouton réserver.

### Réservation

Étapes :

1. Choix de la prestation.
2. Choix de la date.
3. Choix du créneau.
4. Confirmation.
5. Notification.

### Mes rendez-vous

Statuts :

* À venir.
* Confirmé.
* En attente.
* Annulé.
* Terminé.

Actions :

* Modifier.
* Annuler.
* Voir détails.

### Historique

Contenu :

* Prestations passées.
* Salon visité.
* Date.
* Montant.
* Statut.
* Reçu éventuel.

### Profil client

Contenu :

* Informations personnelles.
* Paramètres.
* Notifications.
* Déconnexion.

---

## 7.2 Interface web gérant

### Dashboard principal

Indicateurs :

* Rendez-vous du jour.
* Chiffre d’affaires du jour.
* Nombre de clients.
* Prestations populaires.
* Transactions récentes.
* Alertes importantes.

### Planning

Vues :

* Jour.
* Semaine.
* Mois.

Actions :

* Voir rendez-vous.
* Confirmer.
* Modifier.
* Annuler.
* Assigner un coiffeur.
* Marquer comme terminé.
* Marquer comme absent.

### Clients

Fonctionnalités :

* Liste des clients.
* Recherche.
* Création fiche client.
* Historique client.
* Notes internes.

### Prestations

Fonctionnalités :

* Ajouter une prestation.
* Modifier une prestation.
* Désactiver une prestation.
* Définir prix.
* Définir durée.
* Définir catégorie.

### Encaissements

Fonctionnalités :

* Enregistrer un paiement.
* Voir transactions.
* Filtrer par date.
* Filtrer par mode de paiement.
* Exporter journal de caisse.
* Voir écarts potentiels.

### Employés

Fonctionnalités :

* Ajouter un employé.
* Modifier rôle.
* Activer/désactiver un compte.
* Voir planning employé.
* Voir performance employé.

### Paramètres du salon

Contenu :

* Informations générales.
* Horaires.
* Jours fermés.
* Photos.
* Localisation.
* Modes de paiement acceptés.
* Règles d’annulation.

---

## 7.3 Interface admin CoifLink

### Dashboard admin

Indicateurs :

* Nombre total de salons.
* Salons actifs.
* Clients inscrits.
* Rendez-vous mensuels.
* Revenus d’abonnement.
* Tickets support ouverts.

### Gestion salons

Fonctionnalités :

* Liste des salons.
* Activation/désactivation.
* Consultation détails.
* Statut abonnement.
* Historique d’activité.

### Gestion utilisateurs

Fonctionnalités :

* Liste clients.
* Liste gérants.
* Liste employés.
* Recherche.
* Suspension compte.

### Abonnements

Fonctionnalités :

* Plans tarifaires.
* Salons abonnés.
* Échéances.
* Statut paiement.
* Historique facturation.

### Support

Fonctionnalités :

* Réclamations.
* Demandes d’aide.
* Suivi incidents.
* Notes internes.

---

# 8. Règles Métier

## 8.1 Rendez-vous

* Un rendez-vous doit toujours être lié à un salon.
* Un rendez-vous doit être lié à au moins une prestation.
* Un rendez-vous peut être lié à un coiffeur si le salon active cette option.
* Un créneau ne peut pas être réservé deux fois pour le même coiffeur.
* Un client peut annuler selon les règles définies par le salon.
* Un rendez-vous terminé ne peut plus être modifié, sauf par le gérant.
* Un rendez-vous annulé ne doit pas être comptabilisé dans le chiffre d’affaires.

---

## 8.2 Encaissement

* Un paiement doit être lié à une prestation ou à un rendez-vous.
* Chaque paiement doit avoir un montant, un mode de paiement et un utilisateur responsable.
* Un paiement validé ne peut pas être supprimé définitivement.
* Toute correction de paiement doit créer une opération d’ajustement.
* Le journal de caisse doit être horodaté.
* Les écarts entre prestations réalisées et paiements doivent être visibles.

---

## 8.3 Salon

* Un gérant peut créer un ou plusieurs salons selon son plan.
* Chaque salon possède ses propres prestations, horaires, clients et employés.
* Un salon inactif ne doit plus être visible dans l’application client.
* Un salon sans horaire configuré ne peut pas recevoir de réservation.

---

## 8.4 Notifications

* Une confirmation doit être envoyée après chaque réservation.
* Un rappel doit être envoyé avant le rendez-vous.
* Une annulation doit notifier le client et le salon.
* Les notifications critiques doivent être tracées dans le système.

---

# 9. Modèle de Données Simplifié

## 9.1 User

Champs principaux :

* id
* full_name
* phone
* email
* password_hash
* role
* status
* created_at
* updated_at

Rôles possibles :

* CLIENT
* HAIRDRESSER
* MANAGER
* ADMIN

---

## 9.2 Salon

Champs principaux :

* id
* owner_id
* name
* description
* phone
* address
* city
* commune
* latitude
* longitude
* logo_url
* status
* opening_hours
* created_at
* updated_at

---

## 9.3 Service / Prestation

Champs principaux :

* id
* salon_id
* name
* description
* price
* duration_minutes
* category
* is_active
* created_at
* updated_at

---

## 9.4 Appointment

Champs principaux :

* id
* salon_id
* client_id
* hairdresser_id
* service_id
* appointment_date
* start_time
* end_time
* status
* cancellation_reason
* client_note
* created_at
* updated_at

Statuts :

* PENDING
* CONFIRMED
* CANCELLED
* COMPLETED
* NO_SHOW

---

## 9.5 Customer Profile

Champs principaux :

* id
* salon_id
* user_id
* full_name
* phone
* notes
* last_visit_at
* total_visits
* created_at
* updated_at

---

## 9.6 Payment / Transaction

Champs principaux :

* id
* salon_id
* appointment_id
* client_id
* amount
* payment_method
* status
* recorded_by
* reference
* created_at

Modes de paiement MVP :

* CASH
* MOBILE_MONEY_MANUAL
* CARD_MANUAL
* OTHER

Statuts :

* PENDING
* VALIDATED
* CANCELLED
* ADJUSTED

---

## 9.7 Cash Journal

Champs principaux :

* id
* salon_id
* transaction_id
* operation_type
* amount
* performed_by
* description
* created_at

Types d’opération :

* PAYMENT
* REFUND
* ADJUSTMENT
* CASH_OPENING
* CASH_CLOSING

---

## 9.8 Notification

Champs principaux :

* id
* user_id
* salon_id
* appointment_id
* type
* channel
* title
* message
* status
* sent_at
* created_at

Canaux :

* PUSH
* SMS
* EMAIL
* WHATSAPP
* IN_APP

---

# 10. Architecture Technique

## 10.1 Vue globale

CoifLink sera composé de trois principales interfaces :

1. Application mobile client.
2. Interface web de gestion pour les salons.
3. Interface web admin pour CoifLink.

Ces interfaces communiqueront avec une API backend centralisée.

---

## 10.2 Architecture recommandée

### Frontend

Application mobile :

* Flutter ou React Native.
* Android prioritaire.
* iOS en second lot ou dès le MVP si budget disponible.

Interface web :

* React.js / Next.js.
* Dashboard responsive.
* Interface simple adaptée aux gérants non techniques.

### Backend

Technologies recommandées :

* Python FastAPI ou Django REST Framework.
* API REST.
* Authentification JWT.
* Gestion des rôles et permissions.
* Jobs asynchrones pour notifications.

### Base de données

Base principale :

* PostgreSQL.

Cache et file d’attente :

* Redis.

Stockage fichiers :

* S3 compatible ou stockage cloud sécurisé pour logos et photos salons.

Notifications :

* Firebase Cloud Messaging pour push mobile.
* Service SMS local ou agrégateur.
* WhatsApp Business API en version future.

Déploiement :

* Docker.
* CI/CD GitHub Actions.
* Hébergement cloud sécurisé.
* Sauvegardes automatiques.

---

## 10.3 Schéma logique

Client Mobile
→ API Backend
→ Base de données PostgreSQL
→ Service Notifications
→ Dashboard Salon
→ Dashboard Admin CoifLink

---

## 10.4 Services backend principaux

* Auth Service.
* Salon Service.
* Appointment Service.
* Customer Service.
* Payment Service.
* Notification Service.
* Analytics Service.
* Admin Service.

---

# 11. Sécurité & Conformité

## 11.1 Authentification

* Mot de passe chiffré avec un algorithme sécurisé.
* Connexion par JWT.
* Refresh token sécurisé.
* Réinitialisation par OTP.
* Protection contre les tentatives répétées.

---

## 11.2 Autorisation

* Gestion stricte des rôles.
* Un gérant ne peut voir que les données de son salon.
* Un coiffeur ne peut voir que son planning ou les rendez-vous qui lui sont assignés.
* Un client ne peut voir que ses propres rendez-vous.
* L’admin CoifLink peut superviser la plateforme selon son niveau d’autorisation.

---

## 11.3 Données personnelles

* Collecte minimale des données.
* Consentement utilisateur.
* Possibilité de désactiver un compte.
* Journalisation des accès sensibles.
* Sauvegardes sécurisées.
* Chiffrement des données sensibles au repos si nécessaire.

---

## 11.4 Journalisation

Chaque action importante doit être journalisée :

* Connexion.
* Création rendez-vous.
* Modification rendez-vous.
* Annulation.
* Paiement enregistré.
* Correction de caisse.
* Création employé.
* Modification prestation.
* Désactivation salon.

---

# 12. Exigences Non Fonctionnelles

## 12.1 Performance

* Temps de réponse API inférieur à 3 secondes.
* Chargement du dashboard principal inférieur à 3 secondes.
* Recherche salon inférieure à 2 secondes.
* Création rendez-vous inférieure à 3 secondes.

---

## 12.2 Disponibilité

* Disponibilité cible minimale : 99 %.
* Sauvegarde automatique quotidienne.
* Monitoring des services critiques.
* Alertes en cas d’incident.

---

## 12.3 Expérience utilisateur

* Interface simple et compréhensible.
* Prise en main salon en moins de 30 minutes.
* Réservation client en moins de 5 clics.
* Design mobile-first.
* Support des smartphones Android d’entrée et milieu de gamme.

---

## 12.4 Scalabilité

La plateforme doit pouvoir évoluer vers :

* Plusieurs villes.
* Plusieurs pays.
* Gestion multi-salons.
* Paiements digitaux.
* Borne intelligente.
* Programme de fidélité.
* Marketplace produits de beauté.

---

# 13. KPI de Succès

## 13.1 Adoption

* Nombre de salons inscrits.
* Nombre de salons actifs.
* Nombre de clients inscrits.
* Nombre de clients actifs mensuels.
* Nombre de rendez-vous mensuels.
* Taux d’activation des salons après inscription.

---

## 13.2 Performance opérationnelle

* Taux de rendez-vous honorés.
* Taux d’annulation.
* Taux de no-show.
* Temps moyen d’attente client.
* Nombre de prestations réalisées.
* Nombre de transactions enregistrées.

---

## 13.3 Performance financière

* Chiffre d’affaires suivi via la plateforme.
* Réduction des écarts de caisse.
* Revenu généré par abonnement.
* Revenu moyen par salon.
* Taux de renouvellement abonnement.

---

## 13.4 Satisfaction

* Note moyenne des utilisateurs.
* Taux de rétention clients.
* Taux de rétention salons.
* Nombre de réclamations.
* Temps moyen de résolution support.
* Net Promoter Score, si disponible.

---

# 14. Critères de Réussite du MVP

Le MVP sera considéré comme réussi lorsque :

* Au moins 10 salons utilisent activement la plateforme.
* Au moins 500 clients sont inscrits.
* Au moins 1 000 rendez-vous sont créés sur la plateforme.
* Les rendez-vous sont entièrement gérés via CoifLink dans les salons pilotes.
* Les encaissements sont tracés dans le système.
* Le journal de caisse permet d’identifier les écarts.
* Les utilisateurs expriment une satisfaction supérieure à 80 %.
* Une réduction mesurable des erreurs ou fraudes de caisse est constatée.
* Le temps de réservation client est inférieur à 2 minutes.
* Le dashboard permet au gérant de suivre son activité quotidienne.

---

# 15. Modèle Économique

## 15.1 Modèle SaaS par abonnement

CoifLink peut fonctionner avec un modèle d’abonnement mensuel ou annuel payé par les salons.

### Plan Starter

Cible : petits salons indépendants.

Fonctionnalités :

* 1 salon.
* 1 gérant.
* Gestion rendez-vous.
* Gestion clients.
* Encaissement simple.
* Tableau de bord basique.

### Plan Pro

Cible : salons avec plusieurs coiffeurs.

Fonctionnalités :

* Plusieurs employés.
* Planning par coiffeur.
* Statistiques avancées.
* Journal de caisse détaillé.
* Notifications avancées.
* Export des données.

### Plan Business

Cible : salons premium ou chaînes.

Fonctionnalités :

* Multi-salons.
* Gestion avancée des employés.
* Programme de fidélité.
* Gestion de stock.
* Rapports avancés.
* Support prioritaire.

---

## 15.2 Revenus futurs

* Commission sur paiement Mobile Money.
* Frais sur borne intelligente.
* Vente ou location de borne tactile.
* Marketplace de produits de beauté.
* SMS/WhatsApp premium.
* Publicité locale contrôlée.
* Module de fidélité payant.
* Module IA payant.

---

# 16. Fonctionnalités Futures — Version 2 et Plus

## 16.1 Paiement Mobile Money

Objectif :

Permettre aux clients de payer directement via Mobile Money.

Fonctionnalités :

* Paiement avant rendez-vous.
* Paiement après prestation.
* Acompte obligatoire.
* Remboursement partiel.
* Réconciliation automatique.
* Reçu numérique.

---

## 16.2 Programme de fidélité

Objectif :

Encourager les clients à revenir.

Fonctionnalités :

* Points par prestation.
* Récompenses.
* Réductions.
* Cartes fidélité digitales.
* Offres personnalisées.

---

## 16.3 Vente de produits de beauté

Objectif :

Permettre aux salons de vendre des produits en ligne ou sur place.

Fonctionnalités :

* Catalogue produits.
* Stock simple.
* Paiement.
* Historique d’achat.
* Recommandations.

---

## 16.4 Intelligence artificielle de recommandation

Objectif :

Aider les salons à mieux vendre et mieux fidéliser.

Cas d’usage :

* Recommandation de prestation selon historique client.
* Identification des clients inactifs.
* Suggestion de promotions.
* Prévision des heures de forte affluence.
* Analyse des prestations les plus rentables.

---

## 16.5 Gestion des stocks

Objectif :

Suivre les produits utilisés ou vendus.

Fonctionnalités :

* Entrées de stock.
* Sorties de stock.
* Alertes stock faible.
* Produits consommés par prestation.
* Historique des mouvements.

---

## 16.6 Gestion multi-salons

Objectif :

Permettre à un propriétaire de gérer plusieurs établissements.

Fonctionnalités :

* Dashboard global.
* Statistiques par salon.
* Employés par salon.
* Prestations par salon.
* Comparaison de performances.

---

## 16.7 QR Code de présence

Objectif :

Fluidifier l’arrivée du client au salon.

Fonctionnalités :

* QR code rendez-vous.
* Scan à l’arrivée.
* Confirmation automatique de présence.
* Mise à jour de la file d’attente.

---

# 17. Borne Intelligente d’Accueil

## 17.1 Concept

La borne intelligente d’accueil est un terminal tactile installé dans le salon. Elle permet au client de s’identifier à son arrivée, de confirmer son rendez-vous, de choisir une prestation, de connaître son temps d’attente et d’être orienté vers un coiffeur disponible.

---

## 17.2 Objectifs

* Réduire la charge du personnel à l’accueil.
* Fluidifier la file d’attente.
* Réduire les conflits liés à l’ordre de passage.
* Améliorer l’expérience client.
* Automatiser la présence client.
* Préparer le paiement autonome.

---

## 17.3 Fonctionnalités de la borne

### Identification client

Options :

* Numéro de téléphone.
* QR code de réservation.
* Code de rendez-vous.
* Nom du client.

### Vérification rendez-vous

La borne vérifie :

* Date du rendez-vous.
* Heure.
* Salon.
* Prestation.
* Statut du rendez-vous.

### Choix de prestation

Pour les clients sans rendez-vous, la borne permet de :

* Choisir une prestation.
* Voir le prix.
* Voir la durée estimée.
* Voir les coiffeurs disponibles.

### Gestion de file d’attente

La borne affiche :

* Position dans la file.
* Temps d’attente estimé.
* Coiffeur assigné.
* Statut : en attente, appelé, en cours, terminé.

### Ticket numérique

Après l’enregistrement, le client reçoit :

* Un numéro de passage.
* Une notification.
* Un ticket affiché à l’écran.
* Option d’envoi par SMS ou WhatsApp.

### Paiement

Version future :

* Paiement Mobile Money.
* Paiement par QR code.
* Paiement par carte si terminal disponible.
* Reçu numérique.

---

## 17.4 Parcours borne

1. Le client arrive au salon.
2. Il touche l’écran de la borne.
3. Il choisit “J’ai un rendez-vous” ou “Je viens sans rendez-vous”.
4. Il s’identifie par téléphone ou QR code.
5. La borne vérifie ses informations.
6. Le système confirme sa présence.
7. Le client reçoit son numéro de passage.
8. Le salon voit automatiquement le client dans la file.
9. Le coiffeur disponible prend en charge le client.
10. La prestation est marquée comme en cours puis terminée.
11. Le paiement est enregistré.

---

# 18. Roadmap Produit

## Sprint 0 — Cadrage & Préparation

Durée estimée : 1 à 2 semaines.

Livrables :

* PRD validé.
* Cahier des charges fonctionnel.
* Architecture technique.
* Maquettes UX/UI.
* Backlog initial.
* Choix technologiques.
* Modèle de données initial.
* Plan de tests.
* Environnements de développement.

---

## Sprint 1 — Authentification & Gestion utilisateurs

Durée estimée : 2 semaines.

Fonctionnalités :

* Inscription client.
* Inscription gérant.
* Connexion.
* Réinitialisation mot de passe.
* Gestion rôles.
* Création compte employé.
* Middleware permissions.
* Base du dashboard.

Critères de sortie :

* Un utilisateur peut créer un compte.
* Un gérant peut se connecter.
* Les rôles sont bien séparés.
* Les accès non autorisés sont bloqués.

---

## Sprint 2 — Gestion salons & prestations

Durée estimée : 2 semaines.

Fonctionnalités :

* Création salon.
* Modification salon.
* Horaires d’ouverture.
* Ajout prestations.
* Modification prestations.
* Liste des prestations.
* Détail salon côté client.

Critères de sortie :

* Un gérant peut configurer son salon.
* Un client peut consulter un salon.
* Les prestations sont visibles et réservables.

---

## Sprint 3 — Rendez-vous

Durée estimée : 2 semaines.

Fonctionnalités :

* Création rendez-vous.
* Modification rendez-vous.
* Annulation rendez-vous.
* Confirmation salon.
* Planning salon.
* Statuts rendez-vous.
* Anti double-réservation.

Critères de sortie :

* Un client peut réserver.
* Le salon peut confirmer.
* Le planning se met à jour.
* Les notifications de base sont prêtes.

---

## Sprint 4 — Clients, encaissement & journal de caisse

Durée estimée : 2 semaines.

Fonctionnalités :

* Fiche client.
* Historique client.
* Enregistrement paiement.
* Historique transactions.
* Journal de caisse.
* Correction ou ajustement.
* Liaison paiement/rendez-vous.

Critères de sortie :

* Les paiements sont enregistrés.
* Le journal de caisse est consultable.
* Les prestations réalisées sont liées au chiffre d’affaires.

---

## Sprint 5 — Dashboard & notifications

Durée estimée : 2 semaines.

Fonctionnalités :

* Dashboard gérant.
* KPI salon.
* Prestations populaires.
* CA journalier/mensuel.
* Clients actifs.
* Notifications confirmation.
* Notifications rappel.
* Notifications annulation.

Critères de sortie :

* Le gérant suit son activité.
* Le client reçoit ses notifications.
* Les KPI MVP sont visibles.

---

## Sprint 6 — Tests, corrections & mise en production

Durée estimée : 2 semaines.

Livrables :

* Tests fonctionnels.
* Tests de sécurité.
* Tests de performance.
* Corrections bugs.
* Documentation utilisateur.
* Déploiement production.
* Formation salons pilotes.
* Suivi post-lancement.

Critères de sortie :

* MVP stable.
* 10 salons pilotes prêts.
* Données de test validées.
* Monitoring activé.
* Support opérationnel.

---

# 19. Organisation de l’Équipe

| Rôle                     | Responsabilité                                          |
| ------------------------ | ------------------------------------------------------- |
| Chef de projet           | Coordination globale, suivi planning, arbitrage         |
| Product Owner            | Vision produit, priorisation backlog, validation métier |
| Business Analyst         | Cahier des charges, règles métier, user stories         |
| UX/UI Designer           | Maquettes, parcours utilisateur, design system          |
| Développeur Backend      | API, base de données, sécurité, logique métier          |
| Développeur Frontend Web | Dashboard salon, dashboard admin                        |
| Développeur Mobile       | Application client Android/iOS                          |
| Testeur QA               | Tests fonctionnels, régression, validation MVP          |
| DevOps                   | CI/CD, déploiement, monitoring, sauvegardes             |
| Support Client           | Accompagnement salons, remontée incidents               |

---

# 20. Risques & Mesures de Mitigation

## Risque 1 — Faible adoption par les salons

Cause possible :

Les gérants peuvent être peu habitués aux outils numériques.

Mitigation :

* Interface très simple.
* Formation courte.
* Support WhatsApp.
* Offre d’essai gratuite.
* Accompagnement des premiers salons.

---

## Risque 2 — Mauvaise utilisation de la caisse

Cause possible :

Les employés peuvent ne pas enregistrer tous les paiements.

Mitigation :

* Journal de caisse obligatoire.
* Historique non supprimable.
* Écarts visibles.
* Permissions limitées.
* Rapports quotidiens.

---

## Risque 3 — Clients qui ne se présentent pas

Cause possible :

Réservations sans engagement.

Mitigation :

* Rappels automatiques.
* Statut no-show.
* Score de fiabilité client.
* Acompte en version future.

---

## Risque 4 — Problèmes réseau

Cause possible :

Connexion instable dans certains salons.

Mitigation :

* Interface légère.
* Cache local limité.
* Synchronisation différée pour certaines actions.
* Optimisation API.

---

## Risque 5 — Complexité de la borne intelligente

Cause possible :

Coût matériel, maintenance, adoption.

Mitigation :

* Lancer d’abord sans borne.
* Tester la borne sur 2 ou 3 salons pilotes.
* Prévoir une version tablette Android.
* Simplifier le parcours borne.

---

# 21. Hors Périmètre MVP

Les fonctionnalités suivantes ne sont pas incluses dans le MVP :

* Paiement Mobile Money automatisé.
* Programme de fidélité.
* Vente de produits de beauté.
* Gestion complète des stocks.
* IA de recommandation.
* Gestion multi-salons avancée.
* Borne intelligente.
* QR code de présence.
* Application coiffeur dédiée.
* Marketplace publique.
* Publicité salon.
* Système d’avis clients avancé.

---

# 22. Priorisation MoSCoW

## Must Have

* Authentification.
* Création salon.
* Gestion prestations.
* Réservation rendez-vous.
* Modification/annulation rendez-vous.
* Planning salon.
* Gestion clients.
* Enregistrement paiement.
* Journal de caisse.
* Dashboard basique.
* Notifications de confirmation et rappel.

---

## Should Have

* Gestion employés.
* Planning par coiffeur.
* Statistiques avancées.
* Historique client détaillé.
* Reçu numérique.
* Export journal de caisse.
* Notifications SMS/WhatsApp.

---

## Could Have

* Notes client.
* Campagnes promotionnelles.
* Avis clients.
* Score client.
* Gestion d’attente simple.
* Carte des salons.

---

## Won’t Have dans le MVP

* Paiement Mobile Money automatisé.
* Borne intelligente.
* IA.
* Gestion de stock.
* Multi-salons avancé.
* Marketplace produits.

---

# 23. Définition du MVP Final

Le MVP de CoifLink doit permettre à un salon de fonctionner quotidiennement avec la plateforme.

Un salon doit pouvoir :

* Se connecter.
* Configurer ses informations.
* Ajouter ses prestations.
* Recevoir des réservations.
* Gérer son planning.
* Suivre ses clients.
* Enregistrer ses paiements.
* Voir son chiffre d’affaires.
* Recevoir et envoyer les notifications essentielles.

Un client doit pouvoir :

* Créer un compte.
* Trouver un salon.
* Réserver un rendez-vous.
* Modifier ou annuler.
* Recevoir des rappels.
* Voir son historique.

---

# 24. Vision Long Terme

À long terme, CoifLink doit devenir un système complet de gestion et de croissance pour les salons de coiffure.

La plateforme ne doit pas seulement gérer les rendez-vous. Elle doit aider les salons à :

* Augmenter leur chiffre d’affaires.
* Réduire les pertes.
* Fidéliser les clients.
* Mieux organiser les équipes.
* Digitaliser les paiements.
* Vendre des produits.
* Automatiser l’accueil.
* Prendre de meilleures décisions grâce aux données.

L’objectif final est de faire de CoifLink la plateforme de référence pour la gestion digitale des salons de coiffure en Afrique de l’Ouest, avec une approche simple, locale, mobile-first et adaptée aux réalités du terrain.

---
