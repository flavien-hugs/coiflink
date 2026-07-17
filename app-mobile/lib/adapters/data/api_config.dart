// Configuration réseau de l'application mobile (adapter data, #18).
//
// L'URL de base de l'API est **injectée au build** via `--dart-define`
// (`API_BASE_URL`), jamais codée en dur et jamais un secret (spec §Security 7).
// Aucune valeur sensible ne doit transiter par ce fichier ni par l'APK.
//
// Exemples d'injection :
//   flutter run  --dart-define=API_BASE_URL=http://10.0.2.2:8000   // émulateur Android
//   flutter build apk --dart-define=API_BASE_URL=https://api.coiflink.example

/// Configuration de l'accès à l'API backend.
class ApiConfig {
  const ApiConfig({required this.baseUrl});

  /// URL de base de l'API (sans slash final), p. ex. `https://api.coiflink.example`.
  final String baseUrl;

  /// Lit `API_BASE_URL` depuis l'environnement de compilation (`--dart-define`).
  ///
  /// Défaut `http://10.0.2.2:8000` : l'hôte de la machine de dev vu depuis
  /// l'émulateur Android (jamais `localhost`, qui viserait l'émulateur lui-même).
  factory ApiConfig.fromEnvironment() {
    const raw = String.fromEnvironment(
      'API_BASE_URL',
      defaultValue: 'http://10.0.2.2:8000',
    );
    return ApiConfig(baseUrl: _stripTrailingSlash(raw));
  }

  /// Construit l'URI d'un chemin d'API relatif, avec paramètres de requête.
  Uri resolve(String path, {Map<String, String>? queryParameters}) {
    final base = Uri.parse(baseUrl);
    final normalizedPath = path.startsWith('/') ? path : '/$path';
    final params = <String, String>{...?queryParameters};
    return base.replace(
      path: '${_stripTrailingSlash(base.path)}$normalizedPath',
      queryParameters: params.isEmpty ? null : params,
    );
  }

  static String _stripTrailingSlash(String value) {
    return value.endsWith('/')
        ? value.substring(0, value.length - 1)
        : value;
  }
}
