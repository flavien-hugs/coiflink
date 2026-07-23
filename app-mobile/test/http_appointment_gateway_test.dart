// Tests unitaires — HttpAppointmentGateway : mapping HTTP → domaine (#22).
//
// Couverture : availableSlots mappe slots[] → AvailabilitySlot (trims secondes,
// hairdresserId optionnel) ; book envoie Authorization, omet client_id/salon_id/
// status (anti-élévation §11.2), mappe 201/401/409/404/réseau → types domaine ;
// 409 disambiguïté (SlotTaken vs NotBookable) ; messages d'erreur neutres (§11).
// Aucun réseau réel : faux BaseClient intercepte toutes les requêtes.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:coiflink_mobile/adapters/data/api_config.dart';
import 'package:coiflink_mobile/adapters/data/http_appointment_gateway.dart';
import 'package:coiflink_mobile/application/ports/appointment_gateway.dart';
import 'package:coiflink_mobile/domain/appointment/appointment_status.dart';

// ---------------------------------------------------------------------------
// Faux clients HTTP
// ---------------------------------------------------------------------------

class _FakeHttpClient extends http.BaseClient {
  _FakeHttpClient({required this.statusCode, required this.body});

  final int statusCode;
  final String body;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    return http.StreamedResponse(
      Stream.value(utf8.encode(body)),
      statusCode,
      headers: const {'content-type': 'application/json; charset=utf-8'},
    );
  }
}

class _NetworkFailClient extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    throw Exception('Network down');
  }
}

/// Client capturant la requête sortante (URL, en-têtes, corps).
class _CapturingClient extends http.BaseClient {
  _CapturingClient({required this.statusCode, required this.body});

  final int statusCode;
  final String body;

