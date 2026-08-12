"""Composition root de l'API backend CoifLink (architecture hexagonale, ADR-0008).

Ce module n'est pas une couche métier : il **assemble** l'application. Il lit la
configuration depuis l'environnement (jamais de secret en dur, cf. PRD §11,
ADR-0005/0006), instancie FastAPI et monte les adapters entrants (routers).

Répartition hexagonale :
- `domain/`       — entités et règles métier (zéro dépendance framework/I/O) ;
- `application/`  — cas d'usage + `ports` (interfaces) ;
- `adapters/`     — `inbound/` (HTTP FastAPI...) et `outbound/` (Postgres, Redis...).
"""

from __future__ import annotations

import os
import secrets

from fastapi import Depends, FastAPI

from coiflink_api.adapters.inbound.admin import router as admin_router
from coiflink_api.adapters.inbound.appointments import router as appointments_router
from coiflink_api.adapters.inbound.auth import router as auth_router
from coiflink_api.adapters.inbound.campaigns import router as campaigns_router
from coiflink_api.adapters.inbound.catalog import router as catalog_router
from coiflink_api.adapters.inbound.customers import router as customers_router
from coiflink_api.adapters.inbound.employees import router as employees_router
from coiflink_api.adapters.inbound.health import router as health_router
from coiflink_api.adapters.inbound.kiosk_customers import (
    router as kiosk_customers_router,
)
from coiflink_api.adapters.inbound.kiosk_devices import router as kiosk_devices_router
from coiflink_api.adapters.inbound.payments import router as payments_router
from coiflink_api.adapters.inbound.queue_tickets import (
    router as queue_tickets_router,
)
from coiflink_api.adapters.inbound.receipts import router as receipts_router
from coiflink_api.adapters.inbound.salons import router as salons_router
from coiflink_api.adapters.inbound.security import require_authenticated
from coiflink_api.adapters.inbound.services import router as services_router
from coiflink_api.adapters.inbound.stats import router as stats_router
from coiflink_api.adapters.outbound.notifications.otp_sender_stub import (
    StubOtpSender,
)
from coiflink_api.adapters.outbound.security.argon2_hasher import Argon2Hasher
from coiflink_api.adapters.outbound.security.jwt_token_service import JwtTokenService
from coiflink_api.adapters.outbound.security.login_rate_limiter_memory import (
    InMemoryLoginRateLimiter,
)
from coiflink_api.adapters.outbound.security.otp_in_memory import (
    InMemoryOtpRepository,
)
from coiflink_api.config import load_auth_config, load_media_config

# Configuration lue depuis l'environnement (jamais de secret en dur).
APP_NAME = os.environ.get("APP_NAME", "CoifLink API")
APP_ENV = os.environ.get("APP_ENV", "development")

# Autorisation **deny-by-default** (#12, ADR-0015) : `require_authenticated` est une
# dépendance **globale**, donc appliquée à toutes les routes de tous les routers.
# Une route n'est publique que si son chemin figure dans la liste d'exemption
# explicite `security.PUBLIC_ROUTE_PATHS` — une route ajoutée sans rien déclarer
# est **fermée**, jamais ouverte.
app = FastAPI(title=APP_NAME, dependencies=[Depends(require_authenticated)])

# Assemblage de l'authentification : la config et les adapters singletons sont
# déposés sur `app.state` et relus par l'adapter entrant `auth` lors de
# l'injection de dépendances. Aucune règle métier ici — uniquement du câblage.
_auth_config = load_auth_config()
app.state.auth_config = _auth_config

# Inscription/OTP (#8/#9) : envoi stub + dépôt OTP en mémoire.
app.state.otp_sender = StubOtpSender()
app.state.otp_repository = InMemoryOtpRepository()

# Réinitialisation du mot de passe par OTP (#11) : instances **dédiées** et
# physiquement distinctes de celles de l'inscription — un OTP d'inscription ne
# peut jamais servir à un reset (ou l'inverse). L'OTP de reset est **bloquant**
# et **toujours actif** (indépendant d'`OTP_ENABLED`). Le limiteur dédié protège
# la demande contre le flood d'OTP (« SMS/e-mail bombing »). Le dépôt en mémoire
# n'est ni partagé ni persistant (limite documentée ADR-0014 ; Redis différé M5).
app.state.password_reset_otp_repository = InMemoryOtpRepository()
app.state.password_reset_otp_sender = StubOtpSender()
app.state.password_reset_rate_limiter = InMemoryLoginRateLimiter(
    max_attempts=_auth_config.password_reset_max_attempts,
    window=_auth_config.password_reset_window,
    lockout=_auth_config.password_reset_lockout,
)

