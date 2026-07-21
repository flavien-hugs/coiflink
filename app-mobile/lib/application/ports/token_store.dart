// Port (interface) de stockage du jeton d'accès — application, #22.
//
// Abstraction du **magasin** où vit le jeton de session : la production vise un
// magasin **sécurisé** de plateforme (Keychain/Keystore, p. ex.
// `flutter_secure_storage`) ; le MVP #22 fournit une implémentation **en mémoire**
// (session perdue au redémarrage) pour rester testable sans plugin natif — voir
// ADR-0024. Le jeton n'est **jamais journalisé** (§11.1).

/// Magasin du jeton d'accès de la session cliente.
///
/// Implémentation injectable (ADR-0008) : un `HttpAppointmentGateway` ne connaît
/// pas ce port ; c'est la session/UI qui lit le jeton et le passe à `book`.
abstract class TokenStore {
  /// Retourne le jeton d'accès mémorisé, ou `null` si aucune session.
  Future<String?> read();

  /// Mémorise le jeton d'accès de la session courante.
  Future<void> write(String token);

  /// Efface le jeton mémorisé (déconnexion, `401`).
  Future<void> clear();
}

/// Implémentation **en mémoire** du [TokenStore] (MVP #22).
///
/// Le jeton ne survit pas au redémarrage de l'application. La bascule vers un
/// magasin sécurisé de plateforme est un simple remplacement d'implémentation
/// (aucun autre code ne dépend de la nature du magasin) — voir ADR-0024.
class InMemoryTokenStore implements TokenStore {
  String? _token;

  @override
  Future<String?> read() async => _token;

  @override
  Future<void> write(String token) async => _token = token;

  @override
  Future<void> clear() async => _token = null;
}
