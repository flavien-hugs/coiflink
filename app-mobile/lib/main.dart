// Point d'entrée de l'application CoifLink Borne (US-8.5, #159).
//
// Mode kiosque **exclusif** : ce paquet n'a plus qu'un seul point d'entrée, aucun
// `-t`/`--dart-define=APP_MODE` n'est nécessaire — `flutter run`/`flutter build`
// suffisent. Seuls restent injectables au build : `API_BASE_URL`
// (`adapters/data/api_config.dart`) et le credential propre à chaque borne
// provisionnée, `KIOSK_DEVICE_ID`/`KIOSK_DEVICE_SECRET`
// (`adapters/data/kiosk_config.dart`).
//
//   flutter run \
//     --dart-define=API_BASE_URL=https://api.coiflink.example \
//     --dart-define=KIOSK_DEVICE_ID=<device_id> \
//     --dart-define=KIOSK_DEVICE_SECRET=<secret>

import 'package:flutter/material.dart';

import 'adapters/ui/kiosk/kiosk_app.dart';

void main() {
  runApp(const KioskApp());
}
