"""Tests unitaires — domaine `notification.py` (US-7.1 #45, US-7.2 #46).

Couvre les fonctions et dataclasses pures sans I/O :

- `ChannelAvailability` : valeurs par défaut, immuabilité ;
- `resolve_notification_channel` (+ alias `resolve_confirmation_channel`) : priorité
  PUSH → SMS → IN_APP, déterminisme ;
- `build_confirmation_notification` : champs attendus, status PENDING, aucune PII ;
- `compute_reminder_schedules` : échéances futures, filtre du passé, déterminisme ;
- `build_reminder_notifications` : champs attendus, `scheduled_for`, aucune PII ;
- `NotificationToCreate` : immuabilité, status par défaut, aucune PII portée.
"""

from __future__ import annotations

import dataclasses
import datetime
import uuid

import pytest

from coiflink_api.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from coiflink_api.domain.notification import (
    CONFIRMATION_MESSAGE,
    CONFIRMATION_TITLE,
    REMINDER_MESSAGE,
    REMINDER_OFFSETS,
    REMINDER_TITLE,
    ChannelAvailability,
    NotificationToCreate,
    build_confirmation_notification,
    build_reminder_notifications,
    compute_reminder_schedules,
    resolve_confirmation_channel,
    resolve_notification_channel,
)

# ---------------------------------------------------------------------------
# Constantes synthétiques (aucune PII réelle)
# ---------------------------------------------------------------------------

_CLIENT_ID = uuid.UUID("22222222-0000-0000-0000-000000000002")
_SALON_ID = uuid.UUID("11111111-0000-0000-0000-000000000001")
_APPOINTMENT_ID = uuid.UUID("aaaaaa00-0000-0000-0000-000000000001")
_APPOINTMENT_START = datetime.datetime(2026, 8, 10, 9, 0)


# ---------------------------------------------------------------------------
# ChannelAvailability
# ---------------------------------------------------------------------------


class TestChannelAvailability:
    def test_defaults_are_both_false(self) -> None:
        avail = ChannelAvailability()
        assert avail.has_push_token is False
        assert avail.has_phone is False

    def test_is_immutable(self) -> None:
        avail = ChannelAvailability(has_push_token=True)
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            avail.has_push_token = False  # type: ignore[misc]

    def test_carries_no_pii(self) -> None:
        # L'objet porte des booléens (le *fait* qu'un canal est disponible),
        # jamais un numéro de téléphone ni un jeton d'appareil.
        avail = ChannelAvailability(has_push_token=True, has_phone=True)
        for value in dataclasses.asdict(avail).values():
            assert isinstance(value, bool)


# ---------------------------------------------------------------------------
# resolve_confirmation_channel
# ---------------------------------------------------------------------------


class TestResolveConfirmationChannel:
    def test_push_token_returns_push(self) -> None:
        avail = ChannelAvailability(has_push_token=True, has_phone=False)
        assert resolve_confirmation_channel(avail) == NotificationChannel.PUSH.value

    def test_push_takes_priority_over_phone(self) -> None:
        avail = ChannelAvailability(has_push_token=True, has_phone=True)
        assert resolve_confirmation_channel(avail) == NotificationChannel.PUSH.value

    def test_phone_without_push_returns_sms(self) -> None:
        avail = ChannelAvailability(has_push_token=False, has_phone=True)
        assert resolve_confirmation_channel(avail) == NotificationChannel.SMS.value

    def test_no_channel_returns_in_app(self) -> None:
        avail = ChannelAvailability(has_push_token=False, has_phone=False)
        assert resolve_confirmation_channel(avail) == NotificationChannel.IN_APP.value

    def test_default_availability_returns_in_app(self) -> None:
        assert resolve_confirmation_channel(ChannelAvailability()) == NotificationChannel.IN_APP.value

    def test_result_is_a_string(self) -> None:
        for avail in [
            ChannelAvailability(has_push_token=True),
            ChannelAvailability(has_phone=True),
            ChannelAvailability(),
        ]:
            assert isinstance(resolve_confirmation_channel(avail), str)

    def test_whatsapp_is_never_returned(self) -> None:
        for avail in [
            ChannelAvailability(has_push_token=True),
            ChannelAvailability(has_phone=True),
            ChannelAvailability(),
        ]:
            assert resolve_confirmation_channel(avail) != NotificationChannel.WHATSAPP.value

    def test_email_is_never_returned(self) -> None:
        for avail in [
            ChannelAvailability(has_push_token=True),
            ChannelAvailability(has_phone=True),
            ChannelAvailability(),
        ]:
            assert resolve_confirmation_channel(avail) != NotificationChannel.EMAIL.value

    def test_deterministic_same_input_same_output(self) -> None:
        avail = ChannelAvailability(has_phone=True)
        assert resolve_confirmation_channel(avail) == resolve_confirmation_channel(avail)

    def test_confirmation_channel_is_alias_of_notification_channel(self) -> None:
        # #46 généralise `resolve_confirmation_channel` en `resolve_notification_channel` ;
        # l'ancien nom reste un alias rétrocompatible (même fonction).
        assert resolve_confirmation_channel is resolve_notification_channel


