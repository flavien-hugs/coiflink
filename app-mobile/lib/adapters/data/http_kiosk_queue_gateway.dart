// Adaptateur data (sortant) : « rejoindre la file » de la borne (US-8.5, #159).
//
// Implémente le port `KioskQueueGateway` sur `POST /salons/{salon_id}/queue/tickets`
// (#157), réservé au rôle KIOSK. Le `salon_id` et l'en-tête `Authorization: Bearer`
// proviennent de `KioskDeviceSession` (jamais d'un jeton personnel) ; un `401` (jeton
// device expiré) déclenche **une** ré-authentification device puis un unique réessai.
//
// #159 ne recalcule rien : il transmet `service_ids` (pluriel, #157) et lit tels
// quels `ticket_number`/`estimated_wait_minutes`. Aucun log d'URL, de jeton ni de PII.

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../application/kiosk_device_session.dart';
import '../../application/ports/kiosk_queue_gateway.dart';
import 'api_config.dart';
import 'kiosk_http_retry.dart';

class HttpKioskQueueGateway implements KioskQueueGateway {
  HttpKioskQueueGateway({
    required this.config,
    required this.session,
    http.Client? client,
  }) : _client = client ?? http.Client();

  final ApiConfig config;
  final KioskDeviceSession session;
  final http.Client _client;

  @override
  Future<QueueTicket> joinQueue({
    String? customerProfileId,
    required List<String> serviceIds,
  }) async {
    final uri = config.resolve('/salons/${session.salonId}/queue/tickets');
    final body = jsonEncode(<String, dynamic>{
      'customer_profile_id': ?customerProfileId,
      'service_ids': serviceIds,
    });

    final response = await _send(uri, body);
    if (response.statusCode != 201) {
      throw const KioskQueueException();
    }
    return _ticketFrom(response.body);
  }

  Future<http.Response> _send(Uri uri, String body) => postWithKioskReauth(
        client: _client,
        session: session,
        uri: uri,
        body: body,
        headers: _headers(),
        onUnreachable: () =>
            throw const KioskQueueException('Impossible de joindre le serveur.'),
        onReauthFailed: () => throw const KioskQueueException(),
      );

  Map<String, String> _headers() => <String, String>{
        'content-type': 'application/json; charset=utf-8',
        ...session.authorizationHeaders(),
      };

  static QueueTicket _ticketFrom(String body) {
    try {
      final json = jsonDecode(body) as Map<String, dynamic>;
      return QueueTicket(
        id: json['id'] as String,
        ticketNumber: (json['ticket_number'] as num).toInt(),
        estimatedWaitMinutes: (json['estimated_wait_minutes'] as num).toInt(),
        // `created_at` (#157) → heure **locale** (source de l'`issuedAt` imprimé).
        createdAt: DateTime.parse(json['created_at'] as String).toLocal(),
      );
    } catch (_) {
      throw const KioskQueueException('Réponse du serveur illisible.');
    }
  }
}
