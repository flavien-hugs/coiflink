# ADR-0024 : Réservation côté client — tunnel mobile & session cliente au-dessus des endpoints #21

- **Statut** : Accepté
- **Date** : 2026-07-21
- **Décideurs** : équipe CoifLink
- **Issue** : #22 (US-3.1 — Réservation d'un rendez-vous, client)
- **Référence PRD** : §6 Épic 3 (US-3.1), §7.1 (parcours client), §8.1 (RDV lié salon + ≥ 1 prestation,
  anti double-réservation), §8.3 (salon non réservable), §11.1 (jeton), §11.2 (anti-élévation),
  §11.3 (confidentialité des créneaux pris)
- **S'appuie sur** : [ADR-0001](./0001-app-mobile-flutter.md) (Flutter),
  [ADR-0008](./0008-architecture-hexagonale.md) (hexagonal),
  [ADR-0013](./0013-connexion-jwt-refresh-anti-bruteforce.md) (connexion JWT + refresh),
  [ADR-0020](./0020-catalogue-salons-cote-client.md) / [ADR-0021](./0021-consultation-salon-cote-client.md)
  (catalogue & fiche client, première couche réseau du paquet),
  [ADR-0023](./0023-moteur-disponibilite-anti-double-reservation.md) (disponibilité & réservation,
  endpoints réutilisés tels quels)

## Contexte et problème

Le backend expose **déjà** (#21) les deux surfaces dont US-3.1 a besoin : `GET .../availability`
(publique, créneaux **libres**) et `POST /salons/{id}/appointments` (client `APPOINTMENT_BOOK`, crée le
RDV `PENDING`). Les critères d'acceptation de #22 sont donc satisfaits **au niveau du contrat HTTP**.
Le gap : côté mobile, le parcours n'existait pas — la fiche salon (#19) n'avait qu'un bouton
« Réserver » **inerte** (SnackBar « bientôt disponible »), et le paquet Flutter n'avait **ni domaine
rendez-vous, ni passerelle de réservation, ni tunnel, ni couche d'auth cliente**. #22 construit ce
parcours en **consommant** les endpoints #21, sans modifier le backend.

## Décision

1. **Backend inchangé.** Aucune route, table, migration ni contrainte nouvelle. Le tunnel client se
   **superpose** aux cas d'usage #21 (`CheckAvailability`, `BookAppointment` côté serveur) via HTTP.
   L'anti double-réservation reste porté par la contrainte d'exclusion PostgreSQL (§8.1, ADR-0023) : le
   mobile ne fait qu'une **aide UX** (n'affiche que des créneaux libres) et traite le `409` comme le
   **verdict final** (créneau perdu) — jamais un contournement.

2. **Auth cliente minimale livrée dans #22 (stratégie A).** Le `POST` exige un JWT `APPOINTMENT_BOOK` ;
   or le paquet mobile n'avait aucune couche d'auth et #22 ne dépend (backlog) que de #19 et #21.
   Plutôt que bloquer, #22 livre une **connexion minimale** réutilisant `POST /auth/login`
   (téléphone/e-mail + mot de passe → JWT) : port `AuthGateway`, cas d'usage `SignIn`, écran
   `LoginScreen`. Le tunnel exige une session au moment de confirmer ; si absente, il **redirige vers
   Connexion** puis revient. (L'inscription §7.1 réutilisera `POST /auth/register` ultérieurement —
   minimisée à la connexion pour ce MVP.)

3. **Stockage du jeton : abstraction `TokenStore`, implémentation en mémoire au MVP.** Le jeton vit
   derrière un port `TokenStore` (`read`/`write`/`clear`) exposé via `AuthSession`. Le MVP fournit
   `InMemoryTokenStore` (session perdue au redémarrage) pour rester **testable sans plugin natif**. La
   cible de production est un **magasin sécurisé de plateforme** (Keychain/Keystore, p. ex.
   `flutter_secure_storage`) : la bascule est un **simple remplacement d'implémentation** du port,
   aucun autre code n'en dépend. Le jeton n'est **jamais journalisé** (§11.1) et transite en en-tête
   `Authorization: Bearer`. Un `401` invalide la session locale et redirige vers Connexion.