# ---------------------------------------------------------------------------
# build_confirmation_notification
# ---------------------------------------------------------------------------


class TestBuildConfirmationNotification:
    def _build(
        self,
        *,
        client_id: uuid.UUID = _CLIENT_ID,
        salon_id: uuid.UUID = _SALON_ID,
        appointment_id: uuid.UUID = _APPOINTMENT_ID,
        channel: str = NotificationChannel.SMS.value,
    ) -> NotificationToCreate:
        return build_confirmation_notification(
            client_id=client_id,
            salon_id=salon_id,
            appointment_id=appointment_id,
            channel=channel,
        )

    def test_type_is_confirmation(self) -> None:
        n = self._build()
        assert n.type == NotificationType.CONFIRMATION.value

    def test_status_is_pending(self) -> None:
        n = self._build()
        assert n.status == NotificationStatus.PENDING.value

    def test_user_id_is_client_id(self) -> None:
        n = self._build(client_id=_CLIENT_ID)
        assert n.user_id == _CLIENT_ID

    def test_salon_id_is_set(self) -> None:
        n = self._build(salon_id=_SALON_ID)
        assert n.salon_id == _SALON_ID

    def test_appointment_id_is_set(self) -> None:
        n = self._build(appointment_id=_APPOINTMENT_ID)
        assert n.appointment_id == _APPOINTMENT_ID

    def test_channel_is_forwarded(self) -> None:
        for channel in [
            NotificationChannel.PUSH.value,
            NotificationChannel.SMS.value,
            NotificationChannel.IN_APP.value,
        ]:
            n = self._build(channel=channel)
            assert n.channel == channel

    def test_title_is_template_constant(self) -> None:
        n = self._build()
        assert n.title == CONFIRMATION_TITLE

    def test_message_is_template_constant(self) -> None:
        n = self._build()
        assert n.message == CONFIRMATION_MESSAGE

    def test_result_is_immutable(self) -> None:
        n = self._build()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            n.status = "SENT"  # type: ignore[misc]

    def test_title_contains_no_phone_number(self) -> None:
        n = self._build()
        # Titre templaté : aucun numéro de téléphone.
        assert "+" not in n.title
        assert not any(c.isdigit() for c in n.title)

    def test_message_contains_no_phone_number(self) -> None:
        n = self._build()
        assert "+" not in n.message

    def test_notification_carries_only_opaque_ids(self) -> None:
        n = self._build()
        as_dict = dataclasses.asdict(n)
        # Les champs scalaires de texte (title, message, type, channel, status)
        # ne doivent pas contenir l'UUID du client sous forme littérale.
        client_str = str(_CLIENT_ID)
        for key in ("title", "message", "type", "channel", "status"):
            assert client_str not in as_dict[key]

    def test_sent_at_is_absent(self) -> None:
        n = self._build()
        assert not hasattr(n, "sent_at")

    def test_different_clients_produce_different_user_ids(self) -> None:
        other_client = uuid.UUID("99999999-0000-0000-0000-000000000099")
        n1 = self._build(client_id=_CLIENT_ID)
        n2 = self._build(client_id=other_client)
        assert n1.user_id != n2.user_id