# Connexion/JWT (#10) :
# - le limiteur anti-bruteforce est un **singleton** (état en mémoire partagé) ;
# - le condensat *dummy* est **pré-calculé une fois** (atténuation d'oracle
#   temporel quand aucun compte ne correspond, cf. `AuthenticateUser`) ;
# - le `TokenService` n'est assemblé que si `JWT_SECRET` est présent. Absent, on
#   laisse `None` : les routes `/auth/login` et `/auth/refresh` répondent `503`
#   (fail-fast clair) sans casser `GET /health` ni l'inscription (ADR-0011/0013).
app.state.login_rate_limiter = InMemoryLoginRateLimiter(
    max_attempts=_auth_config.login_max_attempts,
    window=_auth_config.login_window,
    lockout=_auth_config.login_lockout,
)
app.state.login_dummy_hash = Argon2Hasher().hash(secrets.token_urlsafe(32))

# Recherche téléphone à la borne kiosque (#156, US-8.2) : limiteur anti-énumération
# **dédié** (singleton `app.state`), distinct des limiteurs de connexion (#10) et de
# login kiosque (#155) — verrouiller les recherches d'une borne ne verrouille ni son
# login ni les connexions humaines. Réutilise le même port/adaptateur (spec §D) avec
# des seuils propres au lookup (plus permissifs : erreur de saisie tactile fréquente).
app.state.kiosk_lookup_rate_limiter = InMemoryLoginRateLimiter(
    max_attempts=_auth_config.kiosk_lookup_max_attempts,
    window=_auth_config.kiosk_lookup_window,
    lockout=_auth_config.kiosk_lookup_lockout,
)
if _auth_config.jwt_secret:
    app.state.token_service = JwtTokenService(
        _auth_config.jwt_secret,
        algorithm=_auth_config.jwt_algorithm,
        access_ttl=_auth_config.access_ttl,
        refresh_ttl=_auth_config.refresh_ttl,
    )
else:
    app.state.token_service = None

# Stockage objet des médias de salon (#15, ADR-0005) : assemblé sur le patron du
# `token_service`. Si la configuration S3 est incomplète, `media_storage = None` :
# les routes médias répondent `503`, sans casser `GET /health`, l'authentification
# ni **`POST /salons`** (créer un salon sans logo doit rester possible — le critère
# d'acceptation de #15 ne dépend pas du stockage objet). La config média (dont le
# plafond `MEDIA_MAX_PHOTOS`) est aussi déposée pour les cas d'usage.
_media_config = load_media_config()
app.state.media_config = _media_config
if _media_config.is_configured:
    from coiflink_api.adapters.outbound.storage.s3_media_storage import S3MediaStorage

    app.state.media_storage = S3MediaStorage(_media_config)
else:
    app.state.media_storage = None

