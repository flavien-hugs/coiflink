// Retry HTTP partagé par les adaptateurs de la borne (US-8.5, #159).
//
// Les routes réservées au rôle KIOSK (#156, #157) partagent la **même** politique :
// POST authentifié par le jeton device, `401` (jeton expiré/révoqué) → une seule
// ré-authentification device puis un unique réessai. Centralisé ici pour ne pas
// dupliquer cette mécanique dans chaque adaptateur — seul le type d'exception levée
// varie d'un port à l'autre, laissé aux callbacks `onUnreachable`/`onReauthFailed`.

import 'package:http/http.dart' as http;

import '../../application/kiosk_device_session.dart';
import '../../application/ports/kiosk_auth_gateway.dart';

/// Exécute un `POST` authentifié avec un unique réessai après ré-authentification
/// device sur `401`. `onUnreachable`/`onReauthFailed` doivent lever l'exception
/// **typée** propre à l'appelant (chaque port a la sienne) — jamais de valeur de
/// retour normale, d'où leur type `Never Function()`.
Future<http.Response> postWithKioskReauth({
  required http.Client client,
  required KioskDeviceSession session,
  required Uri uri,
  required String body,
  required Map<String, String> headers,
  required Never Function() onUnreachable,
  required Never Function() onReauthFailed,
}) async {
  http.Response response;
  try {
    response = await client.post(uri, headers: headers, body: body);
  } catch (_) {
    onUnreachable();
  }

  if (response.statusCode == 401) {
    try {
      await session.reauthenticate();
    } on KioskAuthException {
      onReauthFailed();
    }
    try {
      response = await client.post(uri, headers: headers, body: body);
    } catch (_) {
      onUnreachable();
    }
  }
  return response;
}
