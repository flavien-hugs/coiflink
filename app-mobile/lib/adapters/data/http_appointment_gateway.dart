// Adapter data (sortant) : disponibilité & réservation HTTP (#22).
//
// Implémente le port `AppointmentGateway` sur les endpoints livrés par #21 :
// `GET /catalog/salons/{id}/availability` (public) et
// `POST /salons/{id}/appointments` (client `APPOINTMENT_BOOK`). Seul cet adapter
// connaît `http` et le format JSON du fil : il mappe JSON → domaine et retraduit
// tout échec en exception **neutre** (jamais de détail de transport au domaine).
//
// Sécurité (§11) : cet adapter ne **journalise jamais** d'URL, de corps, de jeton
// ni de PII. Le corps de réservation n'envoie **jamais** `client_id`/`salon_id`/
// `status` (anti-élévation §11.2) — imposés serveur.

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../application/ports/appointment_gateway.dart';
import '../../domain/appointment/appointment.dart';
import '../../domain/appointment/appointment_status.dart';
import '../../domain/appointment/availability_slot.dart';
import 'api_config.dart';

class HttpAppointmentGateway implements AppointmentGateway {
  HttpAppointmentGateway({required this.config, http.Client? client})
      : _client = client ?? http.Client();

  final ApiConfig config;
  final http.Client _client;

