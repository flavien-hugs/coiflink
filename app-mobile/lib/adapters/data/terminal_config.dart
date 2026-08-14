// Configuration de la borne (adapter data, US-8.5, #159).
//
// Un seul indicateur de compilation, lu via `--dart-define` (patron `ApiConfig`,
// `api_config.dart:18-28`) :
//
//   flutter run --dart-define=API_BASE_URL=https://api.coiflink.example
//
// `TERMINAL_SALON_ID` : **override de développement local uniquement**. En
// production, le `salon_id` de la borne provient de la réponse du login (#155),
// obtenu après activation par code à 6 chiffres (`TerminalActivationGateway`) — un
// APK unique pour toutes les bornes, aucune valeur de salon ni credential compilé
// en dur. Cette valeur ne sert qu'à lancer l'app sur un poste de dev sans borne
// activée ; elle est ignorée dès qu'un credential device est stocké localement.
class TerminalConfig {
  const TerminalConfig._();

  /// Override de développement local du `salon_id` (voir en-tête). Vide en
  /// production : la borne apprend son salon via l'activation puis le login (#155).
  static const String devSalonIdOverride =
      String.fromEnvironment('TERMINAL_SALON_ID');

  /// `salon_id` d'override s'il est fourni en dev, sinon `null` (cas de production).
  static String? get devSalonId =>
      devSalonIdOverride.isEmpty ? null : devSalonIdOverride;
}
