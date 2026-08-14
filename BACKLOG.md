# Backlog — CoifLink (plateforme de gestion pour salons de coiffure)

> **Source :** dérivé de [`prd-coiflink.md`](./prd-coiflink.md) — §6 (Épics & User Stories), §18 (Roadmap Sprint 0→6), §22 (MoSCoW), §8 (Règles métier), §11 (Sécurité).
> **État du dépôt :** projet *greenfield* — aucun code applicatif, uniquement le PRD et l'outillage ADW.
> **Usage :** ce backlog est la source des **issues GitHub** consommées par le pipeline ADW
> (`scripts/run-issue.sh <N>` → `.claude/commands/issue.md`). Chaque item ci-dessous devient
> une issue numérotée `#N` ; ses *Critères d'acceptation* sont la **definition of done** et la
> ligne *Dépend de* est lue par l'orchestrateur pour bloquer un ordre invalide.

## Légende

- **Effort :** `S` (≤ 2 j) · `M` (3–5 j) · `L` (1–2+ semaines)
- **Priorité :** `Must` / `Should` / `Could` (MoSCoW, §22)
- **Étiquettes :** `feature`, `bug`, `tech-debt`, `docs`, `security`, `infra`, `ux`, `payments`, `notifications`

---

## Vue d'ensemble des jalons (milestones)

| Jalon | Sprint PRD | Objectif (1 ligne) | Épics couverts |
| ----- | ---------- | ------------------ | -------------- |
| **M0 — Socle & Préparation** | Sprint 0 | Figer stack, dépôt, schéma de données, CI et environnements avant toute fonctionnalité. | (transverse) |
| **M1 — Authentification & utilisateurs** | Sprint 1 | Comptes client/gérant/employé, connexion JWT, RBAC, squelette dashboard. | Épic 1 |
| **M2 — Salons & prestations** | Sprint 2 | Un gérant configure son salon ; un client le consulte et voit les prestations réservables. | Épic 2 |
| **M3 — Rendez-vous** | Sprint 3 | Boucle réservation → confirmation → planning, sans double-réservation. | Épic 3 |
| **M4 — Clients, encaissement & caisse** | Sprint 4 | Fiches clients, paiements liés aux prestations, journal de caisse horodaté. | Épics 4, 5 |
| **M5 — Dashboard & notifications** | Sprint 5 | KPI gérant/admin + notifications confirmation/rappel/annulation. | Épics 6, 7 |
| **M6 — Tests, corrections & production** | Sprint 6 | Durcissement, e2e, perf, déploiement et pilote 10 salons. | (transverse) |
| **M7 — Borne client (terminal libre-service)** | Post-MVP | Un client sans rendez-vous s'enregistre seul sur une borne tactile en salon et reçoit un ticket imprimé avec numéro de passage. | Épic 8 |