4. **MVP mono-prestation.** Une réservation cliente porte **une seule** prestation. La route de
   disponibilité prend un **unique** `service_id` ; autoriser plusieurs prestations sans adapter la
   disponibilité proposerait des créneaux trop courts (durée = somme). Le multi-prestations viendra avec
   un ajustement d'API ultérieur. L'UI impose ≥ 1 prestation (bouton « Continuer »/« Confirmer »
   désactivé sinon) — cohérent avec le critère d'acceptation « RDV lié à ≥ 1 prestation ».

5. **Réservation au niveau salon (pas de coiffeur).** Le tunnel MVP réserve avec `hairdresser_id` **nul**
   (aucun endpoint public ne liste les coiffeurs d'un salon ; l'assignation relève du gérant, US-3.4).
   Conséquence assumée (§8.1, ADR-0023) : **sans** coiffeur, la contrainte d'exclusion base ne
   s'applique pas — la garantie de capacité viendra avec l'assignation gérant.

6. **Statut `PENDING → « En attente »`.** Le domaine mobile mappe la chaîne backend vers un `enum`
   `AppointmentStatus`, avec libellé d'affichage francophone. Une valeur de statut **inconnue** est
   tolérée (défaut prudent) pour ne pas casser sur une évolution serveur. La confirmation #22 est **à
   l'écran** à partir de la **réponse du `POST`** (aucune lecture supplémentaire) ; l'étape
   « Notification » du §7.1 relève de l'Épic 7.

7. **Gestion honnête des états & codes.** Chargement des créneaux, *aucun créneau* (jour fermé/complet),
   *erreur réseau* (réessayer) ; à la confirmation : `201` → confirmation « En attente » ; `409` créneau
   pris → message + **retour à l'étape créneaux rafraîchie** ; `409` salon non réservable (§8.3) →
   message ; `401` → redirection Connexion ; autre non-2xx/réseau → message **neutre**. Les exceptions
   mobiles (`AppointmentGatewayException`, `SlotTakenException`, `NotBookableException`,
   `UnauthorizedException`, `AuthException`) portent des messages **génériques** — **jamais** d'URL,
   jeton, corps de requête, détail de transport ni PII (garde-fou identique au gateway catalogue #18).

8. **Anti-élévation (§11.2).** Le corps de réservation n'envoie **jamais** `client_id`, `salon_id` ni
   `status` — imposés serveur (`extra="ignore"` côté #21). Le mobile construit `{date, start_time,
   service_ids, client_note?}` uniquement. La confidentialité (§11.3) est préservée : la disponibilité
   ne renvoie que des créneaux libres et le mobile n'affiche jamais l'identité de qui occupe un créneau.

9. **Fuseau Africa/Abidjan = UTC+0.** Le mobile construit dates/heures en **composantes locales** (jamais
   de conversion UTC) pour rester cohérent avec le repère du schéma `tsrange` (#16/#21) et éviter des
   décalages de créneaux. Horizon de sélection de date borné à **30 jours** (choix MVP raisonnable, non
   spécifié par le PRD).

## Conséquences

- **Positives** : les critères d'acceptation de #22 (réservation d'un créneau libre, statut initial
  « En attente », RDV lié salon + ≥ 1 prestation) sont couverts **sans** toucher au backend ; le
  découpage hexagonal du paquet est respecté (domaine pur, ports, adapters HTTP, UI) ; l'anti-doublon
  base reste l'unique juge ; le point d'entrée « Réserver » (#19) ouvre enfin le tunnel réel, tout en
  restant **inerte** quand aucun lanceur n'est câblé (préserve les écrans/tests sans réservation).
- **Négatives / suivis** : le jeton **ne survit pas** au redémarrage (magasin sécurisé de plateforme à
  brancher — remplacement de `TokenStore`) ; **mono-prestation** et **sans coiffeur** au MVP
  (multi-prestations = ajustement d'API ; coiffeur = assignation gérant US-3.4) ; **modification/
  annulation** (US-3.2/3.3) et l'écran **« Mes rendez-vous »** complet restent hors périmètre ; les
  **notifications** de confirmation/rappel (§8.4, Épic 7) ne sont pas envoyées ; l'hypothèse **UTC+0**
  doit rester explicite si un fuseau à décalage était introduit.