app.include_router(health_router)
app.include_router(auth_router)
# Gestion des employés (#13) : route protégée par RBAC (EMPLOYEE_MANAGE + portée
# salon) — le use case est assemblé par DI dans l'adapter (mêmes patrons que `auth`).
app.include_router(employees_router)
# Bornes kiosque (#155, US-8.1) : provisioning/liste/révocation sous
# /salons/{id}/kiosk-devices. Routes protégées par RBAC (KIOSK_PROVISION, détenue
# par le seul MANAGER + portée salon §11.2) ; provisioning/révocation journalisés
# (KIOSK_DEVICE_PROVISIONED/REVOKED, metadata vide) dans la même unité de travail.
# Le compte de service KIOSK (role fixé serveur) ne détient jamais CUSTOMER_MANAGE
# ni APPOINTMENT_BOOK (moindre privilège, ADR-0041). L'authentification du device
# (POST /auth/kiosk/login) est portée par le routeur `auth` (publique-listée) ; rien
# ici n'est ajouté à `security.PUBLIC_ROUTE_PATHS` (une borne n'est jamais
# provisionnable publiquement).
app.include_router(kiosk_devices_router)
# Gestion des salons (#15) : création rattachée au gérant + consultation + médias.
# Routes protégées par RBAC (SALON_CREATE/READ/UPDATE + portée salon).
app.include_router(salons_router)
# Gestion des prestations (#17) : CRUD par salon sous /salons/{salon_id}/services.
# Routes protégées par RBAC (SERVICE_MANAGE/READ + portée salon) ; mutations
# journalisées (§11.4) dans la même unité de travail que l'écriture métier.
app.include_router(services_router)
# Catalogue client (#18) : recherche/liste publique des salons ACTIVE (§8.3) sous
# /catalog/salons. Ressource distincte de /salons (gestion) ; lecture seule,
# projection de vitrine sans owner_id/PII. La route est publique-listée dans
# `security.PUBLIC_ROUTE_PATHS` (décision de sécurité revue, ADR-0015).
app.include_router(catalog_router)
# Disponibilité & réservation (#21, US-3.7) : GET /catalog/salons/{id}/availability
# (créneaux libres — public, patron catalogue) et POST /salons/{id}/appointments
# (réservation client APPOINTMENT_BOOK). L'anti double-réservation est garanti par
# la contrainte d'exclusion base ex_appointments_hairdresser_slot (schéma #3) ; la
# disponibilité est publique-listée dans `security.PUBLIC_ROUTE_PATHS` (ADR-0023).
app.include_router(appointments_router)
# Fiches clients (#28, US-4.1) : création + lectures sous /salons/{id}/customers.
# Première mise en service de la permission CUSTOMER_MANAGE (§4.1, détenue par le
# seul MANAGER) ; portée salon obligatoire (isolation §11.2). La création est
# journalisée (CUSTOMER_CREATED) dans la même unité de travail que l'écriture —
# collecte de PII au sens §11.3, entrée d'audit **neutre**. Rien n'est ajouté à
# `security.PUBLIC_ROUTE_PATHS` : une fiche client n'est jamais publique.
app.include_router(customers_router)
# Borne kiosque — identité walk-in (#156, US-8.2) : recherche par téléphone et
# création de fiche walk-in sous /salons/{id}/kiosk/customers[...]. Réservées au
# rôle KIOSK via les permissions **dédiées** déjà livrées par #155
# (CUSTOMER_LOOKUP_KIOSK / CUSTOMER_CREATE_WALKIN) + portée salon (isolation §11.2) ;
# la matrice ROLE_PERMISSIONS n'est PAS modifiée (CUSTOMER_MANAGE reste MANAGER-seul).
# Recherche exclusivement sur customer_profiles (jamais la table users — anti-oracle
# ADR-0026), réponse minimale (prénom seul), téléphone en corps (jamais en URL),
# lookups rate-limités (device + IP) et non audités ; la création journalise
# CUSTOMER_CREATED (metadata vide) dans la même unité de travail. Rien n'est ajouté à
# `security.PUBLIC_ROUTE_PATHS` : « réservé au rôle KIOSK » ≠ public.
app.include_router(kiosk_customers_router)
# File d'attente walk-in — tickets de passage (#157, US-8.3, ADR-0042) : trois
# routes sous /salons/{id}/queue/tickets[...]. « Rejoindre la file » est réservée
# au rôle KIOSK via la permission **dédiée** QUEUE_TICKET_CREATE (déjà livrée par
# #155) ; start/complete réutilisent APPOINTMENT_UPDATE_STATUS (mêmes acteurs que
# le démarrage d'un RDV : coiffeuse + gérant) — la matrice ROLE_PERMISSIONS n'est
# PAS modifiée. Toutes salon-scopées (isolation §11.2). Le ticket est INDÉPENDANT
# d'Appointment : numéro séquentiel par salon+jour (verrou consultatif, patron
# ADR-0040), estimation d'attente V1 figée à l'émission, aucune ligne appointments
# écrite. start/complete journalisent QUEUE_TICKET_STARTED/COMPLETED (metadata
# vide) ; l'émission n'est pas auditée. Rien n'est ajouté à
# `security.PUBLIC_ROUTE_PATHS` : « réservé au rôle KIOSK » ≠ public.
app.include_router(queue_tickets_router)
# Campagnes/messages aux clients (#49, US-7.5) : création + liste sous
# /salons/{id}/campaigns. Réutilise la permission CUSTOMER_MANAGE (§4.1, MANAGER
# seul) + portée salon (isolation §11.2). Le gérant compose un message (texte
# libre) et cible un segment de son fichier clients (#28) : la campagne est
# **émise/tracée** (CAMPAIGN_CREATED, effectif non-PII, status=PENDING) dans la
# même unité de travail que l'audit. La **remise proactive** (fan-out SMS) reste
# différée M5 (Épic 7, ADR-0006) — rien n'est envoyé, sent_at reste NULL. Rien
# n'est ajouté à `security.PUBLIC_ROUTE_PATHS` : une campagne n'est jamais publique.
app.include_router(campaigns_router)
# Encaissement & journal de caisse (#33/#34, US-5.1/5.3) : enregistrement d'un
# paiement (PAYMENT_RECORD), journal horodaté en lecture (CASH_JOURNAL_READ) et
# correction par ligne d'ajustement (PAYMENT_RECORD) sous /salons/{id}/…. Journal
# **append-only** (§8.2) : aucune route ne supprime un paiement validé ni une
# ligne de journal ; une correction crée une opération ADJUSTMENT. Écritures
# journalisées (PAYMENT_RECORDED/CASH_ADJUSTED) dans la même unité de travail,
# entrées **neutres** (§11.4). Rien n'est ajouté à `security.PUBLIC_ROUTE_PATHS` :
# le journal de caisse (données financières) n'est jamais public.
app.include_router(payments_router)
# Reçu numérique de paiement (#38, US-5.5) : GET /me/receipts et
# GET /me/receipts/{payment_id} — lectures d'**appartenance** réservées au client
# (PAYMENT_READ_OWN), sans portée salon (`client_id = principal.id` imposé serveur).
# Le reçu est une **projection en lecture** dérivée du paiement (#33) : aucune
# écriture, aucune migration, aucune PII tierce. La **remise** proactive (push/SMS)
# reste différée en M5 (Épic 7, ADR-0006) — #38 génère un reçu **récupérable**, il
# n'envoie rien. Rien n'est ajouté à `security.PUBLIC_ROUTE_PATHS` : un reçu
# financier n'est jamais public.
app.include_router(receipts_router)
# Supervision plateforme admin (#37, US-5.6 ; #44, US-6.6) : router plateforme (non
# salon-scopé) réservé à l'ADMIN (STATS_READ_PLATFORM). Deux endpoints :
#   - GET /admin/transactions/summary — agrégats de transactions **par salon**
#     (compteurs + montant NET via le journal de caisse #34) **sans PII de paiement** ;
#   - GET /admin/kpis — KPI **globaux** consolidés de la plateforme (US-6.6, #44) :
#     salons inscrits/actifs, clients inscrits, RDV (total + mois courant), revenus
#     plateforme (net cumulé + mois courant via cash_journal). Instantané unique de
#     scalaires globaux, **aucune** identité d'entité (§11.3, plus fort que #37) ;
#     KPI « abonnements » volontairement absent (aucun modèle SaaS, ADR-0032).
# STATS_READ_PLATFORM a donc **deux** consommateurs (#37 supervision, #44 KPI globaux).
# La garde de permission suffit (l'admin voit tous les salons), pas de
# require_salon_scope. Lecture pure : aucune écriture, aucun audit. Rien n'est ajouté à
# `security.PUBLIC_ROUTE_PATHS` : la supervision plateforme n'est jamais publique.
app.include_router(admin_router)
# Statistiques salon (#40, US-6.2 ; #41, US-6.3 ; #42, US-6.4 ; #43, US-6.5) : router
# stats dédié réservé au MANAGER (STATS_READ_SALON) + portée salon (isolation §11.2).
# Cinq endpoints :
#   - GET /salons/{id}/revenue/summary — chiffre d'affaires du salon sur trois périodes
#     (jour/semaine/mois) ; le CA dérive du **montant net** du journal de caisse (#34 :
#     somme signée PAYMENT/ADJUSTMENT), « annulés exclus » (§8.1) par construction ;
#   - GET /salons/{id}/service-demand — prestations les plus demandées, classées par
#     volume (RDV COMPLETED) et par revenu (somme des price_at_booking figés) ;
#   - GET /salons/{id}/hairdresser-performance — performance par coiffeur : prestations
#     réalisées + taux d'annulation (planning), CA généré (caisse nette **attribuée**
#     via payments → appointments.hairdresser_id). Seul endpoint stats **nominatif**
#     (nom d'affichage employé, jamais son contact) ;
#   - GET /salons/{id}/dashboard/{kpis,revenue-series,attendance-series,in-progress,
#     activity,alerts} — Dashboard Manager · activité du salon (§7.2, #148) : 4 KPI +
#     évolution, deux graphiques (séries CA/fréquentation), prestations en cours (noms
#     d'affichage), timeline des faits horodatés et alertes dérivées. Filtre de période
#     unifié résolu serveur ; « en cours » dérivé (CONFIRMED ∩ slot @> now), « en
#     attente » = PENDING — aucun statut ni migration nouveaux.
# STATS_READ_SALON a donc six consommateurs (#39 RDV du jour, #40 CA, #41 demande,
# #42 clients actifs, #43 performance des coiffeurs, #148 dashboard d'activité). Lecture
# pure : aucune écriture, aucun audit, aucune PII counts-only / nom d'affichage maîtrisé
# sur les vues opérationnelles (§11.3). Rien n'est ajouté à `security.PUBLIC_ROUTE_PATHS`
# : une donnée d'exploitation salon n'est jamais publique.
app.include_router(stats_router)
