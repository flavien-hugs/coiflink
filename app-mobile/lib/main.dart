// Point d'entrée de l'application CoifLink Borne (US-8.5, #159).
//
// Mode terminal **exclusif** : ce paquet n'a plus qu'un seul point d'entrée, aucun
// `-t`/`--dart-define=APP_MODE` n'est nécessaire — `flutter run`/`flutter build`
// suffisent. Seuls restent injectables au build : `API_BASE_URL`
// (`adapters/data/api_config.dart`) et le credential propre à chaque borne
// provisionnée, `TERMINAL_DEVICE_ID`/`TERMINAL_DEVICE_SECRET`
// (`adapters/data/terminal_config.dart`).
//
//   flutter run \
//     --dart-define=API_BASE_URL=https://api.coiflink.example \
//     --dart-define=TERMINAL_DEVICE_ID=<device_id> \
//     --dart-define=TERMINAL_DEVICE_SECRET=<secret>

import 'package:flutter/material.dart';

import 'adapters/ui/terminal/terminal_app.dart';

void main() {
  runApp(const TerminalApp());
}