  http.BaseRequest? lastRequest;
  String? lastBody;
  Map<String, String>? lastHeaders;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    lastRequest = request;
    lastHeaders = Map<String, String>.unmodifiable(request.headers);
    if (request is http.Request) {
      lastBody = request.body;
    }
    return http.StreamedResponse(
      Stream.value(utf8.encode(body)),
      statusCode,
      headers: const {'content-type': 'application/json; charset=utf-8'},
    );
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

ApiConfig _config() => const ApiConfig(baseUrl: 'http://test.local');

HttpAppointmentGateway _gateway(http.Client client) =>
    HttpAppointmentGateway(config: _config(), client: client);

Map<String, dynamic> _slotJson({
  String date = '2026-07-21',
  String start = '09:00:00',
  String end = '09:30:00',
}) =>
    {'date': date, 'start': start, 'end': end};

String _availabilityBody({List<Map<String, dynamic>>? slots}) =>
    jsonEncode({'slots': slots ?? <Map<String, dynamic>>[]});

Map<String, dynamic> _appointmentJsonFull({
  String id = 'rdv-1',
  String salonId = 'salon-1',
  String? hairdresserId,
  String date = '2026-07-21',
  String startTime = '09:00:00',
  String endTime = '09:30:00',
  String status = 'PENDING',
  String? clientNote,
  List<Map<String, dynamic>>? services,
}) =>
    {
      'id': id,
      'salon_id': salonId,
      'hairdresser_id': hairdresserId,
      'date': date,
      'start_time': startTime,
      'end_time': endTime,
      'status': status,
      'client_note': clientNote,
      'services': services ??
          [
            {'service_id': 'svc-1', 'price_at_booking': '5000.00'},
          ],
    };

BookingDraft _draft({
  List<String> serviceIds = const ['svc-1'],
  String? clientNote,
  String? hairdresserId,
}) =>
    BookingDraft(
      date: DateTime(2026, 7, 21),
      startTime: '09:00',
      serviceIds: serviceIds,
      clientNote: clientNote,
      hairdresserId: hairdresserId,
    );

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('HttpAppointmentGateway', () {
    // -----------------------------------------------------------------------
    // availableSlots
    // -----------------------------------------------------------------------
    group('availableSlots', () {
      group('mapping JSON → AvailabilitySlot', () {
        test('mappe un créneau complet (date, start, end)', () async {
          final client = _FakeHttpClient(
            statusCode: 200,
            body: _availabilityBody(slots: [
              _slotJson(
                date: '2026-07-21',
                start: '09:00:00',
                end: '09:30:00',
              ),
            ]),
          );

          final slots = await _gateway(client).availableSlots(
            salonId: 'salon-1',
            date: DateTime(2026, 7, 21),
            serviceId: 'svc-1',
          );

          expect(slots, hasLength(1));
          final s = slots.first;
          expect(s.start, '09:00');
          expect(s.end, '09:30');
          expect(s.date.year, 2026);
          expect(s.date.month, 7);
          expect(s.date.day, 21);
        });

        test('tronque les secondes HH:MM:SS → HH:MM', () async {
          final client = _FakeHttpClient(
            statusCode: 200,
            body: _availabilityBody(slots: [
              _slotJson(start: '14:30:00', end: '15:00:00'),
            ]),
          );

          final slots = await _gateway(client).availableSlots(
            salonId: 'salon-1',
            date: DateTime(2026, 7, 21),
            serviceId: 'svc-1',
          );

          expect(slots.first.start, '14:30');
          expect(slots.first.end, '15:00');
        });

        test('heure sans secondes HH:MM conservée telle quelle', () async {
          final client = _FakeHttpClient(
            statusCode: 200,
            body: _availabilityBody(slots: [
              _slotJson(start: '10:00', end: '10:30'),
            ]),
          );

          final slots = await _gateway(client).availableSlots(
            salonId: 'salon-1',
            date: DateTime(2026, 7, 21),
            serviceId: 'svc-1',
          );

          expect(slots.first.start, '10:00');
          expect(slots.first.end, '10:30');
        });

        test('plusieurs créneaux → liste complète dans l\'ordre', () async {
          final client = _FakeHttpClient(
            statusCode: 200,
            body: _availabilityBody(slots: [
              _slotJson(start: '09:00:00', end: '09:30:00'),
              _slotJson(start: '10:00:00', end: '10:30:00'),
              _slotJson(start: '11:00:00', end: '11:30:00'),
            ]),
          );

          final slots = await _gateway(client).availableSlots(
            salonId: 'salon-1',
            date: DateTime(2026, 7, 21),
            serviceId: 'svc-1',
          );

          expect(slots, hasLength(3));
          expect(slots[0].start, '09:00');
          expect(slots[1].start, '10:00');
          expect(slots[2].start, '11:00');
        });

        test('slots absent du JSON → liste vide (aucun créneau)', () async {
          final client = _FakeHttpClient(
            statusCode: 200,
            body: jsonEncode(<String, dynamic>{}),
          );

          final slots = await _gateway(client).availableSlots(
            salonId: 'salon-1',
            date: DateTime(2026, 7, 21),
            serviceId: 'svc-1',
          );

          expect(slots, isEmpty);
        });

        test('slots vide [] → liste vide', () async {
          final client = _FakeHttpClient(
            statusCode: 200,
            body: _availabilityBody(),
          );

          final slots = await _gateway(client).availableSlots(
            salonId: 'salon-1',
            date: DateTime(2026, 7, 21),
            serviceId: 'svc-1',
          );

          expect(slots, isEmpty);
        });
      });

      group('paramètres de requête', () {
        test('salonId, date et serviceId transmis dans l\'URL', () async {
          final capturing = _CapturingClient(
            statusCode: 200,
            body: _availabilityBody(),
          );

          await _gateway(capturing).availableSlots(
            salonId: 'salon-abc',
            date: DateTime(2026, 7, 21),
            serviceId: 'svc-xyz',
          );

          final url = capturing.lastRequest!.url;
          expect(url.path, contains('salon-abc'));
          expect(url.queryParameters['date'], '2026-07-21');
          expect(url.queryParameters['service_id'], 'svc-xyz');
        });

        test('hairdresserId fourni → transmis dans l\'URL', () async {
          final capturing = _CapturingClient(
            statusCode: 200,
            body: _availabilityBody(),
          );

          await _gateway(capturing).availableSlots(
            salonId: 'salon-1',
            date: DateTime(2026, 7, 21),
            serviceId: 'svc-1',
            hairdresserId: 'hair-42',
          );

          expect(
            capturing.lastRequest!.url.queryParameters['hairdresser_id'],
            'hair-42',
          );
        });

        test('hairdresserId null → absent de l\'URL', () async {
          final capturing = _CapturingClient(
            statusCode: 200,
            body: _availabilityBody(),
          );

          await _gateway(capturing).availableSlots(
            salonId: 'salon-1',
            date: DateTime(2026, 7, 21),
            serviceId: 'svc-1',
          );

          expect(
            capturing.lastRequest!.url.queryParameters
                .containsKey('hairdresser_id'),
            isFalse,
          );
        });

        test('date formatée YYYY-MM-DD (UTC+0)', () async {
          final capturing = _CapturingClient(
            statusCode: 200,
            body: _availabilityBody(),
          );

          await _gateway(capturing).availableSlots(
            salonId: 's',
            date: DateTime(2026, 1, 5),
            serviceId: 'svc',
          );

          expect(
            capturing.lastRequest!.url.queryParameters['date'],
            '2026-01-05',
          );
        });
      });

      group('gestion des erreurs HTTP et réseau', () {
        test('409 → NotBookableException (salon non réservable)', () async {
          final client = _FakeHttpClient(
            statusCode: 409,
            body: '{"detail": "Salon not bookable"}',
          );

          await expectLater(
            _gateway(client).availableSlots(
              salonId: 'salon-1',
              date: DateTime(2026, 7, 21),
              serviceId: 'svc-1',
            ),
            throwsA(isA<NotBookableException>()),
          );
        });

        test('404 → AppointmentGatewayException (message neutre)', () async {
          final client = _FakeHttpClient(
            statusCode: 404,
            body: '{"detail": "Salon introuvable."}',
          );

          await expectLater(
            _gateway(client).availableSlots(
              salonId: 'salon-1',
              date: DateTime(2026, 7, 21),
              serviceId: 'svc-1',
            ),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('500 → AppointmentGatewayException (message neutre)', () async {
          final client = _FakeHttpClient(statusCode: 500, body: '');

          await expectLater(
            _gateway(client).availableSlots(
              salonId: 'salon-1',
              date: DateTime(2026, 7, 21),
              serviceId: 'svc-1',
            ),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('panne réseau → AppointmentGatewayException', () async {
          await expectLater(
            _gateway(_NetworkFailClient()).availableSlots(
              salonId: 'salon-1',
              date: DateTime(2026, 7, 21),
              serviceId: 'svc-1',
            ),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('corps JSON illisible sur 200 → AppointmentGatewayException',
            () async {
          final client =
              _FakeHttpClient(statusCode: 200, body: 'invalid-json-{{');

          await expectLater(
            _gateway(client).availableSlots(
              salonId: 'salon-1',
              date: DateTime(2026, 7, 21),
              serviceId: 'svc-1',
            ),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('message d\'erreur ne contient pas l\'URL ni de PII', () async {
          final client = _FakeHttpClient(statusCode: 500, body: '');

          Object? caught;
          try {
            await _gateway(client).availableSlots(
              salonId: 'salon-secret',
              date: DateTime(2026, 7, 21),
              serviceId: 'svc-1',
            );
          } catch (e) {
            caught = e;
          }

          expect(caught, isA<AppointmentGatewayException>());
          final msg = (caught as AppointmentGatewayException).message;
          expect(msg.contains('test.local'), isFalse);
          expect(msg.contains('salon-secret'), isFalse);
        });
      });
    });

    // -----------------------------------------------------------------------
    // book
    // -----------------------------------------------------------------------
    group('book', () {
      group('mapping 201 → Appointment', () {
        test('mappe tous les champs d\'une réponse complète', () async {
          final client = _FakeHttpClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull(
              id: 'rdv-42',
              salonId: 'salon-9',
              hairdresserId: 'hair-3',
              date: '2026-07-21',
              startTime: '09:00:00',
              endTime: '09:30:00',
              status: 'PENDING',
              clientNote: 'Coupe courte',
              services: [
                {'service_id': 'svc-1', 'price_at_booking': '5000.00'},
              ],
            )),
          );

          final appt = await _gateway(client).book(
            salonId: 'salon-9',
            draft: _draft(),
            accessToken: 'tok-abc',
          );

          expect(appt.id, 'rdv-42');
          expect(appt.salonId, 'salon-9');
          expect(appt.hairdresserId, 'hair-3');
          expect(appt.date.year, 2026);
          expect(appt.date.month, 7);
          expect(appt.date.day, 21);
          expect(appt.startTime, '09:00');
          expect(appt.endTime, '09:30');
          expect(appt.status, AppointmentStatus.pending);
          expect(appt.clientNote, 'Coupe courte');
          expect(appt.services, hasLength(1));
          expect(appt.services.first.serviceId, 'svc-1');
          expect(appt.services.first.priceAtBooking, '5000.00');
        });

        test('statut de la réponse est PENDING (critère d\'acceptation #22)',
            () async {
          final client = _FakeHttpClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull(status: 'PENDING')),
          );

          final appt = await _gateway(client).book(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'tok',
          );

          expect(appt.status, AppointmentStatus.pending);
          expect(appt.status.label, 'En attente');
        });

        test('tronque les secondes de start_time et end_time', () async {
          final client = _FakeHttpClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull(
              startTime: '10:00:00',
              endTime: '10:30:00',
            )),
          );

          final appt = await _gateway(client).book(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'tok',
          );

          expect(appt.startTime, '10:00');
          expect(appt.endTime, '10:30');
        });

        test('hairdresserId null dans la réponse → null dans l\'Appointment',
            () async {
          final client = _FakeHttpClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull(hairdresserId: null)),
          );

          final appt = await _gateway(client).book(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'tok',
          );

          expect(appt.hairdresserId, isNull);
        });

        test('services vide → liste vide dans l\'Appointment', () async {
          final client = _FakeHttpClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull(services: [])),
          );

          final appt = await _gateway(client).book(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'tok',
          );

          expect(appt.services, isEmpty);
        });
      });

      group('en-tête Authorization et corps de requête', () {
        test('envoie l\'en-tête Authorization: Bearer <token>', () async {
          final capturing = _CapturingClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).book(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'test-access-token',
          );

          final authHeader = capturing.lastHeaders?['authorization'];
          expect(authHeader, isNotNull);
          expect(authHeader, 'Bearer test-access-token');
        });

        test('corps contient date, start_time et service_ids', () async {
          final capturing = _CapturingClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).book(
            salonId: 'salon-1',
            draft: _draft(serviceIds: const ['svc-1', 'svc-2']),
            accessToken: 'tok',
          );

          final body = jsonDecode(capturing.lastBody!) as Map<String, dynamic>;
          expect(body['date'], '2026-07-21');
          expect(body['start_time'], '09:00');
          expect(body['service_ids'], ['svc-1', 'svc-2']);
        });

        test(
            'corps n\'inclut JAMAIS client_id, salon_id ni status '
            '(anti-élévation §11.2)', () async {
          final capturing = _CapturingClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).book(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'tok',
          );

          final body = jsonDecode(capturing.lastBody!) as Map<String, dynamic>;
          expect(body.containsKey('client_id'), isFalse);
          expect(body.containsKey('salon_id'), isFalse);
          expect(body.containsKey('status'), isFalse);
        });

        test('hairdresserId fourni → inclus dans le corps', () async {
          final capturing = _CapturingClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).book(
            salonId: 'salon-1',
            draft: _draft(hairdresserId: 'hair-7'),
            accessToken: 'tok',
          );

          final body = jsonDecode(capturing.lastBody!) as Map<String, dynamic>;
          expect(body['hairdresser_id'], 'hair-7');
        });

        test('hairdresserId null → absent du corps', () async {
          final capturing = _CapturingClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).book(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'tok',
          );

          final body = jsonDecode(capturing.lastBody!) as Map<String, dynamic>;
          expect(body.containsKey('hairdresser_id'), isFalse);
        });

        test('clientNote non vide → inclus dans le corps (trimmed)', () async {
          final capturing = _CapturingClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).book(
            salonId: 'salon-1',
            draft: _draft(clientNote: '  Coupe courte  '),
            accessToken: 'tok',
          );

          final body = jsonDecode(capturing.lastBody!) as Map<String, dynamic>;
          expect(body['client_note'], 'Coupe courte');
        });

        test('clientNote vide après trim → absent du corps', () async {
          final capturing = _CapturingClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).book(
            salonId: 'salon-1',
            draft: _draft(clientNote: '   '),
            accessToken: 'tok',
          );

          final body = jsonDecode(capturing.lastBody!) as Map<String, dynamic>;
          expect(body.containsKey('client_note'), isFalse);
        });

        test('clientNote null → absent du corps', () async {
          final capturing = _CapturingClient(
            statusCode: 201,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).book(
            salonId: 'salon-1',
            draft: _draft(),
            accessToken: 'tok',
          );

          final body = jsonDecode(capturing.lastBody!) as Map<String, dynamic>;
          expect(body.containsKey('client_note'), isFalse);
        });
      });

      group('gestion des erreurs HTTP', () {
        test('401 → UnauthorizedException (§11.1)', () async {
          final client = _FakeHttpClient(
            statusCode: 401,
            body: '{"detail": "Non authentifié."}',
          );

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'expired-tok',
            ),
            throwsA(isA<UnauthorizedException>()),
          );
        });

        test(
            '409 avec detail "not bookable" → NotBookableException (§8.3)',
            () async {
          final client = _FakeHttpClient(
            statusCode: 409,
            body: '{"detail": "salon not bookable"}',
          );

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<NotBookableException>()),
          );
        });

        test(
            '409 avec detail "réservable" (français) → NotBookableException',
            () async {
          final client = _FakeHttpClient(
            statusCode: 409,
            body: '{"detail": "ce salon n\'est pas réservable"}',
          );

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<NotBookableException>()),
          );
        });

        test(
            '409 message exact backend SalonNotBookable → NotBookableException',
            () async {
          // Chaîne exacte levée par le backend (application/appointments.py).
          final client = _FakeHttpClient(
            statusCode: 409,
            body: jsonEncode(<String, String>{
              'detail': "Ce salon n'accepte pas encore de réservation.",
            }),
          );

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<NotBookableException>()),
          );
        });

        test(
            '409 avec detail "horaire" → NotBookableException',
            () async {
          final client = _FakeHttpClient(
            statusCode: 409,
            body: '{"detail": "pas d\'horaire configuré"}',
          );

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<NotBookableException>()),
          );
        });

        test(
            '409 avec detail créneau pris → SlotTakenException (§8.1)',
            () async {
          final client = _FakeHttpClient(
            statusCode: 409,
            body: '{"detail": "slot already taken"}',
          );

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<SlotTakenException>()),
          );
        });

        test(
            '409 message exact backend SlotAlreadyBooked (course perdue) → '
            'SlotTakenException (§8.1) — « réservé » ne doit PAS router '
            'vers NotBookable',
            () async {
          // Chaîne exacte levée par le backend sur perte de course
          // (persistence/appointment_repository.py). Le mot « réservé »
          // partage le préfixe « réserv » avec « réservable/réservation » du
          // cas salon non réservable : la disambiguïté doit renvoyer le
          // client vers les créneaux rafraîchis, pas vers « non réservable ».
          final client = _FakeHttpClient(
            statusCode: 409,
            body: jsonEncode(<String, String>{
              'detail': "Ce créneau vient d'être réservé pour ce coiffeur.",
            }),
          );

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<SlotTakenException>()),
          );
        });

        test(
            '409 message exact backend SlotUnavailable → SlotTakenException',
            () async {
          // Chaîne exacte levée par le backend (application/appointments.py) :
          // créneau visé hors offre → retour aux créneaux rafraîchis.
          final client = _FakeHttpClient(
            statusCode: 409,
            body: jsonEncode(<String, String>{
              'detail': "Le créneau demandé n'est pas disponible.",
            }),
          );

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<SlotTakenException>()),
          );
        });

        test(
            '409 corps JSON illisible → SlotTakenException par défaut',
            () async {
          final client =
              _FakeHttpClient(statusCode: 409, body: 'invalid-json');

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<SlotTakenException>()),
          );
        });

        test('409 corps vide → SlotTakenException par défaut', () async {
          final client = _FakeHttpClient(statusCode: 409, body: '');

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<SlotTakenException>()),
          );
        });

        test('404 → AppointmentGatewayException (message neutre)', () async {
          final client = _FakeHttpClient(
            statusCode: 404,
            body: '{"detail": "Salon introuvable."}',
          );

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('500 → AppointmentGatewayException (message neutre)', () async {
          final client = _FakeHttpClient(statusCode: 500, body: '');

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('panne réseau → AppointmentGatewayException', () async {
          await expectLater(
            _gateway(_NetworkFailClient()).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('corps JSON illisible sur 201 → AppointmentGatewayException',
            () async {
          final client =
              _FakeHttpClient(statusCode: 201, body: 'not-valid-json');

          await expectLater(
            _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });
      });

      group('confidentialité des messages d\'erreur (§11)', () {
        test('UnauthorizedException ne contient pas le jeton', () async {
          final client = _FakeHttpClient(statusCode: 401, body: '{}');

          Object? caught;
          try {
            await _gateway(client).book(
              salonId: 'salon-1',
              draft: _draft(),
              accessToken: 'super-secret-token-xyz',
            );
          } catch (e) {
            caught = e;
          }

          expect(caught, isA<UnauthorizedException>());
          final msg = (caught as UnauthorizedException).message;
          expect(msg.contains('super-secret-token-xyz'), isFalse);
        });

        test(
            'AppointmentGatewayException ne contient pas l\'URL ni le salonId',
            () async {
          final client = _FakeHttpClient(statusCode: 500, body: '');

          Object? caught;
          try {
            await _gateway(client).book(
              salonId: 'salon-confidentiel',
              draft: _draft(),
              accessToken: 'tok',
            );
          } catch (e) {
            caught = e;
          }

          expect(caught, isA<AppointmentGatewayException>());
          final msg = (caught as AppointmentGatewayException).message;
          expect(msg.contains('test.local'), isFalse);
          expect(msg.contains('salon-confidentiel'), isFalse);
        });

        test('SlotTakenException ne contient pas le jeton ni le salonId',
            () async {
          final client =
              _FakeHttpClient(statusCode: 409, body: '{"detail": "taken"}');

          Object? caught;
          try {
            await _gateway(client).book(
              salonId: 'salon-prive',
              draft: _draft(),
              accessToken: 'tok-secret',
            );
          } catch (e) {
            caught = e;
          }

          expect(caught, isA<SlotTakenException>());
          final msg = (caught as SlotTakenException).message;
          expect(msg.contains('tok-secret'), isFalse);
          expect(msg.contains('salon-prive'), isFalse);
        });
      });
    });

    // -----------------------------------------------------------------------
    // myAppointments
    // -----------------------------------------------------------------------
    group('myAppointments', () {
      group('URL et en-tête', () {
        test('envoie GET /appointments avec Authorization: Bearer', () async {
          final capturing = _CapturingClient(
            statusCode: 200,
            body: jsonEncode(<dynamic>[_appointmentJsonFull()]),
          );

          await _gateway(capturing).myAppointments(
            accessToken: 'test-token-abc',
          );

          final url = capturing.lastRequest!.url;
          expect(url.path, endsWith('/appointments'));
          expect(capturing.lastRequest!.method, 'GET');
          final auth = capturing.lastHeaders?['authorization'];
          expect(auth, 'Bearer test-token-abc');
        });
      });

      group('mapping 200 → List<Appointment>', () {
        test('liste vide → liste vide', () async {
          final client = _FakeHttpClient(
            statusCode: 200,
            body: jsonEncode(<dynamic>[]),
          );

          final result = await _gateway(client).myAppointments(
            accessToken: 'tok',
          );

          expect(result, isEmpty);
        });

        test('un rendez-vous → liste à un élément', () async {
          final client = _FakeHttpClient(
            statusCode: 200,
            body: jsonEncode(<dynamic>[
              _appointmentJsonFull(id: 'rdv-10', status: 'PENDING'),
            ]),
          );

          final result = await _gateway(client).myAppointments(
            accessToken: 'tok',
          );

          expect(result, hasLength(1));
          expect(result.first.id, 'rdv-10');
        });

        test('plusieurs rendez-vous → liste complète dans l\'ordre', () async {
          final client = _FakeHttpClient(
            statusCode: 200,
            body: jsonEncode(<dynamic>[
              _appointmentJsonFull(id: 'rdv-1'),
              _appointmentJsonFull(id: 'rdv-2'),
            ]),
          );

          final result = await _gateway(client).myAppointments(
            accessToken: 'tok',
          );

          expect(result, hasLength(2));
          expect(result[0].id, 'rdv-1');
          expect(result[1].id, 'rdv-2');
        });
      });

      group('gestion des erreurs', () {
        test('401 → UnauthorizedException', () async {
          final client = _FakeHttpClient(statusCode: 401, body: '{}');

          await expectLater(
            _gateway(client).myAppointments(accessToken: 'expired'),
            throwsA(isA<UnauthorizedException>()),
          );
        });

        test('500 → AppointmentGatewayException', () async {
          final client = _FakeHttpClient(statusCode: 500, body: '');

          await expectLater(
            _gateway(client).myAppointments(accessToken: 'tok'),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('panne réseau → AppointmentGatewayException', () async {
          await expectLater(
            _gateway(_NetworkFailClient()).myAppointments(accessToken: 'tok'),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('corps JSON illisible → AppointmentGatewayException', () async {
          final client =
              _FakeHttpClient(statusCode: 200, body: 'not-valid-json');

          await expectLater(
            _gateway(client).myAppointments(accessToken: 'tok'),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('UnauthorizedException ne contient pas le jeton', () async {
          final client = _FakeHttpClient(statusCode: 401, body: '{}');

          Object? caught;
          try {
            await _gateway(client).myAppointments(
              accessToken: 'secret-refresh-xyz',
            );
          } catch (e) {
            caught = e;
          }

          expect(caught, isA<UnauthorizedException>());
          final msg = (caught as UnauthorizedException).message;
          expect(msg.contains('secret-refresh-xyz'), isFalse);
        });
      });
    });

    // -----------------------------------------------------------------------
    // modify
    // -----------------------------------------------------------------------
    group('modify', () {
      group('URL, méthode et en-tête', () {
        test('envoie PATCH /appointments/{id} avec Authorization: Bearer',
            () async {
          final capturing = _CapturingClient(
            statusCode: 200,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).modify(
            appointmentId: 'rdv-42',
            draft: _draft(),
            accessToken: 'test-tok-xyz',
          );

          final url = capturing.lastRequest!.url;
          expect(url.path, endsWith('/appointments/rdv-42'));
          expect(capturing.lastRequest!.method, 'PATCH');
          final auth = capturing.lastHeaders?['authorization'];
          expect(auth, 'Bearer test-tok-xyz');
        });
      });

      group('corps de requête (anti-élévation §11.2)', () {
        test('corps contient date, start_time et service_ids', () async {
          final capturing = _CapturingClient(
            statusCode: 200,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).modify(
            appointmentId: 'rdv-1',
            draft: _draft(serviceIds: const ['svc-a', 'svc-b']),
            accessToken: 'tok',
          );

          final body =
              jsonDecode(capturing.lastBody!) as Map<String, dynamic>;
          expect(body['date'], '2026-07-21');
          expect(body['start_time'], '09:00');
          expect(body['service_ids'], ['svc-a', 'svc-b']);
        });

        test('corps n\'inclut JAMAIS client_id, salon_id ni status', () async {
          final capturing = _CapturingClient(
            statusCode: 200,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).modify(
            appointmentId: 'rdv-1',
            draft: _draft(),
            accessToken: 'tok',
          );

          final body =
              jsonDecode(capturing.lastBody!) as Map<String, dynamic>;
          expect(body.containsKey('client_id'), isFalse);
          expect(body.containsKey('salon_id'), isFalse);
          expect(body.containsKey('status'), isFalse);
        });

        test('hairdresserId fourni → inclus dans le corps', () async {
          final capturing = _CapturingClient(
            statusCode: 200,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).modify(
            appointmentId: 'rdv-1',
            draft: _draft(hairdresserId: 'hair-9'),
            accessToken: 'tok',
          );

          final body =
              jsonDecode(capturing.lastBody!) as Map<String, dynamic>;
          expect(body['hairdresser_id'], 'hair-9');
        });

        test('hairdresserId null → absent du corps', () async {
          final capturing = _CapturingClient(
            statusCode: 200,
            body: jsonEncode(_appointmentJsonFull()),
          );

          await _gateway(capturing).modify(
            appointmentId: 'rdv-1',
            draft: _draft(),
            accessToken: 'tok',
          );

          final body =
              jsonDecode(capturing.lastBody!) as Map<String, dynamic>;
          expect(body.containsKey('hairdresser_id'), isFalse);
        });
      });

      group('mapping 200 → Appointment', () {
        test('mappe tous les champs d\'une réponse complète', () async {
          final client = _FakeHttpClient(
            statusCode: 200,
            body: jsonEncode(_appointmentJsonFull(
              id: 'rdv-99',
              status: 'CONFIRMED',
              hairdresserId: 'hair-5',
            )),
          );

          final appt = await _gateway(client).modify(
            appointmentId: 'rdv-99',
            draft: _draft(),
            accessToken: 'tok',
          );

          expect(appt.id, 'rdv-99');
          expect(appt.hairdresserId, 'hair-5');
          expect(appt.status, AppointmentStatus.confirmed);
        });
      });

      group('gestion des erreurs HTTP', () {
        test('401 → UnauthorizedException', () async {
          final client = _FakeHttpClient(statusCode: 401, body: '{}');

          await expectLater(
            _gateway(client).modify(
              appointmentId: 'rdv-1',
              draft: _draft(),
              accessToken: 'expired',
            ),
            throwsA(isA<UnauthorizedException>()),
          );
        });

        test('404 → AppointmentNotFoundException', () async {
          final client = _FakeHttpClient(
            statusCode: 404,
            body: '{"detail": "Introuvable."}',
          );

          await expectLater(
            _gateway(client).modify(
              appointmentId: 'rdv-inconnu',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<AppointmentNotFoundException>()),
          );
        });

        test(
            '409 "modifiable" → NotModifiableException (RDV terminé, §8.1)',
            () async {
          final client = _FakeHttpClient(
            statusCode: 409,
            body: '{"detail": "Ce rendez-vous n\'est plus modifiable."}',
          );

          await expectLater(
            _gateway(client).modify(
              appointmentId: 'rdv-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<NotModifiableException>()),
          );
        });

        test('409 créneau pris → SlotTakenException', () async {
          final client = _FakeHttpClient(
            statusCode: 409,
            body: '{"detail": "slot already taken"}',
          );

          await expectLater(
            _gateway(client).modify(
              appointmentId: 'rdv-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<SlotTakenException>()),
          );
        });

        test('409 salon non réservable → NotBookableException', () async {
          final client = _FakeHttpClient(
            statusCode: 409,
            body: '{"detail": "Ce salon n\'accepte pas encore de réservation."}',
          );

          await expectLater(
            _gateway(client).modify(
              appointmentId: 'rdv-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<NotBookableException>()),
          );
        });

        test('500 → AppointmentGatewayException', () async {
          final client = _FakeHttpClient(statusCode: 500, body: '');

          await expectLater(
            _gateway(client).modify(
              appointmentId: 'rdv-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('panne réseau → AppointmentGatewayException', () async {
          await expectLater(
            _gateway(_NetworkFailClient()).modify(
              appointmentId: 'rdv-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('corps JSON illisible sur 200 → AppointmentGatewayException',
            () async {
          final client =
              _FakeHttpClient(statusCode: 200, body: 'not-valid-json');

          await expectLater(
            _gateway(client).modify(
              appointmentId: 'rdv-1',
              draft: _draft(),
              accessToken: 'tok',
            ),
            throwsA(isA<AppointmentGatewayException>()),
          );
        });

        test('UnauthorizedException ne contient pas le jeton', () async {
          final client = _FakeHttpClient(statusCode: 401, body: '{}');

          Object? caught;
          try {
            await _gateway(client).modify(
              appointmentId: 'rdv-1',
              draft: _draft(),
              accessToken: 'secret-tok-modify',
            );
          } catch (e) {
            caught = e;
          }

          expect(caught, isA<UnauthorizedException>());
          final msg = (caught as UnauthorizedException).message;
          expect(msg.contains('secret-tok-modify'), isFalse);
        });
      });
    });
  });
}
