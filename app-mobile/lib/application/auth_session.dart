// Session cliente — application, #22.
//
// Fine surcouche autour du [TokenStore] : expose l'état d'authentification au
// tunnel de réservation (lecture du jeton, enregistrement après connexion,
// invalidation sur `401`). Ne connaît ni Flutter ni HTTP (ADR-0008). Le jeton
// n'est **jamais journalisé** (§11.1).

import 'ports/token_store.dart';

/// État d'authentification de la session cliente.
class AuthSession {
  AuthSession(this._store);

  final TokenStore _store;

  /// Jeton d'accès courant, ou `null` si aucune session active.
  Future<String?> currentToken() => _store.read();

  /// `true` si une session est active (un jeton est présent).
  Future<bool> isAuthenticated() async => (await _store.read()) != null;

  /// Enregistre le jeton d'accès émis par la connexion.
  Future<void> save(String accessToken) => _store.write(accessToken);

  /// Invalide la session locale (déconnexion, jeton expiré `401`).
  Future<void> clear() => _store.clear();
}
