"""Cas d'usage : **authentification d'une borne terminal** (US-8.1, #155).

Échange le credential de device longue durée `(device_id, secret)` — stocké côté
borne (#159/#161) — contre une paire JWT **standard et courte** au rôle `TERMINAL`.
La « longue durée » exigée par l'issue est portée par le **secret révocable**, pas
par un jeton à TTL étendu : un jeton exfiltré expire en 15 min, et la suspension du
compte device coupe l'accès **à la requête suivante** (ADR-0041/ADR-0015).

Comme `AuthenticateUser` (#10), ce cas d'usage ne dépend que de **ports** (dépôt de
bornes, hacheur, service de jetons, limiteur anti-bruteforce) et applique les mêmes
garde-fous de sécurité :

- **anti-oracle** : device inconnu, secret faux **ou** device révoqué (statut non
  `ACTIVE`) lèvent tous `InvalidCredentials` (même message générique — aucun oracle
  sur l'existence ou l'état d'un device) ;
- **anti-oracle temporel** : sans device correspondant, on exécute quand même une
  vérification argon2 **factice** pour égaliser grossièrement le temps de réponse ;
- **anti-bruteforce** : le limiteur (clé = `device_id`) est consulté **avant** tout
  accès base ; un échec incrémente, un succès réinitialise ;
- le secret en clair ne vit que le temps de `verify()` — jamais journalisé.

La réponse porte le `salon_id` du device (mécanisme retenu pour tout le jalon : un
APK unique pour toutes les bornes, la borne apprend son salon au provisioning).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from coiflink_api.application.ports.terminal_device_repository import TerminalDeviceRepository
from coiflink_api.application.ports.login_rate_limiter import LoginRateLimiter
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.application.ports.token_service import TokenService
from coiflink_api.domain.enums import Role, UserStatus
from coiflink_api.domain.errors import InvalidCredentials
from coiflink_api.domain.terminal_device import TerminalDeviceCredentials
from coiflink_api.domain.tokens import TokenPair

# Message unique renvoyé pour **tout** échec d'authentification (anti-énumération).
_INVALID_CREDENTIALS_MESSAGE = "Identifiants invalides."

# Secret factice haché une fois pour l'atténuation d'oracle temporel quand aucun
# device ne correspond. Sa valeur n'a aucune importance : jamais comparé à un device.
_DUMMY_SECRET = "dummy-terminal-secret-for-timing-mitigation"


@dataclass(frozen=True)
class TerminalLoginCommand:
    """Entrée de l'authentification d'une borne (secret en clair, éphémère).

    `client_ip` (optionnelle) entre dans la clé d'anti-bruteforce pour ne pas
    verrouiller un device sur la seule base de son identifiant.
    """

    device_id: str
    secret: str
    client_ip: str | None = None


@dataclass(frozen=True)
class TerminalLoginResult:
    """Résultat d'une authentification borne réussie : paire JWT + `salon_id`."""

    tokens: TokenPair
    salon_id: uuid.UUID


class AuthenticateTerminalDevice:
    """Cas d'usage : credential de device valide → `TerminalLoginResult`, sinon lève."""

    def __init__(
        self,
        repository: TerminalDeviceRepository,
        hasher: PasswordHasher,
        token_service: TokenService,
        rate_limiter: LoginRateLimiter,
        *,
        dummy_hash: str | None = None,
    ) -> None:
        self._repository = repository
        self._hasher = hasher
        self._token_service = token_service
        self._rate_limiter = rate_limiter
        self._dummy_hash = dummy_hash

    def execute(self, command: TerminalLoginCommand) -> TerminalLoginResult:
        """Authentifie la borne puis émet une paire de jetons ; lève sinon (générique)."""

        raw = command.device_id.strip() if isinstance(command.device_id, str) else ""
        # Clé d'anti-bruteforce : identifiant de device (brut) + IP.
        key = f"{raw}|{command.client_ip or '-'}"

        # Vérification du verrou AVANT tout accès base (lève TooManyLoginAttempts).
        self._rate_limiter.check(key)

        creds = self._find(raw)
        secret_ok = self._verify_secret(creds, command.secret)

        if creds is None or not secret_ok or creds.status != UserStatus.ACTIVE.value:
            self._rate_limiter.record_failure(key)
            raise InvalidCredentials(_INVALID_CREDENTIALS_MESSAGE)

        self._rate_limiter.reset(key)
        tokens = self._token_service.issue_pair(creds.id, Role.TERMINAL.value)
        return TerminalLoginResult(tokens=tokens, salon_id=creds.salon_id)

    def _find(self, raw_device_id: str) -> TerminalDeviceCredentials | None:
        """Résout le credential du device ; `None` si `device_id` illisible/inconnu.

        Un `device_id` non convertible en UUID (saisie invalide) ne divulgue rien :
        le parcours continue et aboutira au même `InvalidCredentials` générique.
        """

        if not raw_device_id:
            return None
        try:
            device_id = uuid.UUID(raw_device_id)
        except (ValueError, TypeError):
            return None
        return self._repository.find_credentials(device_id)

    def _verify_secret(
        self, creds: TerminalDeviceCredentials | None, secret: str
    ) -> bool:
        """Vérifie le secret ; vérification **factice** si aucun device (anti-oracle)."""

        if creds is None:
            self._hasher.verify(secret, self._get_dummy_hash())
            return False
        return self._hasher.verify(secret, creds.password_hash)

    def _get_dummy_hash(self) -> str:
        if self._dummy_hash is None:
            self._dummy_hash = self._hasher.hash(_DUMMY_SECRET)
        return self._dummy_hash


__all__ = [
    "TerminalLoginCommand",
    "TerminalLoginResult",
    "AuthenticateTerminalDevice",
]