  @override
  Future<List<AvailabilitySlot>> availableSlots({
    required String salonId,
    required DateTime date,
    required String serviceId,
    String? hairdresserId,
  }) async {
    final uri = config.resolve(
      '/catalog/salons/$salonId/availability',
      queryParameters: <String, String>{
        'date': _formatDate(date),
        'service_id': serviceId,
        'hairdresser_id': ?hairdresserId,
      },
    );

    final http.Response response;
    try {
      response = await _client.get(uri);
    } catch (_) {
      throw const AppointmentGatewayException('Impossible de joindre le serveur.');
    }

    if (response.statusCode == 409) {
      throw const NotBookableException();
    }
    if (response.statusCode != 200) {
      // 404 (salon/prestation introuvable) et autres non-2xx → message neutre.
      throw const AppointmentGatewayException(
        'Les créneaux ne sont pas disponibles pour le moment.',
      );
    }

    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final rawSlots = (body['slots'] as List<dynamic>? ?? const <dynamic>[]);
      return rawSlots
          .map((s) => _slotFromJson(s as Map<String, dynamic>))
          .toList(growable: false);
    } catch (_) {
      throw const AppointmentGatewayException('Réponse du serveur illisible.');
    }
  }

  @override
  Future<Appointment> book({
    required String salonId,
    required BookingDraft draft,
    required String accessToken,
  }) async {
    final uri = config.resolve('/salons/$salonId/appointments');
    // Corps **sans** client_id/salon_id/status : imposés serveur (§11.2).
    final payload = <String, dynamic>{
      'date': _formatDate(draft.date),
      'start_time': draft.startTime,
      'service_ids': draft.serviceIds,
      if (draft.hairdresserId != null) 'hairdresser_id': draft.hairdresserId,
      if (draft.clientNote != null && draft.clientNote!.trim().isNotEmpty)
        'client_note': draft.clientNote!.trim(),
    };

    final http.Response response;
    try {
      response = await _client.post(
        uri,
        headers: <String, String>{
          'content-type': 'application/json; charset=utf-8',
          'authorization': 'Bearer $accessToken',
        },
        body: jsonEncode(payload),
      );
    } catch (_) {
      throw const AppointmentGatewayException('Impossible de joindre le serveur.');
    }

    switch (response.statusCode) {
      case 201:
        break;
      case 401:
        throw const UnauthorizedException();
      case 409:
        throw _conflictFromBody(response.body);
      case 404:
        throw const AppointmentGatewayException(
          'Salon ou prestation introuvable.',
        );
      default:
        throw const AppointmentGatewayException(
          'La réservation a échoué, veuillez réessayer.',
        );
    }

    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return _appointmentFromJson(body);
    } catch (_) {
      throw const AppointmentGatewayException('Réponse du serveur illisible.');
    }
  }

  @override
  Future<List<Appointment>> myAppointments({required String accessToken}) async {
    final uri = config.resolve('/appointments');

    final http.Response response;
    try {
      response = await _client.get(
        uri,
        headers: <String, String>{'authorization': 'Bearer $accessToken'},
      );
    } catch (_) {
      throw const AppointmentGatewayException('Impossible de joindre le serveur.');
    }

    switch (response.statusCode) {
      case 200:
        break;
      case 401:
        throw const UnauthorizedException();
      default:
        throw const AppointmentGatewayException(
          'Impossible de charger vos rendez-vous.',
        );
    }

    try {
      final body = jsonDecode(response.body) as List<dynamic>;
      return body
          .map((a) => _appointmentFromJson(a as Map<String, dynamic>))
          .toList(growable: false);
    } catch (_) {
      throw const AppointmentGatewayException('Réponse du serveur illisible.');
    }
  }

  @override
  Future<Appointment> modify({
    required String appointmentId,
    required BookingDraft draft,
    required String accessToken,
  }) async {
    final uri = config.resolve('/appointments/$appointmentId');
    // Corps **sans** client_id/salon_id/status : imposés serveur (§11.2). Le
    // salon_id vient du RDV chargé côté serveur (route d'appartenance).
    final payload = <String, dynamic>{
      'date': _formatDate(draft.date),
      'start_time': draft.startTime,
      'service_ids': draft.serviceIds,
      if (draft.hairdresserId != null) 'hairdresser_id': draft.hairdresserId,
      if (draft.clientNote != null && draft.clientNote!.trim().isNotEmpty)
        'client_note': draft.clientNote!.trim(),
    };

    final http.Response response;
    try {
      response = await _client.patch(
        uri,
        headers: <String, String>{
          'content-type': 'application/json; charset=utf-8',
          'authorization': 'Bearer $accessToken',
        },
        body: jsonEncode(payload),
      );
    } catch (_) {
      throw const AppointmentGatewayException('Impossible de joindre le serveur.');
    }

    switch (response.statusCode) {
      case 200:
        break;
      case 401:
        throw const UnauthorizedException();
      case 409:
        throw _modifyConflictFromBody(response.body);
      case 404:
        throw const AppointmentNotFoundException();
      default:
        throw const AppointmentGatewayException(
          'La modification a échoué, veuillez réessayer.',
        );
    }

    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return _appointmentFromJson(body);
    } catch (_) {
      throw const AppointmentGatewayException('Réponse du serveur illisible.');
    }
  }

  /// Distingue les trois causes de `409` sur une **modification** : RDV verrouillé
  /// (terminé) vs salon non réservable vs créneau déjà pris. On lit le `detail`
  /// **uniquement** pour router vers la bonne exception neutre — jamais pour
  /// l'exposer tel quel (pas de fuite).
  static AppointmentGatewayException _modifyConflictFromBody(String body) {
    String detail = '';
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        detail = (decoded['detail']?.toString() ?? '').toLowerCase();
      }
    } catch (_) {
      // Corps illisible : on retombe sur la distinction créneau/salon ci-dessous.
    }
    // `AppointmentNotModifiable` (§8.1) est le **seul** message parlant de RDV
    // « modifiable » : verrou terminal, rien à re-choisir.
    if (detail.contains('modifiable')) {
      return const NotModifiableException();
    }
    // Sinon, même distinction salon non réservable vs créneau pris que pour `book`.
    return _conflictFromBody(body);
  }

  /// Distingue les deux causes de `409` : créneau déjà pris (course perdue) vs
  /// salon non réservable. On lit le `detail` **uniquement** pour router vers la
  /// bonne exception neutre — jamais pour l'exposer tel quel (pas de fuite).
  static AppointmentGatewayException _conflictFromBody(String body) {
    String detail = '';
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        detail = (decoded['detail']?.toString() ?? '').toLowerCase();
      }
    } catch (_) {
      // Corps illisible : par défaut, on suppose une course perdue sur créneau.
    }
    // Seul `SalonNotBookable` (§8.3) parle du **salon** non réservable : ses
    // messages disent « réserv**a**ble »/« réserv**a**tion », « bookable »,
    // « actif » ou « horaire ». On teste « réserva » (et non « réserv ») pour ne
    // PAS capturer « créneau … réserv**é** » (course perdue `SlotAlreadyBooked`),
    // ni « créneau … réserv… » d'un `SlotUnavailable` : ces deux cas visent le
    // créneau et doivent router vers `SlotTakenException` (retour aux créneaux
    // rafraîchis, §7 / ADR-0024).
    if (detail.contains('réserva') || detail.contains('reserva') ||
        detail.contains('bookable') || detail.contains('actif') ||
        detail.contains('horaire')) {
      return const NotBookableException();
    }
    return const SlotTakenException();
  }

  static AvailabilitySlot _slotFromJson(Map<String, dynamic> json) {
    return AvailabilitySlot(
      date: _parseDate(json['date'] as String),
      start: _trimSeconds(json['start'] as String),
      end: _trimSeconds(json['end'] as String),
    );
  }

  static Appointment _appointmentFromJson(Map<String, dynamic> json) {
    final rawServices =
        (json['services'] as List<dynamic>? ?? const <dynamic>[]);
    return Appointment(
      id: json['id'] as String,
      salonId: json['salon_id'] as String,
      hairdresserId: json['hairdresser_id'] as String?,
      date: _parseDate(json['date'] as String),
      startTime: _trimSeconds(json['start_time'] as String),
      endTime: _trimSeconds(json['end_time'] as String),
      status: AppointmentStatus.fromApi(json['status'] as String?),
      clientNote: json['client_note'] as String?,
      services: rawServices
          .map((s) => _bookedServiceFromJson(s as Map<String, dynamic>))
          .toList(growable: false),
    );
  }

  static BookedService _bookedServiceFromJson(Map<String, dynamic> json) {
    return BookedService(
      serviceId: json['service_id'] as String,
      priceAtBooking: json['price_at_booking']?.toString(),
    );
  }

  /// Formate une date en `YYYY-MM-DD` à partir de ses **composantes locales**
  /// (jamais de conversion UTC : le backend raisonne en Africa/Abidjan UTC+0).
  static String _formatDate(DateTime date) {
    final y = date.year.toString().padLeft(4, '0');
    final m = date.month.toString().padLeft(2, '0');
    final d = date.day.toString().padLeft(2, '0');
    return '$y-$m-$d';
  }

  /// Parse `YYYY-MM-DD` en `DateTime` **local** (composantes de date seules).
  static DateTime _parseDate(String raw) {
    final parts = raw.split('-');
    return DateTime(
      int.parse(parts[0]),
      int.parse(parts[1]),
      int.parse(parts[2]),
    );
  }

  /// Réduit `HH:MM:SS` en `HH:MM` (le backend sérialise un `time` avec secondes).
  static String _trimSeconds(String time) {
    final parts = time.split(':');
    if (parts.length >= 2) {
      return '${parts[0]}:${parts[1]}';
    }
    return time;
  }
}
