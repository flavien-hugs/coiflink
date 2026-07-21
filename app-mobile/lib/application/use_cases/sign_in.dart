// Cas d'usage : connexion cliente (réservation client, #22).
//
// Orchestration **pure** (indépendante de Flutter, ADR-0008) : délègue au port
// `AuthGateway` (`POST /auth/login`) et **enregistre** le jeton d'accès dans la
// `AuthSession` en cas de succès. Ni mot de passe ni jeton ne sont **jamais
// journalisés** (§11.1).

import '../auth_session.dart';
import '../ports/auth_gateway.dart';

class SignIn {
  const SignIn(this._gateway, this._session);

  final AuthGateway _gateway;
  final AuthSession _session;

  /// Authentifie `(identifier, password)` puis enregistre le jeton en session.
  ///
  /// Propage [AuthException] (identifiants refusés, réseau, réponse invalide) sans
  /// écrire aucune session en cas d'échec.
  Future<void> call({
    required String identifier,
    required String password,
  }) async {
    final tokens = await _gateway.login(
      identifier: identifier,
      password: password,
    );
    await _session.save(tokens.accessToken);
  }
}