**Chemin critique :** M0 → M1 → M2 → M3 → M4/M5 → M6.
M3 ne peut démarrer tant que le modèle de données (#3) et l'auth/RBAC (M1) ne sont pas figés ;
l'encaissement (M4) et les KPI (M5) dépendent de la boucle de rendez-vous (M3).
M7 est promu depuis « Hors périmètre MVP » (PRD §17) : il démarre après M1 (RBAC), M2 (catalogue
public) et M4 (fiches clients), et réutilise la file d'attente livrée par la PR #152 (issue de M4/M5).

---

## M0 — Socle & Préparation (Sprint 0)

> **Objectif :** aucune fonctionnalité avant un socle décidé et reproductible. On fige ici la stack,
> le schéma de données (§9) et la chaîne d'intégration.

- **#1 — Choix de la stack technique & ADR** · `Must` · `M` · `docs` `infra`
  Trancher chaque brique recommandée au §10 : app mobile (**Flutter** vs React Native, Android prioritaire), interface web gérant/admin (**Next.js / React**), backend (**FastAPI** vs Django REST, API REST + JWT), données (**PostgreSQL + Redis**), stockage fichiers (S3-compatible), notifications (FCM + SMS). Documenter via des ADR.
  *Acceptation :* un ADR par décision majeure committé dans `docs/adr/` ; justification du compromis (coût, écosystème, cible Android entrée de gamme) ; aucune décision de stack ne reste ouverte pour M1.

- **#2 — Initialisation du dépôt & structure du projet** · `Must` · `S` · `infra`
  Créer l'arborescence (`app-mobile/`, `web-dashboard/`, `backend/`, `docs/`, `docs/adr/`, `specs/`), licence, `README` décrivant le projet et la commande de build/test de chaque paquet, `.gitignore`, conventions de commits.
  *Acceptation :* structure en place ; `README` documente comment builder et tester chaque paquet ; les chemins attendus par le pipeline ADW existent.
  *Dépend de :* #1.

- **#3 — Modèle de données & schéma initial PostgreSQL** · `Must` · `M` · `infra` `tech-debt`
  Implémenter le schéma des entités du §9 : `User`, `Salon`, `Service/Prestation`, `Appointment`, `CustomerProfile`, `Payment/Transaction`, `CashJournal`, `Notification`, avec migrations versionnées.
  *Acceptation :* migrations exécutables (up/down) ; contraintes clés (un RDV lié à un salon + ≥ 1 prestation §8.1, un paiement lié à une prestation/RDV §8.2) présentes ; schéma documenté.
  *Dépend de :* #1, #2.

- **#4 — Pipeline CI/CD (GitHub Actions)** · `Must` · `M` · `infra`
  Lint, tests unitaires, build des apps et du backend, scan de dépendances, à chaque PR ; build d'images Docker.
  *Acceptation :* CI verte obligatoire avant merge ; artefacts de build produits ; jobs séparés mobile/web/backend.
  *Dépend de :* #2.

- **#5 — Environnements & gestion des secrets** · `Should` · `M` · `infra` `security`
  Environnements dev/staging/prod, aucune clé en clair dans le dépôt, configuration par variables d'environnement, sauvegardes activées.
  *Acceptation :* secrets injectés hors dépôt ; `staging` reproductible ; politique de secrets documentée.
  *Dépend de :* #4.

- **#6 — Plan de tests & configuration du test gate ADW** · `Should` · `S` · `infra` `docs`
  Définir la stratégie de tests (unitaire/intégration/e2e) et câbler le test gate du pipeline (`MX_AGENT_TEST_CMD`, ex. `flutter test` côté mobile, `pytest` côté backend) dans `scripts/adw.env`.
  *Acceptation :* `MX_AGENT_TEST_CMD` documenté et fonctionnel ; un test trivial passe via le gate.
  *Dépend de :* #1, #4.

- **#7 — Maquettes UX/UI des écrans MVP** · `Should` · `M` · `ux` `docs`
  Maquettes des écrans du §7 (mobile client, web gérant, admin) couvrant les parcours du §5.
  *Acceptation :* maquettes des écrans Must validées ; référencées par les issues d'implémentation correspondantes.

---

## M1 — Authentification & utilisateurs (Sprint 1) — Épic 1

> **Critères de sortie (PRD) :** un utilisateur peut créer un compte ; un gérant peut se connecter ;
> les rôles sont séparés ; les accès non autorisés sont bloqués.

- **#8 — US-1.1 · Inscription client (nom, téléphone, mot de passe)** · `Must` · `M` · `feature` `security`
  Création de compte client par téléphone + mot de passe ; vérification OTP recommandée ; mot de passe chiffré (§11.1).
  *Acceptation :* un client crée un compte ; doublon de téléphone refusé ; mot de passe jamais stocké en clair ; OTP testable.
  *Dépend de :* #3.

- **#9 — Inscription gérant & création du compte propriétaire** · `Must` · `M` · `feature` `security`
  Onboarding gérant (compte propriétaire du salon), prérequis de US-2.1. Dérivé de §18 (Sprint 1) et §4.
  *Acceptation :* un gérant crée son compte ; rôle `Gérant` attribué ; prêt à créer un salon.
  *Dépend de :* #3.

- **#10 — US-1.2 · Connexion (téléphone/email + mot de passe, JWT)** · `Must` · `S` · `feature` `security`
  Connexion avec émission d'un JWT + refresh token sécurisé ; protection contre les tentatives répétées (§11.1).
  *Acceptation :* connexion valide émet un JWT ; identifiants invalides refusés ; rate-limit sur les échecs.
  *Dépend de :* #8.

- **#11 — US-1.3 · Réinitialisation du mot de passe (OTP)** · `Must` · `S` · `feature` `security`
  Réinitialisation par OTP SMS ou email.
  *Acceptation :* parcours de reset complet ; OTP à usage unique et expirant ; ancien mot de passe invalidé.
  *Dépend de :* #8.

- **#12 — Middleware d'autorisation & RBAC** · `Must` · `M` · `security`
  Modèle de rôles/permissions du §4 + règles d'isolation du §11.2 (un gérant ne voit que son salon, un coiffeur que son planning, un client que ses RDV). Dérivé de §18 (« Middleware permissions »).
  *Acceptation :* accès inter-salons bloqué ; tests d'autorisation négatifs par rôle ; routes protégées par défaut (deny-by-default).
  *Dépend de :* #10.

- **#13 — US-1.4 · Création/invitation de comptes employés** · `Should` · `M` · `feature`
  Le gérant crée ou invite des employés (coiffeurs) avec rôles.
  *Acceptation :* un gérant crée un compte coiffeur ; le coiffeur se connecte avec un périmètre restreint.
  *Dépend de :* #12.

- **#14 — Squelette du dashboard web gérant** · `Must` · `S` · `feature` `ux`
  Shell du dashboard (navigation, layout, garde d'authentification). Dérivé de §18 (« Base du dashboard ») et §7.2.
  *Acceptation :* le gérant authentifié atteint un dashboard vide protégé ; un non-authentifié est redirigé.
  *Dépend de :* #10, #12.

---

## M2 — Salons & prestations (Sprint 2) — Épic 2

> **Critères de sortie (PRD) :** un gérant configure son salon ; un client le consulte ;
> les prestations sont visibles et réservables.

- **#15 — US-2.1 · Création d'un salon** · `Must` · `M` · `feature`
  Nom, logo, description, téléphone, localisation, photos.
  *Acceptation :* un gérant crée un salon rattaché à son compte ; un salon sans horaire n'est pas encore réservable (§8.3).
  *Dépend de :* #9, #14.

- **#16 — US-2.2 · Configuration des horaires d'ouverture** · `Must` · `M` · `feature`
  Horaires par jour, jours fermés, pauses, jours exceptionnels.
  *Acceptation :* horaires enregistrés par salon ; un salon sans horaire ne peut pas recevoir de réservation (§8.3).
  *Dépend de :* #15.

- **#17 — US-2.3 · Ajout & gestion des prestations** · `Must` · `M` · `feature`
  Nom, durée, prix, description, catégorie ; ajout/modification/suppression.
  *Acceptation :* prestations CRUD par salon ; durée et prix obligatoires ; modification journalisée (§11.4).
  *Dépend de :* #15.

- **Prestations · Illustration téléversable** · `feature` · **Livré**
  Extension de #17 : image PNG/JPEG/WEBP par prestation, téléversée directement navigateur → stockage
  objet (URL signée, ADR-0005, miroir logo salon #15), attachement dédié découplé de la création/
  modification générale, affichée sur le catalogue gérant et destinée à la borne cliente. Demande ad
  hoc (aucune issue GitHub créée en amont).
  *Livré via :* [PR #151](https://github.com/flavien-hugs/coiflink/pull/151) (mergée sur `main`).
  *Dépend de :* #17.

- **#18 — Recherche & liste des salons (côté client)** · `Must` · `M` · `feature` `ux`
  Écran de recherche/liste des salons (§7.1, parcours §5.1). Seuls les salons actifs sont visibles (§8.3).
  *Acceptation :* un client liste/recherche les salons actifs ; un salon désactivé n'apparaît pas.
  *Dépend de :* #15.

- **#19 — US-2.4 · Consultation d'un salon (côté client)** · `Must` · `M` · `feature` `ux`
  Affichage horaires, prestations, prix, localisation et disponibilité.
  *Acceptation :* le détail d'un salon montre prestations + horaires + dispo ; point d'entrée de la réservation.
  *Dépend de :* #16, #17, #18.

- **#20 — US-2.5 · Modification des informations du salon** · `Should` · `S` · `feature`
  Mise à jour des informations depuis le dashboard.
  *Acceptation :* le gérant met à jour son salon ; changements reflétés côté client.
  *Dépend de :* #15.

---

## M3 — Rendez-vous (Sprint 3) — Épic 3

> **Critères de sortie (PRD) :** un client réserve ; le salon confirme ; le planning se met à jour ;
> les notifications de base sont prêtes.

- **#21 — US-3.7 · Moteur de disponibilité & anti double-réservation** · `Must` · `M` · `feature`
  Vérification automatique des créneaux ; un créneau ne peut être réservé deux fois pour le même coiffeur (§8.1).
  *Acceptation :* deux réservations concurrentes sur le même créneau/coiffeur → une seule acceptée ; tests de concurrence.
  *Dépend de :* #16, #17.

- **#22 — US-3.1 · Réservation d'un rendez-vous (client)** · `Must` · `M` · `feature`
  Choix salon, prestation, date, heure, commentaire optionnel ; un RDV est lié à un salon + ≥ 1 prestation (§8.1).
  *Acceptation :* un client réserve un créneau disponible ; statut initial `en attente` ; RDV lié salon+prestation.
  *Dépend de :* #19, #21.

- **#23 — US-3.2 · Modification d'un rendez-vous (client)** · `Must` · `S` · `feature`
  Modification selon les règles du salon ; un RDV terminé n'est plus modifiable sauf par le gérant (§8.1).
  *Acceptation :* modification d'un RDV non terminé ; RDV terminé verrouillé côté client.
  *Dépend de :* #22.

- **#24 — US-3.3 · Annulation d'un rendez-vous (client)** · `Must` · `S` · `feature`
  Annulation avec motif optionnel ; un RDV annulé n'est pas comptabilisé dans le CA (§8.1).
  *Acceptation :* annulation selon la règle du salon ; RDV annulé exclu du chiffre d'affaires.
  *Dépend de :* #22.

- **#25 — US-3.4 · Confirmer/refuser un RDV & cycle de statuts (gérant)** · `Must` · `M` · `feature`
  Statuts : en attente, confirmé, annulé, terminé, absent ; assignation optionnelle d'un coiffeur (§8.1).
  *Acceptation :* transitions de statut valides ; transitions interdites bloquées ; changement journalisé (§11.4).
  *Dépend de :* #22.

- **#26 — US-3.5 · Planning du salon (vue calendrier)** · `Must` · `M` · `feature` `ux`
  Vue jour/semaine/mois des RDV confirmés/en attente/annulés/terminés (§5.2).
  *Acceptation :* le planning affiche les RDV du jour par statut ; se met à jour après changement de statut.
  *Dépend de :* #25.

- **#27 — US-3.6 · Planning personnel du coiffeur** · `Should` · `M` · `feature`
  Le coiffeur consulte les RDV qui lui sont assignés (§11.2 : il ne voit que les siens).
  *Acceptation :* un coiffeur voit uniquement son planning ; aucun accès aux RDV non assignés.
  *Dépend de :* #13, #26.

- **Réservation · Choix optionnel d'une coiffeuse (client)** · `feature` · **Livré**
  Étend #22 : la fiche salon publique (#19) expose les coiffeuses `ACTIVE` du salon (projection
  minimale id/nom/spécialités, jamais de PII de gestion) et le tunnel de réservation mobile ajoute une
  étape dédiée pour en choisir une optionnellement — « Peu importe » laisse le salon assigner, la
  réservation au niveau salon sans coiffeuse reste inchangée. Demande ad hoc (aucune issue GitHub créée
  en amont).
  *Livré via :* [PR #153](https://github.com/flavien-hugs/coiflink/pull/153) (mergée sur `main`).
  *Dépend de :* #19, #22, #152.

---

## M4 — Clients, encaissement & caisse (Sprint 4) — Épics 4 & 5

> **Critères de sortie (PRD) :** les paiements sont enregistrés ; le journal de caisse est consultable ;
> les prestations réalisées sont liées au chiffre d'affaires.

- **#28 — US-4.1 · Création d'une fiche client (gérant)** · `Must` · `M` · `feature`
  Nom, téléphone, genre optionnel, notes internes.
  *Acceptation :* le gérant crée une fiche client rattachée à son salon ; isolation par salon (§11.2).
  *Dépend de :* #12.

- **#29 — US-4.2 · Historique des visites d'un client (gérant)** · `Must` · `M` · `feature`
  Liste des RDV passés, prestations, montants.
  *Acceptation :* l'historique liste les RDV terminés du client avec prestations et montants.
  *Dépend de :* #25, #28.

- **Fiche client · Historique des paiements (gérant)** · `feature` · **Livré**
  Extension de #29 : onglet « Paiements » sur la fiche client (date, montant, statut, tous statuts
  confondus) — lien fiche → compte encapsulé en SQL (anti-oracle ADR-0026), isolation par salon,
  dégradation locale sur panne. Demande ad hoc (aucune issue GitHub créée en amont).
  *Livré via :* [PR #150](https://github.com/flavien-hugs/coiflink/pull/150) (mergée sur `main`).
  *Dépend de :* #28, #29.

- **#30 — US-4.4 · Historique de prestations (côté client mobile)** · `Should` · `S` · `feature`
  Historique depuis l'application mobile ; un client ne voit que ses propres RDV (§11.2).
  *Acceptation :* le client voit son historique de RDV terminés et rien d'autre.
  *Dépend de :* #25.

- **#31 — US-4.3 · Prestations préférées d'un client (stats)** · `Should` · `S` · `feature`
  Statistiques par client.
  *Acceptation :* affichage des prestations les plus fréquentes du client.
  *Dépend de :* #29.

- **#32 — US-4.5 · Note client privée** · `Could` · `S` · `feature`
  Notes privées : préférences, allergies, habitudes.
  *Acceptation :* le gérant ajoute/édite une note privée non visible du client.
  *Dépend de :* #28.

- **#144 — US-4.6 · Modification des informations d'une fiche client (gérant)** · `Must` · `S` · `feature`
  Nom, téléphone, genre optionnel — les mêmes champs que la création (#28), modifiables après coup.
  *Acceptation :* le gérant modifie nom/téléphone/genre d'une fiche de son salon ; unicité `(salon_id, phone)`
  respectée ; isolation par salon (§11.2) ; modification journalisée (§11.4).
  *Dépend de :* #28.

- **#33 — US-5.1 · Enregistrement d'un paiement** · `Must` · `M` · `feature` `payments`
  Montant, mode de paiement, prestation liée, client lié ; un paiement est lié à une prestation/RDV avec un utilisateur responsable (§8.2) ; le montant correspond à la prestation (§5.3).
  *Acceptation :* paiement enregistré et lié au RDV/prestation ; montant cohérent ; opération journalisée (§11.4).
  *Dépend de :* #25.

- **#34 — US-5.3 · Journal de caisse horodaté** · `Must` · `M` · `feature` `payments` `security`
  Journal horodaté avec l'utilisateur ayant enregistré l'opération ; un paiement validé n'est jamais supprimé, toute correction crée une opération d'ajustement (§8.2).
  *Acceptation :* chaque paiement apparaît horodaté + auteur ; suppression interdite ; correction = ligne d'ajustement.
  *Dépend de :* #33.

- **#35 — US-5.2 · Historique des transactions (filtrable)** · `Must` · `S` · `feature` `payments`
  Liste filtrable par date, client, montant, mode de paiement.
  *Acceptation :* filtres fonctionnels ; cohérence avec le journal de caisse.
  *Dépend de :* #33.

- **#36 — US-5.4 · Détection des écarts de caisse** · `Should` · `M` · `feature` `payments`
  Comparaison entre prestations réalisées et paiements enregistrés (§8.2).
  *Acceptation :* un RDV terminé sans paiement est signalé comme écart.
  *Dépend de :* #34.

- **#37 — US-5.6 · Supervision agrégée des transactions (admin)** · `Should` · `M` · `feature` `payments`
  Statistiques agrégées par salon, sans détails sensibles inutiles (§11.2/§11.3).
  *Acceptation :* l'admin voit des agrégats par salon sans PII de paiement superflue.
  *Dépend de :* #34.

- **#38 — US-5.5 · Reçu numérique de paiement (client)** · `Could` · `S` · `feature` `payments`
  Reçu numérique ou notification.
  *Acceptation :* un reçu est généré/envoyé après paiement.
  *Dépend de :* #33.

---

## M5 — Dashboard & notifications (Sprint 5) — Épics 6 & 7

> **Critères de sortie (PRD) :** le gérant suit son activité ; le client reçoit ses notifications ;
> les KPI MVP sont visibles.

- **#39 — US-6.1 · RDV du jour (dashboard)** · `Must` · `S` · `feature`
  Total, confirmés, annulés, terminés, absents.
  *Acceptation :* le dashboard affiche le décompte du jour par statut.
  *Dépend de :* #14, #25.

- **#40 — US-6.2 · Chiffre d'affaires (jour/semaine/mois)** · `Must` · `M` · `feature`
  CA journalier, hebdomadaire, mensuel ; les RDV annulés ne comptent pas (§8.1).
  *Acceptation :* CA calculé à partir des paiements ; annulés exclus ; périodes correctes.
  *Dépend de :* #33.

- **#41 — US-6.3 · Prestations les plus demandées** · `Must` · `M` · `feature`
  Classement par volume et revenu généré.
  *Acceptation :* top prestations par volume et par revenu.
  *Dépend de :* #33.

- **#42 — US-6.4 · Clients actifs** · `Must` · `M` · `feature`
  Nouveaux, récurrents, inactifs.
  *Acceptation :* segmentation des clients sur une période donnée.
  *Dépend de :* #29.

- **#43 — US-6.5 · Performance des coiffeurs** · `Should` · `M` · `feature`
  Nombre de prestations réalisées, CA généré, taux d'annulation.
  *Acceptation :* indicateurs par coiffeur cohérents avec le planning et la caisse.
  *Dépend de :* #27, #33.

- **#44 — US-6.6 · KPI globaux plateforme (admin)** · `Must` · `M` · `feature`
  Salons inscrits, abonnements, rendez-vous, revenus plateforme.
  *Acceptation :* dashboard admin avec KPI globaux agrégés.
  *Dépend de :* #37.

- **#148 — Dashboard Manager · Activité du salon** · `Must` · `L` · `feature` · **Livré**
  Consolide/étend le dashboard gérant (#39/#40/#42) : KPI clients en attente/prestations en cours/CA/
  clientes (+ évolution), filtres de période, graphiques CA & fréquentation, liste des prestations en
  cours, timeline d'activité, alertes, actualisation automatique.
  *Acceptation :* 4 KPI affichés et filtrables par période, données réelles (aucun mock), mise à jour
  automatique, états loading/empty/error gérés, tests ajoutés.
  *Dépend de :* #39, #40, #42.
  *Livré via :* #149 (mergé sur `main`), [ADR-0039](./docs/adr/0039-dashboard-manager-activite-salon.md).

- **Dashboard Manager · Gestion des employés & file d'attente (gérant)** · `feature` · **Livré**
  Étend #148 : gestion complète des coiffeuses (création, modification de profil, activation/
  désactivation pilotant la disponibilité aux affectations, #13) et file d'attente du jour avec
  pointage réel de l'arrivée/du début (migration dédiée, statut dérivé En attente/En cours/Terminée/
  Payée) — réutilise l'assignation de coiffeuse et le cycle de statut (#25) ainsi que l'encaissement
  (#33) plutôt que de créer de nouveaux flux. Demande ad hoc (aucune issue GitHub créée en amont).
  *Livré via :* [PR #152](https://github.com/flavien-hugs/coiflink/pull/152) (mergée sur `main`).
  *Dépend de :* #13, #25, #33, #148.

- **#45 — US-7.1 · Notification de confirmation de RDV** · `Must` · `M` · `feature` `notifications`
  Push, SMS ou WhatsApp selon disponibilité ; envoyée après chaque réservation (§8.4).
  *Acceptation :* une confirmation part à la création du RDV ; notification critique tracée (§8.4/§11.4).
  *Dépend de :* #22.

- **#46 — US-7.2 · Rappel automatique avant RDV** · `Must` · `M` · `feature` `notifications`
  Rappel configurable 24h / 2h / 30 min via jobs asynchrones.
  *Acceptation :* rappel planifié et envoyé à l'échéance ; annulation du RDV annule le rappel.
  *Dépend de :* #22.

- **#47 — US-7.3 · Notification au salon à la réservation** · `Must` · `S` · `feature` `notifications`
  Notification dashboard + option email/SMS.
  *Acceptation :* le salon est notifié à chaque nouvelle réservation.
  *Dépend de :* #22.

- **#48 — US-7.4 · Notification d'annulation/modification** · `Must` · `S` · `feature` `notifications`
  Notification automatique après changement de statut ; annulation notifie client + salon (§8.4).
  *Acceptation :* un changement de statut déclenche la notification aux parties concernées.
  *Dépend de :* #23, #24, #25.

- **#49 — US-7.5 · Campagnes/messages aux clients** · `Could` · `M` · `feature` `notifications`
  Campagnes simples : rappel, promotion, fermeture exceptionnelle.
  *Acceptation :* le gérant envoie un message à un segment de clients.
  *Dépend de :* #28.

---

## M6 — Tests, corrections & mise en production (Sprint 6)

> **Critères de sortie (PRD) :** MVP stable ; 10 salons pilotes prêts ; données de test validées ;
> monitoring activé ; support opérationnel.

- **#50 — Tests e2e des parcours critiques** · `Must` · `L` · `tests`
  Parcours réservation (§5.1), gestion RDV gérant (§5.2) et encaissement (§5.3) de bout en bout.
  *Acceptation :* suite e2e verte sur les parcours Must ; intégrée à la CI (#4).
  *Dépend de :* M3, M4, M5.

- **#51 — Tests de sécurité (authz, JWT, données perso)** · `Must` · `M` · `security` `tests`
  Vérifier RBAC/isolation par salon (§11.2), JWT/refresh, protection brute-force, journalisation des accès sensibles (§11.3/§11.4).
  *Acceptation :* tests négatifs d'autorisation par rôle ; aucune fuite inter-salons ; accès sensibles journalisés.
  *Dépend de :* #12.

- **#52 — Tests de performance** · `Should` · `M` · `tests`
  Charge sur les endpoints critiques selon les cibles du §12.1.
  *Acceptation :* temps de réponse dans les budgets du §12 sous charge nominale.
  *Dépend de :* M3, M4.

- **#53 — Documentation utilisateur** · `Should` · `M` · `docs`
  Guides gérant et client.
  *Acceptation :* documentation des parcours Must publiée.

- **#54 — Déploiement production** · `Must` · `L` · `infra`
  Docker, hébergement cloud sécurisé, sauvegardes automatiques, monitoring.
  *Acceptation :* prod déployée et monitorée ; sauvegardes vérifiées ; rollback documenté.
  *Dépend de :* #5.

- **#55 — Préparation du pilote (10 salons) & formation** · `Should` · `M` · `docs`
  Données de test, onboarding et formation des salons pilotes, suivi post-lancement.
  *Acceptation :* 10 salons pilotes prêts ; support opérationnel en place.
  *Dépend de :* #54.

---

## M7 — Borne client (terminal libre-service) (Post-MVP) — Épic 8

> **Contexte :** promu depuis « Hors périmètre MVP » (PRD §17 « Borne Intelligente d'Accueil »).
> Le PRD (Risque 5) recommandait explicitement de « lancer d'abord sans borne » et de la piloter sur
> 2-3 salons avant généralisation — ce jalon reprend ce conseil en limitant volontairement le scope.
>
> **Scope de ce jalon (walk-in uniquement) :** un client **sans rendez-vous** s'identifie par
> téléphone (ou crée une fiche) sur une borne tactile physique installée en salon, choisit une
> prestation, reçoit un numéro de passage avec temps d'attente estimé, et un **ticket papier
> imprimé** (évolution assumée par rapport au « ticket numérique + SMS/WhatsApp » du PRD §17.3).
>
> **Explicitement hors scope de M7** (restent différés, non repris dans « Hors périmètre MVP » car
> réévaluables plus tard) : vérification/check-in d'un rendez-vous existant depuis la borne,
> identification par QR code ou code de réservation (PRD §17.3), affichage temps réel des coiffeurs
> disponibles avant affectation, paiement autonome sur la borne (« Version future » du PRD lui-même).
>
> **Critères de sortie :** un client sans rendez-vous s'enregistre seul sur une borne tactile en
> salon, sans intervention du personnel d'accueil, et reçoit un ticket imprimé.

- **#155 — US-8.1 · Rôle & authentification borne** · `Must` · `M` · `feature` `security`
  Nouveau rôle `TERMINAL` scopé à un salon, avec un identifiant device longue durée distinct des JWT
  personnels : le RBAC actuel sépare `CUSTOMER_MANAGE` (MANAGER uniquement) et `APPOINTMENT_BOOK`
  (CLIENT uniquement), aucun rôle existant ne convient à un terminal public partagé. Permissions
  minimales et dédiées ; ADR requise (même exigence que l'anti-oracle ADR-0026).
  *Acceptation :* un device provisionné pour le salon X s'authentifie avec un scope limité (lecture
  catalogue, recherche téléphone restreinte, création de ticket walk-in) ; il ne peut obtenir ni
  `CUSTOMER_MANAGE` ni `APPOINTMENT_BOOK` complets ; test RBAC négatif ajouté à la matrice existante.
  *Dépend de :* #12.

- **#156 — US-8.2 · Identification téléphone & création client walk-in** · `Must` · `M` · `feature`
  Nouveau `find_by_phone` (port + repository + endpoint) sur `CustomerProfile`, réservé au rôle
  `TERMINAL`, sans jamais interroger `users` par téléphone (préserve l'anti-oracle ADR-0026) ; ouverture
  ciblée de la création de fiche client à ce même rôle.
  *Acceptation :* la borne retrouve une fiche existante par téléphone (salon de la borne uniquement)
  et n'affiche que le prénom du client ; si absente, crée une fiche nom/prénom/téléphone sans mot de
  passe ; isolation par salon respectée (§11.2).
  *Dépend de :* #155, #28.

- **#157 — US-8.3 · Ticket de passage walk-in & estimation d'attente** · `Must` · `L` · `feature`
  Nouveau domaine `QueueTicket` (numéro séquentiel par salon/jour, statut, estimation d'attente),
  indépendant d'`Appointment` (pas de détournement de créneaux planifiés), avec un endpoint
  public/terminal « rejoindre la file » et une formule V1 d'ETA (position dans la file × durée moyenne
  des prestations des tickets en attente et en cours ÷ coiffeuses actives). Pontable vers un `Appointment` uniquement quand une
  coiffeuse démarre réellement la prestation, pour réutiliser la file d'attente livrée en PR #152.
  *Acceptation :* un ticket walk-in reçoit un numéro séquentiel, une heure d'émission et un temps
  d'attente estimé ; il apparaît dans la file gérant existante une fois pris en charge ; aucune
  régression sur la file des rendez-vous planifiés.
  *Dépend de :* #155, #156.

- **#158 — US-8.4 · Photo de prestation dans le catalogue public** · `Should` · `S` · `feature`
  Ajoute `image_url` (URL signée) à `PublicServiceResponse`/`PublicServiceView`, en réutilisant la
  résolution d'URL déjà utilisée côté gérant — la donnée (`image_object_key`) existe déjà en base.
  *Acceptation :* le catalogue public retourne une URL de photo quand une image est renseignée ;
  aucune régression sur les consommateurs existants de l'endpoint.
  *Dépend de :* aucune.

- **#159 — US-8.5 · Mode terminal de l'app mobile** · `Must` · `L` · `feature` `ux` — **livré**
  `app-mobile/` est désormais un paquet **terminal exclusif** (point d'entrée unique `main.dart`, plus
  d'app cliente dans ce dépôt) : huit écrans accueil/identification/création/choix-prestation/
  vérification/numéro/impression en gros boutons tactiles adaptés à un usage à distance de bras, avec
  un timer d'inactivité global ramenant automatiquement à l'accueil. Activation **une seule fois** par
  code à 6 chiffres remis au provisioning (`POST /auth/terminal/activate`, code à usage unique lié au
  device) puis authentification device **silencieuse** à chaque lancement (credential persisté chiffré
  sur l'appareil, aucune session personnelle) — voir [`app-mobile/README.md`](./app-mobile/README.md).
  *Acceptation :* US-001 à US-007 (UI) et US-008 couvertes ; aucune session personnelle active en fin
  de parcours ; retour automatique après 60 s d'inactivité, timer suspendu pendant l'impression du
  ticket.
  *Dépend de :* #155, #156, #157, #158.

- **#160 — US-8.6 · Impression du ticket sur imprimante thermique** · `Must` · `M` · `feature`
  Nouveau port `TicketPrinterGateway` côté mobile + adaptateur ESC/POS Bluetooth ou USB, gabarit
  visuel de ticket dérivé de celui de l'impression de reçu (PR #154) porté en widget Flutter, avec
  gestion explicite des erreurs imprimante (hors ligne, plus de papier).
  *Acceptation :* le ticket imprimé contient salon, numéro, date, heure et prestation (US-007) ; un
  échec d'impression est signalé clairement au client sans bloquer le retour à l'accueil.
  *Dépend de :* #157, #159.

- **#161 — US-8.7 · ADR, documentation & procédure de provisioning borne** · `Should` · `S` · `docs` `infra`
  ADR sur le modèle d'authentification borne et l'architecture `QueueTicket` ; procédure de
  provisioning d'un device (PIN gérant, sortie du mode terminal, mise à jour applicative) ; mise à jour
  du PRD/BACKLOG une fois le jalon livré.
  *Acceptation :* les ADR d'authentification borne et d'architecture `QueueTicket` sont committées
  dans `docs/adr/` et indexées ; procédure de provisioning documentée et vérifiée sur au moins un
  device physique.
  *Dépend de :* #155, #156, #157, #158, #159, #160.

---

## Hors périmètre MVP (§21 / §22 « Won't Have »)

Reportés en V2+ (suivis ailleurs, **pas** dans ce backlog MVP) : paiement Mobile Money automatisé,
IA de recommandation, gestion de stock, multi-salons avancé, marketplace produits, programme de
fidélité, QR code de présence.

> La **borne intelligente d'accueil (§17)** n'est plus listée ici : son sous-ensemble « walk-in sans
> rendez-vous » a été promu au jalon **M7** ci-dessus. Restent différés hors de M7 (réévaluables plus
> tard, pas nécessairement « Won't Have ») : check-in d'un rendez-vous existant depuis la borne,
> identification par QR code/code de réservation, affichage temps réel des coiffeurs disponibles, et
> le paiement autonome sur la borne (déjà noté « Version future » par le PRD §17.3 lui-même).
