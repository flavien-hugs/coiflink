// Adaptateur data (sortant) : « rejoindre la file » de la borne (US-8.5, #159).
//
// Implémente le port `TerminalQueueGateway` sur `POST /salons/{salon_id}/queue/tickets`
// (#157), réservé au rôle TERMINAL. Le `salon_id` et l'en-tête `Authorization: Bearer`
// proviennent de `TerminalDeviceSession` (jamais d'un jeton personnel) ; un `401` (jeton
// device expiré) déclenche **une** ré-authentification device puis un unique réessai.
//
// #159 ne recalcule rien : il transmet `service_ids` (pluriel, #157) et lit tels
// quels `ticket_number`/`people_ahead_count`. Aucun log d'URL, de jeton ni de PII.

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../application/terminal_device_session.dart';
import '../../application/ports/terminal_queue_gateway.dart';
import 'api_config.dart';
import 'terminal_http_retry.dart';

class HttpTerminalQueueGateway implements TerminalQueueGateway {
  HttpTerminalQueueGateway({
    required this.config,
    required this.session,
    http.Client? client,
  }) : _client = client ?? http.Client();

  final ApiConfig config;
  final TerminalDeviceSession session;
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
      throw const TerminalQueueException();
    }
    return _ticketFrom(response.body);
  }

  Future<http.Response> _send(Uri uri, String body) => postWithTerminalReauth(
        client: _client,
        session: session,
        uri: uri,
        body: body,
        headers: _headers(),
        onUnreachable: () =>
            throw const TerminalQueueException('Impossible de joindre le serveur.'),
        onReauthFailed: () => throw const TerminalQueueException(),
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
        peopleAheadCount: (json['people_ahead_count'] as num).toInt(),
        // `created_at` (#157) → heure **locale** (source de l'`issuedAt` imprimé).
        createdAt: DateTime.parse(json['created_at'] as String).toLocal(),
      );
    } catch (_) {
      throw const TerminalQueueException('Réponse du serveur illisible.');
    }
  }
}
