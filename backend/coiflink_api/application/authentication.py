"""Cas d'usage : **connexion** et **rafraîchissement de jeton** (application, ADR-0008).

Orchestre l'authentification par **téléphone ou e-mail + mot de passe** (US-1.2,
issue #10) puis l'émission d'une paire **JWT d'accès + refresh** ; et l'échange
d'un refresh valide contre une nouvelle paire. Comme l'inscription (#8/#9), le
cas d'usage ne dépend que de **ports** : dépôt utilisateur, hacheur, service de
jetons, limiteur anti-bruteforce — jamais de FastAPI, SQLAlchemy ni PyJWT.

Garde-fous de sécurité (PRD §11.1) :
- **anti-énumération** : identifiant inconnu, mot de passe faux ou compte non
  `ACTIVE` lèvent tous `InvalidCredentials` (même message générique) ;
- **anti-oracle temporel** : quand aucun compte ne correspond, on exécute quand
  même une vérification argon2 **factice** (condensat *dummy* pré-calculé) pour
  égaliser grossièrement le temps de réponse ;
- **anti-bruteforce** : le limiteur est consulté **avant** tout accès base ; un
  échec incrémente le compteur, un succès le réinitialise ;
- le mot de passe en clair ne vit que le temps de `verify()` — jamais journalisé.
"""

from __future__ import annotations

from dataclasses import dataclass

from coiflink_api.application.ports.login_rate_limiter import LoginRateLimiter
from coiflink_api.application.ports.password_hasher import PasswordHasher
from coiflink_api.application.ports.token_service import TokenService
from coiflink_api.application.ports.user_repository import UserRepository
from coiflink_api.domain.credentials import UserCredentials
from coiflink_api.domain.enums import UserStatus
from coiflink_api.domain.errors import InvalidCredentials, InvalidPhone, InvalidToken
from coiflink_api.domain.identifier import EMAIL, LoginIdentifier, classify_identifier
from coiflink_api.domain.tokens import TokenPair

# Message unique renvoyé pour **tout** échec d'authentification (anti-énumération).
_INVALID_CREDENTIALS_MESSAGE = "Identifiants invalides."

# Mot de passe factice haché une fois pour la vérification d'atténuation d'oracle
# temporel quand aucun compte ne correspond. Sa valeur n'a aucune importance : il
# n'est jamais comparé à un vrai compte.
_DUMMY_PASSWORD = "dummy-password-for-timing-mitigation"


@dataclass(frozen=True)
class LoginCommand:
    """Entrée de la connexion (mot de passe en clair, éphémère).

    `identifier` est un **téléphone ou un e-mail** ; `client_ip` (optionnelle)
    entre dans la clé d'anti-bruteforce pour ne pas verrouiller le compte d'un
    tiers sur la seule base de l'identifiant.
    """

    identifier: str
    password: str
    client_ip: str | None = None


class AuthenticateUser:
    """Cas d'usage de connexion : identifiants valides → `TokenPair`, sinon lève."""

    def __init__(
        self,
        repository: UserRepository,
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
        # Condensat factice pré-calculé (injecté par le composition root) ; calculé
        # paresseusement au premier besoin sinon.
        self._dummy_hash = dummy_hash

    def execute(self, command: LoginCommand) -> TokenPair:
        """Authentifie puis émet une paire de jetons ; lève sinon (générique)."""

        raw = command.identifier.strip() if isinstance(command.identifier, str) else ""
        identifier = self._classify(raw)
        # Clé d'anti-bruteforce : identifiant normalisé (ou brut si inclassable) + IP.
        key_id = identifier.value if identifier is not None else raw
        key = f"{key_id}|{command.client_ip or '-'}"

        # Vérification du verrou AVANT tout accès base (lève TooManyLoginAttempts).
        self._rate_limiter.check(key)

        creds = self._find(identifier)
        password_ok = self._verify_password(creds, command.password)

        if creds is None or not password_ok or creds.status != UserStatus.ACTIVE.value:
            self._rate_limiter.record_failure(key)
            raise InvalidCredentials(_INVALID_CREDENTIALS_MESSAGE)

        self._rate_limiter.reset(key)
        return self._token_service.issue_pair(creds.id, creds.role)

    def _classify(self, raw: str) -> LoginIdentifier | None:
        """Classe l'identifiant ; `None` si vide ou téléphone inexploitable.

        Un identifiant inclassable ne divulgue rien : le parcours continue et
        aboutira au même `InvalidCredentials` générique.
        """

        if not raw:
            return None
        try:
            return classify_identifier(raw)
        except InvalidPhone:
            return None

    def _find(self, identifier: LoginIdentifier | None) -> UserCredentials | None:
        """Recherche le compte correspondant à l'identifiant classé."""

        if identifier is None:
            return None
        if identifier.kind == EMAIL:
            return self._repository.find_by_email(identifier.value)
        return self._repository.find_by_phone(identifier.value)

    def _verify_password(self, creds: UserCredentials | None, password: str) -> bool:
        """Vérifie le mot de passe ; vérification **factice** si aucun compte.

        Sans compte trouvé, on hache/vérifie contre un condensat *dummy* pour ne
        pas révéler par le temps de réponse qu'aucun compte n'existe.
        """

        if creds is None:
            self._hasher.verify(password, self._get_dummy_hash())
            return False
        return self._hasher.verify(password, creds.password_hash)

    def _get_dummy_hash(self) -> str:
        if self._dummy_hash is None:
            self._dummy_hash = self._hasher.hash(_DUMMY_PASSWORD)
        return self._dummy_hash


class RefreshTokens:
    """Cas d'usage : échange d'un refresh valide contre une **nouvelle** paire.

    Vérifie le refresh (`type == "refresh"`, signature, `exp`), **recharge** le
    compte pour relire `role`/`status` courants (un compte devenu non `ACTIVE` est
    refusé), puis émet une nouvelle paire (rotation). Lève `InvalidToken` /
    `ExpiredToken` — message générique côté HTTP.
    """

    def __init__(self, repository: UserRepository, token_service: TokenService) -> None:
        self._repository = repository
        self._token_service = token_service

    def execute(self, refresh_token: str) -> TokenPair:
        claims = self._token_service.verify_refresh(refresh_token)
        creds = self._repository.find_by_id(claims.sub)
        if creds is None or creds.status != UserStatus.ACTIVE.value:
            raise InvalidToken("Jeton de rafraîchissement invalide.")
        return self._token_service.issue_pair(creds.id, creds.role)


__all__ = ["LoginCommand", "AuthenticateUser", "RefreshTokens"]
