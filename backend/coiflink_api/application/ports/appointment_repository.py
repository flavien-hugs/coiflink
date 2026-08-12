"""Port de persistance des **rendez-vous** (`Protocol`, US-3.7 #21, US-3.2 #23).

Les cas d'usage `application/appointments.py` déclarent ici leurs besoins de
lecture (créneaux occupés, RDV du client) et d'écriture (création & modification
transactionnelles) ; l'implémentation SQLAlchemy vit dans
`adapters/outbound/persistence/appointment_repository.py`. Conformément à
l'hexagonal (ADR-0008), l'application ne connaît ni la `Session` ni le modèle ORM.

**Garantie anti double-réservation** (§8.1) : `create` **et** `update` **doivent**
lever `SlotAlreadyBooked` quand la contrainte d'exclusion base
`ex_appointments_hairdresser_slot` rejette l'écriture (course concurrente perdue),
en distinguant cette violation de toute autre erreur d'intégrité. La contrainte
d'exclusion PostgreSQL s'applique aussi bien aux `INSERT` qu'aux `UPDATE`.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Mapping
from typing import Protocol

from coiflink_api.domain.appointment import (
    Appointment,
    AppointmentToCreate,
    AppointmentUpdate,
)
from coiflink_api.domain.availability import SlotRange
from coiflink_api.domain.dashboard import InProgressService
from coiflink_api.domain.hairdresser_performance import HairdresserActivityCounts
from coiflink_api.domain.queue import QueueAppointmentRow
from coiflink_api.domain.service_demand import ServiceDemand


class AppointmentRepository(Protocol):
    """Contrat de persistance des rendez-vous d'un salon."""

    def booked_slots(
        self,
        salon_id: uuid.UUID,
        hairdresser_id: uuid.UUID | None,
        date: datetime.date,
        *,
        exclude_appointment_id: uuid.UUID | None = None,
    ) -> tuple[SlotRange, ...]:
        """Créneaux **actifs** (`status IN (PENDING, CONFIRMED)`) du coiffeur pour `date`.

        Alimente le moteur de disponibilité. Le filtre porte sur `salon_id`,
        `hairdresser_id` (ou `IS NULL` si `None`) et la date : un RDV
        `CANCELLED`/`NO_SHOW`/`COMPLETED` n'occupe plus le créneau (hors clause
        `WHERE` de l'exclusion, cohérent avec le schéma).

        `exclude_appointment_id` (optionnel, additif — rétro-compatible #21) exclut
        un RDV du calcul : indispensable à la **modification** (#23), sans quoi le
        propre créneau actuel du RDV apparaîtrait « occupé » et un déplacement
        légitime (ou un simple changement de note) serait faussement rejeté.
        """
        ...

    def create(self, appointment: AppointmentToCreate) -> Appointment:
        """Insère le RDV **et** ses lignes `appointment_services` dans **une** transaction.

        Lève `domain.errors.SlotAlreadyBooked` si la contrainte d'exclusion base est
        violée (course concurrente) — la seconde insertion perd et **rien** n'est
        persisté (rollback de l'unité de travail). Toute autre erreur d'intégrité est
        relevée telle quelle (jamais masquée).
        """
        ...

    def get_owned(
        self, appointment_id: uuid.UUID, client_id: uuid.UUID
    ) -> Appointment | None:
        """Charge le RDV **et** ses `BookedService` si — et seulement si — il
        appartient à `client_id` (isolation §11.2 imposée en SQL).

        Retourne `None` quand le RDV n'existe pas **ou** n'appartient pas au client :
        les deux cas sont **indiscernables** (le cas d'usage lève alors un `404`
        générique, aucun oracle d'existence). Jamais de RDV d'autrui.
        """
        ...

    def update(
        self, appointment_id: uuid.UUID, changes: AppointmentUpdate
    ) -> Appointment:
        """Re-planifie le RDV et **remplace** ses lignes `appointment_services` dans
        **une** transaction (sémantique *replace*, #23).

        L'écriture est conditionnée au statut **actif** (`PENDING`/`CONFIRMED`) :
        si aucune ligne active ne correspond (statut passé terminal entre la lecture
        et l'écriture — garde TOCTOU), lève `domain.errors.AppointmentNotModifiable`.
        Lève `domain.errors.SlotAlreadyBooked` sur violation de l'exclusion base
        (course/collision avec un autre RDV actif du même coiffeur). Toute autre
        erreur d'intégrité est relevée telle quelle.
        """
        ...

    def cancel(
        self, appointment_id: uuid.UUID, *, reason: str | None
    ) -> Appointment:
        """Annule le RDV (transition vers `CANCELLED`) et pose son motif (#24).

        Écriture **conditionnée au statut actif** (`PENDING`/`CONFIRMED`) via un
        UPDATE conditionnel : si aucune ligne active ne correspond (RDV inexistant
        ou statut passé terminal entre la lecture et l'écriture — garde TOCTOU), lève
        `domain.errors.AppointmentNotCancellable`. Pose `status = 'CANCELLED'` et
        `cancellation_reason = reason` (`reason` déjà normalisé, `None` = pas de
        motif) ; `updated_at` se rafraîchit automatiquement. Les jonctions
        `appointment_services` (prestations + prix figé) sont **conservées** (utiles
        à l'historique/CA futur). L'annulation **libère** le créneau (le RDV quitte
        l'ensemble actif de l'exclusion base et de `booked_slots`) : elle ne peut pas
        violer la contrainte d'exclusion. Retourne l'entité relue.
        """
        ...

    def get_in_salon(
        self, appointment_id: uuid.UUID, salon_id: uuid.UUID
    ) -> Appointment | None:
        """Charge le RDV **et** ses `BookedService` ssi il appartient à `salon_id`
        (isolation §11.2 imposée en SQL, US-3.4 #25 — analogue salon-scopé de
        `get_owned`).

        Le filtre porte sur `id` **et** `salon_id` : un RDV d'un autre salon est
        indiscernable d'un identifiant inexistant. Retourne `None` dans les deux
        cas — le cas d'usage lève alors un `404` générique **après** la portée
        (aucun oracle d'existence). Jamais un RDV hors salon.
        """
        ...

    def set_status(
        self,
        appointment_id: uuid.UUID,
        salon_id: uuid.UUID,
        *,
        expected_current: str,
        target: str,
        reason: str | None = None,
    ) -> Appointment:
        """Fait passer le RDV vers `target` (transition de statut gérant, US-3.4 #25).

        Écriture **conditionnée** au salon **et** au statut courant attendu
        (`WHERE id = :id AND salon_id = :salon_id AND status = :expected_current`) :
        si aucune ligne ne correspond (RDV disparu, hors salon, ou statut changé
        entre la lecture et l'écriture — garde TOCTOU), lève
        `domain.errors.InvalidAppointmentTransition`. Pose `status = :target` et,
        **uniquement** si `target = 'CANCELLED'`, `cancellation_reason = :reason`
        (déjà normalisé, `None` = pas de motif). `updated_at` (`onupdate`) se
        rafraîchit automatiquement. Une transition de statut **ne peut pas** violer
        l'exclusion base : elle retire le RDV de l'ensemble actif (→ terminal) ou le
        maintient sur le **même** créneau/coiffeur (`PENDING → CONFIRMED`). Retourne
        l'entité relue (avec ses `BookedService`, conservés).
        """
        ...

    def assign_hairdresser(
        self,
        appointment_id: uuid.UUID,
        salon_id: uuid.UUID,
        *,
        hairdresser_id: uuid.UUID | None,
    ) -> Appointment:
        """(Dés)assigne un coiffeur à un RDV **actif** du salon (US-3.4 #25).

        Écriture **conditionnée** au salon **et** au statut **actif**
        (`WHERE id = :id AND salon_id = :salon_id AND status IN (PENDING, CONFIRMED)`) :
        si aucune ligne active ne correspond (RDV disparu, hors salon, ou terminal —
        créneau libéré, assignation non pertinente), lève
        `domain.errors.InvalidAppointmentTransition`. Pose `hairdresser_id`
        (`None` = désassignation). Lève `domain.errors.SlotAlreadyBooked` si la
        contrainte d'exclusion base rejette l'assignation (le coiffeur est déjà pris
        sur ce créneau) — une désassignation ne peut jamais la violer. Retourne
        l'entité relue.
        """
        ...

    def list_for_client(
        self,
        client_id: uuid.UUID,
        statuses: tuple[str, ...] | None = None,
        *,
        newest_first: bool = False,
    ) -> tuple[Appointment, ...]:
        """Liste les RDV **du client** (`client_id`), avec leurs `BookedService`.

        Ne renvoie **que** les données du client demandeur (§11.2/§11.3) — jamais
        l'identité d'un tiers. `statuses` restreint la lecture (p. ex. aux états
        actifs `PENDING`/`CONFIRMED`, ou aux `COMPLETED` de l'historique #30) ;
        `None` ne filtre pas sur le statut.

        `newest_first` (additif, rétro-compatible) contrôle **l'ordre** : par défaut
        (`False`) tri **chronologique croissant** (date puis heure — les RDV « à
        venir » de `GET /appointments`) ; `True` trie **décroissant** (du plus récent
        au plus ancien — l'historique se lit naturellement ainsi, US-4.4 #30).
        """
        ...

    def list_for_salon(
        self,
        salon_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[Appointment, ...]:
        """Liste les RDV **du salon** sur une plage de dates (planning gérant, #26).

        Miroir salon-scopé de `list_for_client` : renvoie les RDV dont
        `appointment_date` est dans `[date_from, date_to]` (**inclusif**), avec leurs
        `BookedService`, triés `(appointment_date, start_time)`. `statuses=None` ne
        filtre pas sur le statut (**tous** statuts, y compris terminaux) ; une liste
        restreint. **Ne renvoie jamais** un RDV d'un autre salon : l'isolation §11.2
        est imposée **en SQL** (`WHERE salon_id = :salon_id`), en défense en profondeur
        de la garde HTTP `require_salon_scope`. L'index `ix_appointments_salon_id
        (salon_id, appointment_date)` couvre ce filtre.
        """
        ...

    def count_by_status_for_day(
        self, salon_id: uuid.UUID, day: datetime.date
    ) -> Mapping[str, int]:
        """Décompte des RDV **du salon** pour `day`, **groupés par statut** (US-6.1 #39).

        Renvoie `{status: count}` pour les RDV dont `appointment_date == day`, agrégés
        **en base** (`GROUP BY status`) : la lecture **ne rapatrie aucune ligne de RDV**
        ni aucune PII (pas de `client_id`, `client_note`, `hairdresser_id`) — seulement
        des compteurs (§11.3). Un statut **sans RDV** du jour est **absent** de la map
        (le domaine le complète à `0` via `build_daily_summary`).

        L'isolation §11.2 est imposée **en SQL** (`WHERE salon_id = :salon_id`), en
        défense en profondeur de la garde HTTP `require_salon_scope` : la lecture ne
        peut jamais compter un RDV d'un autre salon. L'index `ix_appointments_salon_id
        (salon_id, appointment_date)` couvre le filtre.
        """
        ...

    def count_by_status_in_range(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[str, int]:
        """Décompte des RDV du salon **par statut** sur une plage de dates (#148).

        Miroir « plage » de `count_by_status_for_day` (#39) : renvoie `{status: count}`
        pour les RDV dont `appointment_date` est dans `[date_from, date_to]`
        **inclus** et dont `status ∈ statuses`, agrégés **en base** (`GROUP BY status`).
        Base du KPI « clients en attente » (`statuses=("PENDING",)`) et de son évolution
        (appelé sur la période **et** la période précédente). Un statut sans RDV est
        **absent** de la map (le cas d'usage retombe sur `0`). L'isolation §11.2 est
        imposée **en SQL** (`WHERE salon_id`) ; la lecture ne rapatrie **aucune** ligne
        ni PII (pas de `client_id`). Lecture pure.
        """
        ...

    def count_distinct_completed_clients(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> int:
        """Nombre de **comptes distincts** ayant un RDV réalisé sur la période (#148).

        `COUNT(DISTINCT client_id)` des RDV du salon dont `status ∈ statuses` (le cas
        d'usage impose `HISTORY_STATUSES` — RDV `COMPLETED`, une « visite » §8.1) et dont
        `appointment_date` est dans `[date_from, date_to]` **inclus**. Base du KPI
        « nombre de clientes » et de son évolution (période **et** période précédente).
        Le `client_id` est **compté mais jamais émis** (anti-oracle §11.1/§11.3) : seul
        un entier quitte la base. L'isolation §11.2 est imposée **en SQL**
        (`WHERE salon_id`). Lecture pure.
        """
        ...

    def attendance_series(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Mapping[datetime.date, int]:
        """Fréquentation du salon **par jour civil** sur la période (graphique, #148).

        Renvoie `{appointment_date: count}` — nombre de RDV du salon (tous statuts) par
        jour, agrégé **en base** (`GROUP BY appointment_date`). Un jour sans RDV est
        **absent** de la map (le domaine `build_series` le complète à `0` pour un axe
        continu). L'isolation §11.2 est imposée **en SQL** (`WHERE salon_id`) ; la
        lecture ne rapatrie **aucune** ligne ni PII — seulement `(jour, compte)`. L'index
        `ix_appointments_salon_id (salon_id, appointment_date)` couvre le filtre. Lecture
        pure.
        """
        ...

    def list_in_progress_details(
        self, salon_id: uuid.UUID, *, now: datetime.datetime
    ) -> tuple[InProgressService, ...]:
        """RDV `CONFIRMED` **en cours maintenant**, enrichis des noms d'affichage (#148).

        Un RDV est « en cours » si son créneau `[date+start, date+end)` **contient**
        `now` (naïf, fuseau salon `Africa/Abidjan` = UTC+0) — dérivation `is_in_progress`
        appliquée **en SQL** (`date+start <= now < date+end`), sans statut nouveau ni
        colonne d'horodatage. Résout, par jointures **contraintes au salon**, les
        **noms d'affichage** du client (`users.full_name`), de la/des prestation(s)
        (`services.name`) et du coiffeur assigné (`users.full_name`, LEFT) — **jamais**
        `client_id`/`user_id` ni contact (patron #43/#36). L'isolation §11.2 est imposée
        **en SQL** (`WHERE appointments.salon_id`), en défense en profondeur de la garde
        HTTP. Trié par `start_time` croissant. Lecture pure.
        """
        ...

    def demand_by_service(
        self,
        salon_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
    ) -> tuple[ServiceDemand, ...]:
        """Agrège, **par prestation**, le volume et le revenu du salon (US-6.3 #41).

        Renvoie un `ServiceDemand` par `service_id` réalisé : `volume` = `COUNT` des
        lignes `appointment_services`, `revenue` = `COALESCE(SUM(price_at_booking), 0)`
        (prix **figés**, `Decimal` quantifié au centime `NUMERIC(12,2)`), `name` =
        libellé courant (`services.name`, joint par la composite `(salon_id,
        service_id)` — appartenance salon garantie, résoluble même si la prestation est
        soft-deletée). Ne comptent que les RDV dont `status ∈ statuses` (le cas d'usage
        impose `REVENUE_STATUSES` — « réalisées uniquement ») et, si des bornes sont
        fournies, dont `appointment_date` est dans `[date_from, date_to]` **inclus**
        (une borne `None` reste ouverte).

        La lecture **agrège en base** (`GROUP BY service_id`) et ne rapatrie **aucune**
        ligne de RDV/paiement ni PII (pas de `client_id`, `appointment_id`) — seulement
        `(service_id, name, volume, revenue)` par prestation (§11.3). L'**ordre n'est
        pas garanti** : le domaine (`rank_service_demand`) ordonne. L'isolation §11.2
        est imposée **en SQL** (`WHERE appointments.salon_id = :salon_id`), en défense
        en profondeur de la garde HTTP : jamais une prestation d'un autre salon. Les
        index `ix_appointments_salon_id (salon_id, appointment_date)` et
        `ix_appointment_services_service_id` couvrent la requête. Lecture pure.
        """
        ...

    def performance_by_hairdresser(
        self,
        salon_id: uuid.UUID,
        *,
        date_from: datetime.date,
        date_to: datetime.date,
        completed_statuses: tuple[str, ...],
        cancelled_statuses: tuple[str, ...],
    ) -> tuple[HairdresserActivityCounts, ...]:
        """Agrège, **par coiffeur**, les compteurs de planning du salon (US-6.5 #43).

        Renvoie un `HairdresserActivityCounts` par `hairdresser_id` **assigné**
        (`hairdresser_id IS NOT NULL`) à au moins un RDV du salon dont
        `appointment_date` est dans `[date_from, date_to]` **inclus** :
        `services_completed` = `COUNT` des lignes `appointment_services` des RDV dont
        `status ∈ completed_statuses` (le cas d'usage impose `REVENUE_STATUSES` —
        occurrences **réalisées**) ; `cancelled_count` = `COUNT(*) FILTER (WHERE
        status ∈ cancelled_statuses)` (le cas d'usage impose `CANCELLED_STATUSES`) ;
        `total_count` = `COUNT(*)` (**tous** statuts assignés sur la période) ; `name`
        = `users.full_name` (join, **nom d'affichage seul** — jamais téléphone/e-mail,
        §11.3). Les statuts sont **décidés serveur**, jamais soumis par l'appelant.

        Le comptage des occurrences (`appointment_services`) est **séparé** de celui
        des RDV (`COUNT(*)` / filtres) pour **ne pas sur-compter** `total_count` /
        `cancelled_count` (qui comptent des **RDV**) via le join `appointment_services`
        (spec §Open Questions 6). La lecture **agrège en base** (`GROUP BY
        hairdresser_id`) et ne rapatrie **aucune** ligne de RDV ni PII **client** —
        seulement des compteurs et le nom d'affichage de l'employé. **Ne renvoie pas**
        le CA (le cas d'usage y adjoint le net de la caisse — voir
        `CashJournalRepository.net_revenue_by_hairdresser`). L'**ordre n'est pas
        garanti** : le domaine (`rank_hairdresser_performance`) ordonne. L'isolation
        §11.2 est imposée **en SQL** (`WHERE appointments.salon_id = :salon_id`), en
        défense en profondeur de la garde HTTP : jamais un coiffeur d'un autre salon ;
        un même compte membre de deux salons est mesuré **par salon**. L'index
        `ix_appointments_salon_id (salon_id, appointment_date)` couvre le filtre.
        Lecture pure (aucun `flush`, aucun audit).
        """
        ...

    def mark_arrived(
        self,
        appointment_id: uuid.UUID,
        salon_id: uuid.UUID,
        *,
        now: datetime.datetime,
    ) -> Appointment:
        """Pose `arrived_at` sur le RDV `CONFIRMED` du salon (file d'attente, #150).

        Écriture **conditionnée** au salon **et** au statut `CONFIRMED`
        (`WHERE id = :id AND salon_id = :salon_id AND status = 'CONFIRMED'`) :
        si aucune ligne ne correspond (RDV disparu, hors salon, ou déjà
        réalisé/annulé), lève `domain.errors.InvalidAppointmentTransition`.
        **Idempotent** : si `arrived_at` est déjà posé, la valeur existante est
        **conservée** (pas de second horodatage sur un double clic) — l'appel
        reste un succès. Retourne l'entité relue (avec ses `BookedService`).
        """
        ...

    def mark_started(
        self,
        appointment_id: uuid.UUID,
        salon_id: uuid.UUID,
        *,
        now: datetime.datetime,
    ) -> Appointment:
        """Pose `started_at` sur le RDV `CONFIRMED` du salon (file d'attente, #150).

        Écriture **conditionnée** au salon **et** au statut `CONFIRMED` : si
        aucune ligne ne correspond, lève `domain.errors.
        InvalidAppointmentTransition`. Les préconditions métier (arrivée déjà
        pointée, coiffeuse déjà assignée) sont vérifiées **par le cas
        d'usage** (`StartAppointmentService`) avant l'appel — ce dépôt ne les
        revalide pas. **Idempotent** comme `mark_arrived`. Retourne l'entité
        relue.
        """
        ...

    def list_queue_details(
        self, salon_id: uuid.UUID, *, day: datetime.date
    ) -> tuple[QueueAppointmentRow, ...]:
        """RDV `CONFIRMED`/`COMPLETED` du salon pour `day`, enrichis des noms (#150).

        Miroir de `list_in_progress_details` (#148) : deux lectures bornées
        (RDV + noms client/coiffeur via `users`, puis noms de prestation via
        `appointment_services`/`services` — pour ne pas dupliquer les lignes
        du join un-à-plusieurs). Filtre `appointment_date == day` et
        `status ∈ domain.queue.QUEUE_APPOINTMENT_STATUSES` (ni `PENDING` non
        confirmé, ni `CANCELLED`/`NO_SHOW`). Émet **uniquement** des noms
        d'affichage (jamais `client_id`/`user_id`, patron #43/#36) ;
        `hairdresser_id` reste exposé (opaque, le gérant agit sur la ligne).
        L'isolation §11.2 est imposée **en SQL** (`WHERE salon_id`). Trié par
        `start_time` croissant. Lecture pure — ne résout **pas** le paiement
        (responsabilité de `PaymentRepository`, combinée par le cas d'usage).
        """
        ...

    def list_for_hairdresser(
        self,
        hairdresser_id: uuid.UUID,
        date_from: datetime.date,
        date_to: datetime.date,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[Appointment, ...]:
        """Liste les RDV **assignés au coiffeur** sur une plage (planning coiffeur, #27).

        Miroir assignment-scopé de `list_for_salon` : renvoie les RDV dont
        `hairdresser_id == :hairdresser_id` et dont `appointment_date` est dans
        `[date_from, date_to]` (**inclusif**), avec leurs `BookedService`, triés
        `(appointment_date, start_time)`. `statuses=None` ne filtre pas sur le statut
        (**tous** statuts, y compris terminaux) ; une liste restreint. **Ne renvoie
        jamais** un RDV assigné à un autre coiffeur, un RDV **non assigné**
        (`hairdresser_id IS NULL`), ni un RDV d'un autre salon : l'isolation « son
        planning » (§11.2) est imposée **en SQL** (`WHERE hairdresser_id =
        :hairdresser_id`), en défense en profondeur du filtre serveur (le
        `hairdresser_id` vient du `Principal`, jamais d'un champ soumis).
        """
        ...


__all__ = ["AppointmentRepository"]
