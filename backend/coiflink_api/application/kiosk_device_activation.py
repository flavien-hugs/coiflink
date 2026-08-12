"""Cas d'usage : activation d'une borne kiosque par code à 6 chiffres (US-8.1, #155 — provisioning silencieux).

Rend le provisioning **utilisable sur un écran tactile** : le gérant ne recopie plus
un secret de ~43 caractères, il lit un **code à 6 chiffres** sur la réponse du
provisioning et le saisit une fois sur la borne. La borne échange ce code contre son
credential longue durée, puis utilise `POST /auth/kiosk/login` **inchangé** pour
toutes ses sessions ultérieures.

Le secret longue durée est généré **ici**, à l'activation — jamais au provisioning.
C'est ce qui préserve l'invariant §11.3 (« le secret n'est jamais persisté en clair,
jamais journalisé, jamais relisible ») : au provisioning, `ProvisionKioskDevice` ne
pose qu'un condensat **placeholder** (secret jetable aussitôt oublié), donc
inutilisable — `/auth/kiosk/login` échoue déterministiquement sur une borne non
activée, sans aucun cas particulier à câbler ailleurs. À l'activation, le secret réel
est tiré, haché, écrit à la place du placeholder, et renvoyé **une seule fois**.

Comme le reset par OTP (#11), le défi d'activation est un `OtpChallenge` du domaine :
usage unique (`consumed`), expiration, limite d'essais et comparaison en **temps
constant** — le code n'est jamais journalisé. Horloge et limiteur sont **injectables**
pour des tests déterministes ; le cas d'usage ne dépend que de **ports** (aucune
dépendance FastAPI/SQLAlchemy/argon2).

Garde-fous de sécurité (PRD §11.1/§11.3, ADR-0041, spec §Security) :
- **anti-énumération** : code inconnu, expiré, déjà consommé ou trop d'essais lèvent
  tous la **même** `InvalidActivationCode` (message générique constant, `400`) —
  aucun oracle sur l'existence d'un code ni sur l'état d'une borne ;
- **anti-bruteforce** : le limiteur (clé = IP — le `device_id` est **inconnu** avant
  résolution du code) est consulté **avant** tout accès au dépôt ; un échec
  incrémente, un succès réinitialise ;
- **usage unique garanti** : `verify_otp_challenge` consomme le défi **et** le défi
  est supprimé après succès — un code réutilisé ne peut plus émettre de secret.
"""

from __future__ import annotations

import datetime
import secrets
import uuid
from dataclasses import dataclass
from typing import Callable

from coiflink_api.application.ports.kiosk_activation_repository import (
    KioskActivationRepository,
)
from coiflink_api.application.ports.kiosk_device_repository import KioskDeviceRepository
from coiflink_api.application.ports.login_rate_limiter import LoginRateLimiter
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.domain.errors import InvalidActivationCode
from coiflink_api.domain.otp import OtpStatus, verify_otp_challenge

# Message unique renvoyé pour **tout** échec d'activation (anti-énumération) : code
# inconnu, expiré, trop d'essais ou déjà consommé. Ne divulgue jamais la cause
# exacte ni l'existence d'une borne.
_INVALID_CODE_MESSAGE = "Code d'activation invalide ou expiré."
# Le secret longue durée de la borne (32 octets, ~43 caractères) — même mécanisme
# que ProvisionKioskDevice, juste déclenché par l'activation plutôt que la création.
_SECRET_NBYTES = 32


def _utc_now() -> datetime.datetime:
    """Horloge par défaut : instant courant en UTC (aware)."""

    return datetime.datetime.now(datetime.timezone.utc)


@dataclass(frozen=True)
class ActivateKioskDeviceCommand:
    """Entrée de l'activation : le code saisi sur la borne (aucun `device_id`).

    La borne ne connaît **que** le code à ce stade — c'est le code qui résout la
    borne, jamais l'inverse. `client_ip` (optionnelle) est la seule clé disponible
    pour l'anti-bruteforce.
    """

    code: str
    client_ip: str | None = None


@dataclass(frozen=True)
class ActivateKioskDeviceResult:
    """Résultat d'une activation réussie : identité de la borne **+ secret (une fois)**.

    Le `secret` n'est **jamais** persisté en clair, **jamais** journalisé et
    **jamais** relisible : seul son condensat argon2id est stocké.
    """

    device_id: uuid.UUID
    secret: str


class ActivateKioskDevice:
    """Cas d'usage : code d'activation valide → secret de borne émis, sinon lève."""

    def __init__(
        self,
        activation_repository: KioskActivationRepository,
        device_repository: KioskDeviceRepository,
        hasher: PasswordHasher,
        *,
        rate_limiter: LoginRateLimiter | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self._activation_repository = activation_repository
        self._device_repository = device_repository
        self._hasher = hasher
        self._rate_limiter = rate_limiter
        self._clock = clock if clock is not None else _utc_now

    def execute(self, command: ActivateKioskDeviceCommand) -> ActivateKioskDeviceResult:
        """Échange le code contre le secret de la borne ; lève `InvalidActivationCode` sinon.

        Effet net en cas de succès : `users.password_hash` de la borne porte le
        condensat du secret **réel** (le placeholder du provisioning est écrasé) et
        le défi est supprimé — la borne peut se connecter via `/auth/kiosk/login`, et
        le code ne vaut plus rien. Lève `TooManyLoginAttempts` (⇒ `429`) si l'IP est
        verrouillée.
        """

        # 1. Clé d'anti-bruteforce : l'IP seule (aucun `device_id` connu avant
        #    résolution du code). Verrou consulté AVANT tout accès dépôt.
        key = f"kiosk-activate|{command.client_ip or '-'}"
        if self._rate_limiter is not None:
            self._rate_limiter.check(key)

        # 2. Normaliser le code. Un code vide/illisible ne divulgue rien : il suit le
        #    même chemin qu'un code inconnu (400 générique).
        code = command.code.strip() if isinstance(command.code, str) else ""

        # 3. Résoudre le défi par sa valeur. Absent ⇒ 400 générique (même chemin
        #    qu'un code faux), après avoir compté l'échec pour l'anti-bruteforce.
        found = self._activation_repository.find_by_code(code) if code else None
        if found is None:
            self._record_failure(key)
            raise InvalidActivationCode(_INVALID_CODE_MESSAGE)
        device_id, challenge = found

        # 4. Vérifier (temps constant, mutation en place).
        status = verify_otp_challenge(challenge, code, self._clock())
        if status is not OtpStatus.VALID:
            # Persister l'état muté (matérialise la décrémente d'essais sur INVALID)
            # puis lever un 400 **unique** — aucune divulgation de la cause exacte.
            self._activation_repository.save(device_id, challenge)
            self._record_failure(key)
            raise InvalidActivationCode(_INVALID_CODE_MESSAGE)

        # 5. Générer le secret **réel** (première et unique fois), le hacher et
        #    écraser le condensat placeholder posé au provisioning.
        secret = secrets.token_urlsafe(_SECRET_NBYTES)
        self._device_repository.set_password_hash(device_id, self._hasher.hash(secret))

        # Supprimer le défi (usage unique **garanti** après succès) et lever le verrou.
        self._activation_repository.delete(device_id)
        if self._rate_limiter is not None:
            self._rate_limiter.reset(key)

        return ActivateKioskDeviceResult(device_id=device_id, secret=secret)

    def _record_failure(self, key: str) -> None:
        if self._rate_limiter is not None:
            self._rate_limiter.record_failure(key)


__all__ = [
    "ActivateKioskDeviceCommand",
    "ActivateKioskDeviceResult",
    "ActivateKioskDevice",
]
