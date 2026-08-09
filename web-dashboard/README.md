# web-dashboard/ — Interface web gérant / admin CoifLink (Next.js)

Interface web **gérant** et **admin** de CoifLink, conformément à
**[ADR-0002](../docs/adr/0002-web-gerant-admin-nextjs.md)** (Next.js · React · TypeScript). Ce dossier
est un **squelette d'initialisation** (#2) : page d'accueil neutre, aucune fonctionnalité métier
(salons, planning, caisse, supervision → issues M2→).

> **Arborescence retenue (#2)** : **une seule application Next.js** avec zones protégées par rôle
> (`/gerant`, `/admin`) plutôt que deux applications séparées — plus simple à outiller pour le MVP et
> cohérent avec le RBAC backend unique (PRD §11.2). Décision tracée dans
> [ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md) (cf. ADR-0002 *Suivi*).

## Architecture (hexagonale — [ADR-0008](../docs/adr/0008-architecture-hexagonale.md))

```
src/
  domain/         # entités, règles & config métier (TS pur — ex. site.ts)
  application/    # cas d'usage + ports
  adapters/
    ui/           # composants React (consommés par app/)
    api/          # clients HTTP vers le backend (driven)
app/              # routage Next.js = adapter entrant + composition root du framework
```

Le routage `app/` reste l'entrée Next.js ; le domaine et les cas d'usage vivent sous
`src/` et ne dépendent ni de React ni du réseau.

## Dashboard gérant : shell, navigation, garde d'authentification (#14)

Le shell de l'espace **gérant** (`/gerant`) fournit le layout (en-tête, navigation, zone de
contenu), la navigation vers les futures sections (PRD §7.2) et une **garde d'authentification**
(deny-by-default). Aucune fonctionnalité métier n'est encore livrée : le dashboard est **vide mais
protégé** ; les sections Planning, Clients, Encaissements, Employés sont affichées
« à venir » (M2–M5). Les sections **Paramètres** (#15) et **Prestations** (#17) sont **disponibles**
(voir ci-dessous).

### Routes

| Route | Accès | Rôle |
| --- | --- | --- |
| `/` | publique | accueil neutre ; **aiguillage par rôle** si session valide (`MANAGER` → `/gerant`, `HAIRDRESSER` → `/coiffeur/planning`, #27) |
| `/login` | publique | point d'entrée de session (formulaire minimal) |
| `/gerant` | **protégée** | `MANAGER` actif — tableau de bord : **RDV du jour** par statut (#39), **chiffre d'affaires** jour/semaine/mois (#40), **prestations les plus demandées** (#41) puis **clients actifs** (nouveaux/récurrents/inactifs, #42) |
| `/gerant/parametres` | **protégée** | `MANAGER` — création/consultation du salon (#15) |
| `/gerant/prestations` | **protégée** | `MANAGER` — catalogue et gestion des prestations (#17) |
| `/gerant/planning` | **protégée** | `MANAGER` — planning du salon, jour/semaine/mois (#26) |
| `/gerant/clients` | **protégée** | `MANAGER` — fichier client du salon, création de fiche (#28) |
| `/gerant/clients/[customerId]` | **protégée** | `MANAGER` — fiche client + note privée éditable (#32) + historique des visites terminées (#29) + prestations préférées (#31) |
| `/coiffeur/planning` | **protégée** | `HAIRDRESSER` actif — **son** planning assigné, lecture seule (#27) |
| `POST /api/auth/login` | interne (BFF) | proxifie `POST /auth/login`, pose les cookies httpOnly |
| `POST /api/auth/logout` | interne (BFF) | efface les cookies de session |
| `POST /api/salons` | interne (BFF) | proxifie `POST /salons` (jeton lu du cookie httpOnly) |
| `GET /api/salons` | interne (BFF) | proxifie `GET /salons` (salons du gérant) |
| `PUT /api/salons/[id]/opening-hours` | interne (BFF) | proxifie `PUT /salons/{id}/opening-hours` (horaires, #16) |
| `GET /api/salons/[id]/services` | interne (BFF) | proxifie `GET /salons/{id}/services` (catalogue, #17) |
| `POST /api/salons/[id]/services` | interne (BFF) | proxifie `POST /salons/{id}/services` (création, #17) |
| `PUT /api/salons/[id]/services/[serviceId]` | interne (BFF) | proxifie `PUT /salons/{id}/services/{id}` (modification journalisée, #17) |
| `DELETE /api/salons/[id]/services/[serviceId]` | interne (BFF) | proxifie `DELETE …` (désactivation soft-delete, #17) |
| `GET /api/salons/[id]/customers` | interne (BFF) | proxifie `GET /salons/{id}/customers` (fiches du salon, #28) |
| `POST /api/salons/[id]/customers` | interne (BFF) | proxifie `POST /salons/{id}/customers` (création de fiche, #28) |
| `GET /api/salons/[id]/customers/[customerId]/appointments` | interne (BFF) | proxifie `GET /salons/{id}/customers/{id}/appointments` (historique des visites, #29) |
| `GET /api/salons/[id]/customers/[customerId]/stats` | interne (BFF) | proxifie `GET /salons/{id}/customers/{id}/stats` (prestations préférées, #31) |
| `PUT /api/salons/[id]/customers/[customerId]` | interne (BFF) | proxifie `PUT /salons/{id}/customers/{id}/notes` (édition de la note privée, #32) |
| `POST /api/salons/[id]/payments` | interne (BFF) | proxifie `POST /salons/{id}/payments` (enregistrement d'un paiement validé, #33) |
| `GET /api/salons/[id]/payments` | interne (BFF) | proxifie `GET /salons/{id}/payments` (historique filtrable des transactions, #35) |

`/api/auth/*` sont des **routes de l'application web** (Backend-For-Frontend), pas des endpoints
publics de la plateforme : elles ne figurent donc pas dans l'OpenAPI backend.

### Garde d'authentification (Option A — cookie httpOnly + BFF)

1. **Connexion** : `LoginForm` poste vers `POST /api/auth/login`, qui appelle `POST /auth/login`
   (#10) et pose les jetons dans des cookies **`httpOnly` / `Secure` (prod) / `SameSite=Lax`** —
   jamais accessibles au JS du navigateur (atténue le vol par XSS).
2. **Garde « présence » (edge)** : `proxy.ts` (convention Next.js 16, ex-`middleware`) intercepte
   `/gerant*` et redirige vers `/login` si le cookie de session est **absent** (aucun appel réseau
   au niveau edge).
3. **Vérification réelle (serveur)** : le layout `app/(gerant)/layout.tsx` (Server Component)
   appelle **`GET /auth/me`** (#12, **source de vérité**) via le cas d'usage
   `require-manager-session`. Décision : session valide de rôle `MANAGER` actif → rendu du shell ;
   `401`/`403` ou rôle non gérant → `redirect(/login)` ; `503`/panne → état d'erreur maîtrisé. Le
   contenu privé n'est **jamais** envoyé à un visiteur non autorisé (pas de « flash »).
4. **Déconnexion** : `LogoutButton` poste vers `POST /api/auth/logout` (efface les cookies) puis
   redirige vers `/login`.

La présence d'un jeton ne suffit pas : c'est la réponse `200` de `/auth/me` (rôle relu en base côté
backend) qui autorise l'affichage. Le front traite le JWT en **opaque** (il ne le décode pas). Un
`401` est traité comme « session expirée → redirection » ; le rafraîchissement transparent via
`POST /auth/refresh` est un **suivi** (hors #14).

### Tableau de bord — RDV du jour, chiffre d'affaires, prestations demandées & clients actifs (#39/#40/#41/#42)

La page **`/gerant`** (Server Component) charge **côté serveur** (jeton du cookie httpOnly, jamais
exposé au navigateur, invariant #14) le salon du gérant puis, pour ce salon :

- les **tuiles RDV du jour** par statut — Total · Confirmés · Annulés · Terminés · Absents (US-6.1,
  #39, via `GET /salons/{id}/appointments/daily-summary`) ;
- **sous** elles, les **tuiles chiffre d'affaires** — **Jour · Semaine · Mois** (US-6.2, #40, via
  `GET /salons/{id}/revenue/summary`), chacune affichant le total formaté en **FCFA** et, en légende,
  la plage de dates de la période (semaine **lundi → dimanche**, mois civil) ;
- **sous** elles, le panneau **« Prestations les plus demandées »** (US-6.3, #41, via
  `GET /salons/{id}/service-demand`) : un classement des prestations du salon avec une **bascule Volume /
  Revenu** (deux ordres, mêmes entrées), chaque ligne portant « rang · nom · **×N fois** · montant
  **FCFA** » (top affiché, reste résumé) ;
- **sous** lui, le panneau **« Clients actifs »** (US-6.4, #42, via `GET /salons/{id}/active-clients`) :
  la segmentation des clients du salon sur le **mois civil courant** (défaut backend) en **trois
  compteurs** — **Nouveaux** (première visite sur la période) · **Récurrents** (déjà venus, revenus sur
  la période) · **Inactifs** (sans visite sur la période) — plus un total « actifs » (nouveaux +
  récurrents) ;
- **sous** lui, le panneau **« Performance des coiffeurs »** (US-6.5, #43, via
  `GET /salons/{id}/hairdresser-performance`) : **une ligne par coiffeur** assigné à ≥ 1 RDV du salon sur
  le **mois civil courant** (défaut backend), portant **Coiffeur** (nom d'affichage) · **Prestations**
  réalisées (« ×N ») · **CA généré** (**FCFA**) · **Taux d'annulation** (pourcentage + « annulés / total »).
  Prestations & taux dérivent du **planning**, le CA de la **caisse** (net attribué par RDV).

Le backend reste **l'autorité des chiffres ET de l'ordre** (décompte `GROUP BY status`, CA `SUM` net des
corrections #34, classement `GROUP BY service_id`, segmentation `GROUP BY client_id`, performance
`GROUP BY hairdresser_id` — tous calculés en base ; « annulés exclus » §8.1 par construction) : les
composants ne font que **présenter** compteurs et montants (portés en **chaîne décimale**, `NUMERIC(12,2)`,
jamais un flottant JS) et **basculer** entre deux listes déjà triées (jamais de re-tri côté front). Réponses
**sans PII client** (§11.3) — la performance des coiffeurs émet le **seul** nom d'affichage de l'employé
(`users.full_name`, convention #34), jamais son contact ni aucun `client_id`. Un salon **sans activité** →
tuiles à `0` / classements **vides** (« Aucune prestation réalisée sur la période ») / compteurs à `0`
(« Aucun client réalisé sur la période ») / performance **vide** (« Aucun coiffeur assigné sur la période »)
— état vide légitime, ≠ erreur. Une erreur backend sur les RDV/CA (ou l'absence de salon) affiche le
panneau/l'invite correspondant ; une panne du **seul** panneau prestations, clients actifs **ou**
performance des coiffeurs **dégrade localement** (message neutre) sans casser la page. Aucun Route Handler
BFF ajouté : fetch serveur direct (patron du planning), via `http-stats-gateway` (étendu des méthodes
`serviceDemand`, `activeClients` et `hairdresserPerformance`).

### Tableau de bord — écran d'activité du salon (§7.2, #148 — [ADR-0039](../docs/adr/0039-dashboard-manager-activite-salon.md))

Au-dessus de l'analytique détaillée #39–#43, la même page **`/gerant`** rend un **écran d'activité**
consolidé « temps réel » sur données réelles (aucun mock) :

- un **sélecteur de période** (`period-filter.tsx`) — **Aujourd'hui · Semaine · Mois · Personnalisée** —
  qui pilote les `searchParams` de `/gerant` (`period`/`date_from`/`date_to`, `src/domain/dashboard/
  period.ts`) : chaque changement redemande un **rendu serveur** (jamais un filtrage en mémoire) ;
- **quatre cartes KPI** (`dashboard-kpi-cards.tsx`, via `GET dashboard/kpis`) — clients en attente,
  prestations en cours, chiffre d'affaires, nombre de clientes — chacune avec un **badge d'évolution**
  (↑/↓/→, couleur sémantique) vs la période précédente, sauf « prestations en cours » (instantané, sans
  badge) ;
- deux **graphiques SVG inline** rendus **côté serveur** (`revenue-chart.tsx`/`attendance-chart.tsx`,
  `dashboard-bar-chart.tsx` en commun) — évolution du CA et fréquentation — **sans nouvelle dépendance**
  (aucune librairie de charting, cf. ADR-0039), avec `aria-label` + table de secours accessible ; état
  vide si la série est tout-à-zéro ;
- la **liste des prestations en cours** (`in-progress-list.tsx`, via `GET dashboard/in-progress`) —
  cliente · prestation(s) · professionnelle · heure de début/fin · statut, noms d'affichage uniquement ;
- la **timeline des dernières activités** (`activity-timeline.tsx`, via `GET dashboard/activity`) —
  paiements et notifications salon (nouvelle réservation/annulation/modification), triés du plus récent
  au plus ancien, icône par genre ; « arrivée / début / fin de prestation » ne sont **pas** représentés
  (aucune source, voir backend README) ;
- le panneau **alertes importantes** (`alerts-panel.tsx`, via `GET dashboard/alerts`) — anomalie de
  paiement, retard, attente prolongée — badge de sévérité + compteur, message actionnable.

**Auto-refresh** (`auto-refresh.tsx`) : un intervalle (`setInterval`, ≥ 30 s) déclenche
`router.refresh()`, qui **re-exécute le Server Component** — le jeton du cookie httpOnly reste lu
**côté serveur**, jamais exposé au navigateur (invariant #14). Le rafraîchissement **se met en pause**
quand l'onglet est masqué (`document.visibilityState`, Page Visibility API) : aucun appel superflu.

**États.** `app/(gerant)/gerant/loading.tsx` + `dashboard-skeleton.tsx` couvrent le chargement initial et
les changements de période ; chaque panneau a un état vide explicite (« Aucun client en attente »,
« Aucune prestation en cours actuellement », « Aucune activité récente », « Aucune alerte ») ; une panne
d'**un seul** panneau **dégrade localement** (`null`, message neutre, patron #41) sans casser le reste de
l'écran. `http-stats-gateway.ts` est étendu de six méthodes (`dashboardKpis`, `revenueSeries`,
`attendanceSeries`, `inProgress`, `activity`, `alerts`) — même union discriminée `{ok:true,…}|{ok:false,
reason}`, jeton **serveur** jamais exposé, `cache: "no-store"`, mapping `200/401/403/422/503`.

### Paramètres — création & consultation du salon (#15)

La section **Paramètres** (`/gerant/parametres`, Server Component) charge les salons du gérant **côté
serveur** (jeton lu du cookie httpOnly, jamais exposé au navigateur) :

- **aucun salon** → formulaire de création (`SalonForm`) qui poste vers `POST /api/salons` ;
- **un salon** → fiche « Informations générales / Localisation ».

Tant que `isBookable(salon) === false` (§8.3 : `ACTIVE` **et** horaires présents — parité stricte avec
`domain/salon.py`), un **bandeau** invite à configurer les horaires d'ouverture. Les médias
(logo/photos) transitent par des **URLs signées** côté backend ; le téléversement direct
navigateur→bucket exige que le bucket autorise l'origine du dashboard (**CORS**) — configuration
d'infrastructure, hors code. **Aucune UI de logo/photos n'est encore câblée ici** (le formulaire salon
ne les expose pas) ; l'illustration des **prestations** (section Prestations, ci-dessous) implémente ce
flux de téléversement direct pour la première fois dans ce dashboard et peut servir de référence.

### Paramètres — horaires d'ouverture (#16)

Sous la fiche du salon, l'**éditeur d'horaires** (`OpeningHoursForm`, client) présente les 7 jours
(bascule fermé/ouvert, un ou plusieurs intervalles = **pauses**) et une section **jours exceptionnels**
(date + fermé/horaires ponctuels). La saisie est **validée côté client** (`validateOpeningHours`,
`src/domain/salon/opening-hours.ts` — **parité stricte** avec `domain/opening_hours.py`) avant d'être
postée en `PUT /api/salons/[id]/opening-hours` (le **backend reste l'autorité**). En cas de succès la
page se rafraîchit : dès que `isBookable(salon)` devient vrai, le **bandeau §8.3 disparaît**. Le fuseau
(`Africa/Abidjan`) n'est pas éditable dans l'UI au MVP.

### Prestations — catalogue du salon (#17)

La section **Prestations** (`/gerant/prestations`, Server Component) est **disponible** depuis #17. Elle
charge **côté serveur** (jeton du cookie httpOnly, jamais exposé) le salon du gérant puis ses
prestations : sans salon, elle invite à en créer un d'abord (Paramètres) ; sinon elle affiche un
**formulaire d'ajout** (`ServiceForm`) et le **catalogue** (`ServiceList`) — prestations actives **et**
désactivées (badge « Désactivée »), avec **édition en ligne** et bouton **Désactiver**.

La saisie (nom, prix, durée, catégorie, description) est **validée côté client** (`validateService`,
`src/domain/service/service.ts` — **parité stricte** avec `domain/service.py` : prix `>= 0` borné et au
plus 2 décimales, durée entière `> 0` ≤ 24 h, nom non vide) avant d'être postée aux Route Handlers BFF
`POST/PUT /api/salons/[id]/services[/serviceId]` et `DELETE …` (désactivation). Le **backend reste
l'autorité** ; la modification et la désactivation y sont **journalisées §11.4**. Le catalogue **client
public** (#18/#19) et la **réservation** (#21+) restent hors périmètre.

**Illustration de la prestation** (`ServiceImageUpload`, dans `ServiceForm`) : **premier téléversement
direct navigateur → stockage objet** implémenté dans ce dashboard (ADR-0005) — le binaire ne transite
**jamais** par l'API/BFF. Choisir un fichier (PNG/JPEG/WEBP, liste blanche `isAllowedServiceImageType`,
miroir `domain.salon.ALLOWED_IMAGE_TYPES`) déclenche : (1) `POST /api/salons/[id]/services/media/
upload-url` (BFF, jeton lu du cookie httpOnly côté serveur) → URL signée `PUT` ; (2) `PUT` **direct** du
fichier vers le stockage objet avec cette URL ; (3) aperçu local immédiat (`URL.createObjectURL`). La
clé obtenue n'est **attachée** qu'à la soumission du formulaire — `PUT /api/salons/[id]/services/
[serviceId]/image` (BFF) — **après** la création/modification générale : la prestation peut ne pas
encore exister au moment du choix de l'image. Le catalogue (`ServiceList`) affiche une **miniature**
quand l'illustration est disponible. **Prérequis d'infrastructure** : le bucket doit autoriser
l'origine du dashboard (**CORS**) pour que l'étape (2) réussisse — configuration hors code, à vérifier
en environnement de déploiement (même prérequis que le logo/photos du salon, ci-dessous — cette
implémentation peut leur servir de référence).

### Clients — fiches du salon (#28)

La section **Clients** (`/gerant/clients`, Server Component) est **disponible** depuis #28. Elle charge
**côté serveur** (jeton du cookie httpOnly, jamais exposé, invariant #14) le salon du gérant puis ses
fiches : sans salon, elle invite à en créer un d'abord (Paramètres) ; sinon elle affiche le **fichier
client** (`CustomerList` — recherche locale sur nom/téléphone/notes) et un **drawer de création**
(`CustomerForm`).

La saisie (nom, téléphone, genre, notes internes) est **validée côté client** (`validateCustomer`,
`src/domain/customer/customer.ts` — **parité** avec `domain/customer.py` : nom requis ≤ 255, téléphone
optionnel, genre ∈ `FEMALE|MALE|OTHER` ou non renseigné, notes ≤ 2000) avant d'être postée au Route
Handler BFF `POST /api/salons/[id]/customers` ; après succès, `router.refresh()`. Le **backend reste
l'autorité** : il normalise le téléphone en E.164, refuse un doublon de numéro **dans le salon**
(`409` → message neutre « Une fiche existe déjà pour ce numéro dans ce salon. ») et **journalise** la
création (§11.4/§11.3). Les **notes internes** sont annoncées comme « visible uniquement par le salon »
et ne sortent jamais de cette vue gérant (PRD §11.3). La note privée éditable (#32) et les statistiques
(#31) restent hors périmètre.

### Clients — historique des visites (#29)

Chaque ligne du fichier client ouvre une **page de détail** `/gerant/clients/[customerId]` (Server
Component) via un lien « Voir l'historique ». Elle charge **côté serveur** (jeton du cookie httpOnly,
invariant #14) le salon du gérant, la fiche (`get`) et son **historique de visites** (`history`) en
parallèle, puis rend un en-tête de fiche, un **résumé** (visites terminées, dernière visite, total
dépensé) et un **tableau des visites** (date, créneau, prestations nommées + prix figé, montant), le
plus récent d'abord (`CustomerVisitHistory`). Le domaine `src/domain/customer/visit.ts` porte les
types et les **helpers de formatage purs** (`formatAmountXof` → FCFA, `formatVisitDate`/`formatVisitTime`
au fuseau d'Abidjan) : le **backend reste l'autorité des montants** (`price_at_booking` figé, devise
`XOF`), le front **formate** seulement. Une fiche walk-in ou sans RDV terminé affiche un **état vide
explicite** (« Aucune visite terminée pour ce client ») — pas une erreur. `client_id`/`user_id` ne sont
**jamais** exposés (anti-oracle ADR-0026). Le Route Handler BFF
`GET /api/salons/[id]/customers/[customerId]/appointments` proxifie la lecture avec des messages
neutres.

### Clients — historique des paiements (fiche client)

La page de détail `/gerant/clients/[customerId]` charge en parallèle (dans le même `Promise.all` que
`get`/`history`/`stats`) l'**historique des paiements** du client (`payments` →
`GET /salons/{id}/customers/{id}/payments`) et rend, dans un onglet **« Paiements »** (`Tabs`), un
tableau **date · montant · statut**, du plus récent au plus ancien, **tous statuts confondus**
(`CustomerPaymentHistory`). Le domaine `src/domain/customer/payment.ts` porte les types et réutilise
les formateurs déjà éprouvés de `domain/payments/transaction.ts` (US-5.2 #35) —
`formatTransactionDateTime`/`paymentStatusLabel` — plutôt que de les dupliquer ; le badge de statut
reprend les mêmes tons que l'historique des transactions salon (`transaction-history.tsx`). Le
**backend reste l'autorité des montants** (`NUMERIC(12,2)` figé, devise `XOF`), le front **formate**
seulement. Une fiche walk-in ou sans paiement affiche un **état vide explicite** (« Aucun paiement
enregistré pour ce client ») — pas une erreur. `client_id`/`user_id`/`recorded_by`/`reference` ne sont
**jamais** exposés (anti-oracle ADR-0026). Fetch **serveur direct** (patron `history`/`stats`, aucun
Route Handler BFF) ; un échec **non-`not-found`** (`403`/réseau) **dégrade seulement ce panneau** (état
neutre local) sans casser la fiche ni l'historique des visites.

### Clients — prestations préférées (#31)

La page de détail `/gerant/clients/[customerId]` charge en parallèle (dans le même `Promise.all` que
`get`/`history`) les **prestations préférées** du client (`stats` → `GET /salons/{id}/customers/{id}/stats`,
#31) et rend, **sous** l'historique, un panneau **« Prestations préférées »** : un classement des
prestations les plus fréquentes (rang, nom, « ×N fois », montant cumulé), du plus fréquent au moins
fréquent (`CustomerServiceStatsPanel`). Le domaine `src/domain/customer/stats.ts` porte les types et
réutilise `formatAmountXof` : le **backend reste l'autorité des chiffres** (comptes, montants figés,
**ordre du classement**), le front **formate** seulement et ne re-trie jamais. Une fiche walk-in ou sans
RDV terminé affiche un **état vide explicite** (« Aucune prestation réalisée pour ce client ») — pas une
erreur. `client_id`/`user_id` ne sont **jamais** exposés (anti-oracle ADR-0026). Le Route Handler BFF
`GET /api/salons/[id]/customers/[customerId]/stats` proxifie la lecture avec des messages neutres ; un
échec **non-`not-found`** (`403`/réseau) **dégrade seulement ce panneau** (état neutre local) sans casser
la fiche ni l'historique.

### Clients — note privée éditable (#32)

La page de détail `/gerant/clients/[customerId]` rend, **sous** l'en-tête de fiche, un panneau
**« Note privée »** éditable (`CustomerNoteForm`, client component) : préférences, allergies, habitudes.
Une `<textarea>` pré-remplie avec la note courante ; « Enregistrer » remplace la note, « Effacer » la
vide (note `null`) — « éditer » couvre « retirer ». Au succès, `router.refresh()` recharge la fiche
côté serveur. La mention « Visible uniquement par le salon — jamais partagé avec le client » réaffirme
le critère d'acceptation (« non visible du client »). La validation `validateNote`
(`src/domain/customer/customer.ts`, parité `normalize_notes` backend) borne la saisie (≤ 2000) ; le
**backend reste l'autorité**. Le Route Handler BFF `PUT /api/salons/[id]/customers/[customerId]` lit le
jeton du cookie httpOnly **côté serveur** (invariant #14), proxifie `PUT …/notes` via
`CustomerGateway.updateNote` et renvoie des messages **neutres** (`422` « Note invalide. », `403`
« Action non autorisée sur ce salon. », `404` « Fiche client introuvable. ») — ni jeton ni contenu de
note journalisés (PRD §11.3).

### Zone coiffeur — Mon planning (#27)

La zone **coiffeur** (`/coiffeur`) est une zone protégée **dédiée au rôle `HAIRDRESSER`**, distincte de
la zone gérant. Sa garde miroir de `/gerant` : présence de cookie au niveau edge (`proxy.ts`, matcher
`/coiffeur*`), puis vérification **réelle** côté serveur dans `app/(coiffeur)/layout.tsx` via
`GET /auth/me` (source de vérité) et le cas d'usage `require-hairdresser-session`
(`canAccessCoiffeur` = `HAIRDRESSER` **et** `ACTIVE`). Décision : `allow` → shell coiffeur
(navigation réduite « Mon planning ») ; `401`/`403` ou rôle non coiffeur → `redirect(/login)` ;
`503`/panne → état d'erreur maîtrisé. Aucun « flash » de contenu privé.

La page **`/coiffeur/planning`** (Server Component) charge **côté serveur** (jeton du cookie httpOnly,
jamais exposé au navigateur, invariant #14) les RDV **assignés au coiffeur** via
`appointmentGateway.listAssigned({ from, to, statuses })` → `GET /appointments/assigned` (#27) —
`hairdresser_id` **imposé serveur**, aucune notion de salon à choisir. Elle **réutilise le domaine de
planning #26** (`rangeForView`/`todayIso`) et le composant `PlanningBoard` en **variante lecture**
(`readOnly`, `basePath="/coiffeur/planning"`) : vues jour/semaine/mois, groupement par statut, **sans
aucune action de statut** (le coiffeur **consulte** ; la frontière écriture #25 n'est pas franchie —
voir la spec). L'aiguillage par rôle après connexion se fait **à la racine** (`/`), côté serveur.

### Encaissements — enregistrement d'un paiement (#33, US-5.1)

La section **Encaissements** (`/gerant/encaissements`, Server Component) est **disponible** depuis #33.
Elle charge **côté serveur** (jeton du cookie httpOnly, jamais exposé au navigateur, invariant #14) le
salon du gérant puis ses **prestations actives**, et rend le formulaire d'enregistrement d'un paiement
(`RecordPaymentForm`, client component) : sélection de la **prestation à encaisser**, montant
**pré-rempli** avec son prix (guidage de la cohérence — le **backend reste l'autorité** et rejette tout
écart, §5.3/§8.2), mode de paiement (`CASH` / `MOBILE_MONEY_MANUAL` / `CARD_MANUAL` / `OTHER`) et
référence optionnelle. Au succès, `router.refresh()` recharge la page.

Le Route Handler BFF `POST /api/salons/[id]/payments` lit le jeton du cookie httpOnly **côté serveur**,
valide la saisie (`validatePayment`, `src/domain/payments/payment.ts`, parité `domain/payment.py`) puis
proxifie `POST /salons/{id}/payments` via `PaymentGateway.record`. Les erreurs sont **neutres** et
distinguées à partir du message métier du backend : `422` « Le montant ne correspond pas à la
prestation. » (incohérence de montant), `422` « Prestation ou rendez-vous introuvable pour ce salon. »
(référence hors salon/inconnue, sans oracle §11.2), `422` « Paiement invalide. », `403` « Action non
autorisée sur ce salon. », `401` « Session requise. ». Ni jeton, ni montant, ni PII ne sont journalisés
(PRD §11.3). Le journal de caisse consultable + la correction (#34) restent à livrer côté web.

La même page rend désormais la vue **Historique des transactions** (#35, US-5.2) : sous le formulaire, une
**barre de filtres** (`transaction-filters.tsx`, client component — date, montant, mode de paiement,
client) et une **liste read-only** (`transaction-list.tsx` — date/heure `Africa/Abidjan`, client, montant
`formatXof`, mode `paymentMethodLabel`, statut). Les filtres sont **serveur** : soumettre met à jour les
`searchParams` de la page (nouveau rendu serveur, relecture de la source de vérité `payments`), **jamais**
un filtrage en mémoire. Le Route Handler BFF `GET /api/salons/[id]/payments` lit le cookie httpOnly **côté
serveur**, propage les query params de filtre au backend (`PaymentGateway.listTransactions`) et renvoie un
corps **neutre** en erreur (`422` filtre invalide, `403`, `401`, `503`). État vide explicite (« Aucune
transaction ne correspond à ces filtres. »). La liste est **cohérente avec le journal de caisse** (même
source `payments`). Ni jeton, ni montant, ni PII ne sont journalisés.

### Ajouter une section

1. Ajouter une entrée à `src/domain/navigation/sections.ts`
   (`{ key, label, href, status, category }`).
2. Créer la page correspondante sous `app/(gerant)/gerant/<section>/page.tsx` et passer son
   `status` de `"coming-soon"` à `"available"`.
3. Si la section ne rentre dans aucune catégorie existante, ajouter la catégorie dans
   `DASHBOARD_SECTION_CATEGORIES`.

### Variables d'environnement

- **`NEXT_PUBLIC_API_BASE_URL`** — URL de base du backend, **exposée au navigateur** (jamais un
  secret).
- **`API_BASE_URL`** *(optionnelle, serveur uniquement)* — URL utilisée par les appels serveur
  Next (Route Handlers, layout `/gerant`) ; repli sur `NEXT_PUBLIC_API_BASE_URL` si absente. À
  définir seulement si le backend est joignable par une URL interne distincte. **Non secrète.**

Voir `.env.example`. `JWT_SECRET` reste **côté backend** : le front ne le connaît pas et ne valide
aucune signature.

## Prérequis

- **Node ≥ 20** (LTS ; version de référence figée par #2 — cf. champ `engines` et
  [ADR-0007](../docs/adr/0007-arborescence-monorepo-versions.md)) et `npm`.

## Installation

```bash
cd web-dashboard
npm install
```

## Lancement (dev)

```bash
cp .env.example .env.local      # ignoré par git ; aucun secret committé
npm run dev                     # http://localhost:3000
```

## Build & test

| Action | Commande |
| --- | --- |
| **Build** | `npm run build` |
| **Test** (test gate web, cf. #6) | `npm test` (Vitest) |
| Lint | `npm run lint` |
| **Image Docker** (Next.js standalone ; build-seul en CI, non-root) | `docker build -t coiflink-web ./web-dashboard` |

## Configuration

Les variables sont lues depuis l'environnement (`.env.local`, ignoré par git). Voir `.env.example` ;
seules les variables préfixées `NEXT_PUBLIC_` sont exposées au navigateur (jamais un secret). Aucun
secret n'est committé (injection hors dépôt). Modèle d'environnements & politique de secrets :
**[docs/environnements-et-secrets.md](../docs/environnements-et-secrets.md)** (ADR-0011).