# ---------------------------------------------------------------------------
# NotificationToCreate (dataclass)
# ---------------------------------------------------------------------------


class TestNotificationToCreate:
    def test_default_status_is_pending(self) -> None:
        n = NotificationToCreate(
            type=NotificationType.CONFIRMATION.value,
            channel=NotificationChannel.SMS.value,
            title="T",
            message="M",
        )
        assert n.status == NotificationStatus.PENDING.value

    def test_is_immutable(self) -> None:
        n = NotificationToCreate(
            type=NotificationType.CONFIRMATION.value,
            channel=NotificationChannel.SMS.value,
            title="T",
            message="M",
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            n.status = "SENT"  # type: ignore[misc]

    def test_user_id_defaults_to_none(self) -> None:
        n = NotificationToCreate(
            type="X",
            channel="Y",
            title="T",
            message="M",
        )
        assert n.user_id is None

    def test_salon_id_defaults_to_none(self) -> None:
        n = NotificationToCreate(
            type="X",
            channel="Y",
            title="T",
            message="M",
        )
        assert n.salon_id is None

    def test_appointment_id_defaults_to_none(self) -> None:
        n = NotificationToCreate(
            type="X",
            channel="Y",
            title="T",
            message="M",
        )
        assert n.appointment_id is None

    def test_scheduled_for_defaults_to_none(self) -> None:
        # `None` = confirmation (à remettre au plus tôt, #45, inchangé).
        n = NotificationToCreate(
            type="X",
            channel="Y",
            title="T",
            message="M",
        )
        assert n.scheduled_for is None


# ---------------------------------------------------------------------------
# compute_reminder_schedules (US-7.2, #46)
# ---------------------------------------------------------------------------


class TestComputeReminderSchedules:
    def test_far_future_appointment_yields_three_offsets(self) -> None:
        now = _APPOINTMENT_START - datetime.timedelta(days=2)
        due = compute_reminder_schedules(_APPOINTMENT_START, now=now)
        assert len(due) == 3

    def test_offsets_match_appointment_start_minus_offset(self) -> None:
        now = _APPOINTMENT_START - datetime.timedelta(days=2)
        due = compute_reminder_schedules(_APPOINTMENT_START, now=now)
        expected = {
            _APPOINTMENT_START - offset for offset in REMINDER_OFFSETS
        }
        assert set(due) == expected

    def test_order_follows_offsets_declaration(self) -> None:
        # `REMINDER_OFFSETS` est ordonné 24h → 2h → 30min : les échéances renvoyées
        # suivent le même ordre (du plus lointain au plus proche).
        now = _APPOINTMENT_START - datetime.timedelta(days=2)
        due = compute_reminder_schedules(_APPOINTMENT_START, now=now)
        assert list(due) == sorted(due)

    def test_past_offset_excluded(self) -> None:
        # Réservé 90 min à l'avance : seul l'offset 30 min est encore futur.
        now = _APPOINTMENT_START - datetime.timedelta(minutes=90)
        due = compute_reminder_schedules(_APPOINTMENT_START, now=now)
        assert due == (_APPOINTMENT_START - datetime.timedelta(minutes=30),)

    def test_all_offsets_past_yields_empty_tuple(self) -> None:
        # Réservé 10 min à l'avance : aucun offset (24h/2h/30min) n'est encore futur.
        now = _APPOINTMENT_START - datetime.timedelta(minutes=10)
        due = compute_reminder_schedules(_APPOINTMENT_START, now=now)
        assert due == ()

    def test_offset_exactly_at_now_is_excluded(self) -> None:
        # Filtre strict (`> now`, pas `>=`) : une échéance égale à `now` n'est pas
        # « encore » future.
        now = _APPOINTMENT_START - datetime.timedelta(minutes=30)
        due = compute_reminder_schedules(
            _APPOINTMENT_START, now=now, offsets=(datetime.timedelta(minutes=30),)
        )
        assert due == ()

    def test_deterministic_same_input_same_output(self) -> None:
        now = _APPOINTMENT_START - datetime.timedelta(days=2)
        assert compute_reminder_schedules(_APPOINTMENT_START, now=now) == (
            compute_reminder_schedules(_APPOINTMENT_START, now=now)
        )

    def test_custom_offsets_are_honored(self) -> None:
        now = _APPOINTMENT_START - datetime.timedelta(days=2)
        custom = (datetime.timedelta(hours=1),)
        due = compute_reminder_schedules(_APPOINTMENT_START, now=now, offsets=custom)
        assert due == (_APPOINTMENT_START - datetime.timedelta(hours=1),)


# ---------------------------------------------------------------------------
# build_reminder_notifications (US-7.2, #46)
# ---------------------------------------------------------------------------


class TestBuildReminderNotifications:
    _NOW = _APPOINTMENT_START - datetime.timedelta(days=2)

    def _build(
        self,
        *,
        client_id: uuid.UUID = _CLIENT_ID,
        salon_id: uuid.UUID = _SALON_ID,
        appointment_id: uuid.UUID = _APPOINTMENT_ID,
        appointment_start: datetime.datetime = _APPOINTMENT_START,
        channel: str = NotificationChannel.SMS.value,
        now: datetime.datetime | None = None,
    ) -> tuple[NotificationToCreate, ...]:
        return build_reminder_notifications(
            client_id=client_id,
            salon_id=salon_id,
            appointment_id=appointment_id,
            appointment_start=appointment_start,
            channel=channel,
            now=now if now is not None else self._NOW,
        )

    def test_one_reminder_per_future_offset(self) -> None:
        reminders = self._build()
        assert len(reminders) == 3

    def test_type_is_reminder(self) -> None:
        for reminder in self._build():
            assert reminder.type == NotificationType.REMINDER.value

    def test_status_is_pending(self) -> None:
        for reminder in self._build():
            assert reminder.status == NotificationStatus.PENDING.value

    def test_user_id_is_client_id(self) -> None:
        for reminder in self._build():
            assert reminder.user_id == _CLIENT_ID

    def test_salon_id_is_set(self) -> None:
        for reminder in self._build():
            assert reminder.salon_id == _SALON_ID

    def test_appointment_id_is_set(self) -> None:
        for reminder in self._build():
            assert reminder.appointment_id == _APPOINTMENT_ID

    def test_scheduled_for_matches_computed_schedules(self) -> None:
        reminders = self._build()
        expected = set(
            compute_reminder_schedules(_APPOINTMENT_START, now=self._NOW)
        )
        assert {r.scheduled_for for r in reminders} == expected

    def test_channel_is_forwarded(self) -> None:
        for channel in [
            NotificationChannel.PUSH.value,
            NotificationChannel.SMS.value,
            NotificationChannel.IN_APP.value,
        ]:
            reminders = self._build(channel=channel)
            assert all(r.channel == channel for r in reminders)

    def test_title_is_template_constant(self) -> None:
        for reminder in self._build():
            assert reminder.title == REMINDER_TITLE

    def test_message_is_template_constant(self) -> None:
        for reminder in self._build():
            assert reminder.message == REMINDER_MESSAGE

    def test_title_contains_no_pii(self) -> None:
        for reminder in self._build():
            assert "+" not in reminder.title
            assert not any(c.isdigit() for c in reminder.title)

    def test_message_contains_no_pii(self) -> None:
        for reminder in self._build():
            assert "+" not in reminder.message

    def test_result_is_immutable(self) -> None:
        reminder = self._build()[0]
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            reminder.status = "SENT"  # type: ignore[misc]

    def test_close_appointment_yields_fewer_reminders(self) -> None:
        now = _APPOINTMENT_START - datetime.timedelta(minutes=90)
        reminders = self._build(now=now)
        assert len(reminders) == 1
        assert reminders[0].scheduled_for == _APPOINTMENT_START - datetime.timedelta(
            minutes=30
        )

    def test_immediate_appointment_yields_no_reminder(self) -> None:
        now = _APPOINTMENT_START - datetime.timedelta(minutes=10)
        assert self._build(now=now) == ()
