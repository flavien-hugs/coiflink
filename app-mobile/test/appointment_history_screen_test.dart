// Tests widget — AppointmentHistoryScreen (US-4.4, #30).
//
// Couverture : titre AppBar ; indicateur de chargement ; affichage d'un RDV
// terminé (puce « Terminé », horaires, prix figé) ; liste multiple ; état vide ;
// état sans session (onRequireLogin appelé) ; UnauthorizedException (session
// effacée, « Session expirée ») ; erreur réseau (« Réessayer ») ; absence
// des boutons d'action (lecture seule, §8.1).
// Aucun appel HTTP réel ; aucun jeton de production dans les fixtures (§11).

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/appointments/appointment_history_screen.dart';
import 'package:coiflink_mobile/application/auth_session.dart';
import 'package:coiflink_mobile/application/ports/appointment_gateway.dart';
import 'package:coiflink_mobile/application/ports/token_store.dart';
import 'package:coiflink_mobile/application/use_cases/list_my_appointment_history.dart';
import 'package:coiflink_mobile/domain/appointment/appointment.dart';
import 'package:coiflink_mobile/domain/appointment/appointment_status.dart';
import 'package:coiflink_mobile/domain/appointment/availability_slot.dart';

// ---------------------------------------------------------------------------
// Faux gateway
// ---------------------------------------------------------------------------

class _StubGateway implements AppointmentGateway {
  _StubGateway({
    this.result,
    this.error,
    this.future,
  });

  final List<Appointment>? result;
  final Object? error;
  final Future<List<Appointment>>? future;

  @override
  Future<List<AvailabilitySlot>> availableSlots({
    required String salonId,
    required DateTime date,
    required String serviceId,
    String? hairdresserId,
  }) =>
      throw UnimplementedError();

  @override
  Future<Appointment> book({
    required String salonId,
    required BookingDraft draft,
    required String accessToken,
  }) =>
      throw UnimplementedError();

  @override
  Future<List<Appointment>> myAppointments({required String accessToken}) =>
      throw UnimplementedError();

  @override
  Future<List<Appointment>> myHistory({required String accessToken}) async {
    if (future != null) return future!;
    if (error != null) throw error!;
    return result ?? const [];
  }

  @override
  Future<Appointment> modify({
    required String appointmentId,
    required BookingDraft draft,
    required String accessToken,
  }) =>
      throw UnimplementedError();

  @override
  Future<Appointment> cancel({
    required String appointmentId,
    String? reason,
    required String accessToken,
  }) =>
      throw UnimplementedError();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

AuthSession _sessionWithToken(String token) {
  final store = InMemoryTokenStore();
  store.write(token); // body is synchronous before any await
  return AuthSession(store);
}

InMemoryTokenStore _emptyStore() => InMemoryTokenStore();

AuthSession _emptySession() => AuthSession(_emptyStore());

Appointment _completedAppointment({
  String id = 'rdv-hist-1',
  List<BookedService> services = const [],
}) {
  return Appointment(
    id: id,
    salonId: 'salon-1',
    date: DateTime(2026, 7, 20),
    startTime: '10:30',
    endTime: '11:30',
    status: AppointmentStatus.completed,
    services: services,
  );
}

Widget _screen({
  required AppointmentGateway gateway,
  required AuthSession session,
  Future<bool> Function(BuildContext)? onRequireLogin,
}) {
  return MaterialApp(
    home: AppointmentHistoryScreen(
      listMyAppointmentHistory: ListMyAppointmentHistory(gateway),
      session: session,
      onRequireLogin:
          onRequireLogin ?? (_) async => false,
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('AppointmentHistoryScreen', () {
    group('titre', () {
      testWidgets('AppBar affiche "Mon historique"', (tester) async {
        final gateway = _StubGateway(result: const []);
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Mon historique'), findsOneWidget);
      });
    });

    group('état de chargement', () {
      testWidgets(
          'CircularProgressIndicator visible pendant le chargement (avant résolution)',
          (tester) async {
        final completer = Completer<List<Appointment>>();
        final gateway = _StubGateway(future: completer.future);
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );

        // Après pumpWidget la future du gateway n'est pas encore résolue.
        expect(find.byType(CircularProgressIndicator), findsOneWidget);

        completer.complete(const []);
        await tester.pumpAndSettle();
      });
    });

    group('affichage d\'un RDV terminé', () {
      testWidgets('affiche la puce avec le label "Terminé"', (tester) async {
        final gateway = _StubGateway(
          result: [_completedAppointment()],
        );
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Terminé'), findsOneWidget);
      });

      testWidgets('affiche les horaires "10:30 – 11:30"', (tester) async {
        final gateway = _StubGateway(
          result: [_completedAppointment()],
        );
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('10:30 – 11:30'), findsOneWidget);
      });

      testWidgets('affiche le prix figé "7500.00 FCFA"', (tester) async {
        final gateway = _StubGateway(
          result: [
            _completedAppointment(
              services: const [
                BookedService(serviceId: 'svc-coupe', priceAtBooking: '7500.00'),
              ],
            ),
          ],
        );
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('7500.00 FCFA'), findsOneWidget);
      });

      testWidgets(
          'plusieurs RDV → autant de puces "Terminé" (un par rendez-vous)',
          (tester) async {
        final gateway = _StubGateway(
          result: [
            _completedAppointment(id: 'rdv-1'),
            _completedAppointment(id: 'rdv-2'),
          ],
        );
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Terminé'), findsNWidgets(2));
      });
    });

    group('lecture seule (§8.1) — absence de boutons d\'action', () {
      testWidgets('aucun bouton "Modifier" (RDV terminé non modifiable)',
          (tester) async {
        final gateway = _StubGateway(
          result: [_completedAppointment()],
        );
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Modifier'), findsNothing);
      });

      testWidgets('aucun bouton "Annuler" (RDV terminé non annulable)',
          (tester) async {
        final gateway = _StubGateway(
          result: [_completedAppointment()],
        );
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(find.text('Annuler'), findsNothing);
      });
    });

    group('état vide', () {
      testWidgets(
          'liste vide → message "Vous n\'avez aucun rendez-vous terminé."',
          (tester) async {
        final gateway = _StubGateway(result: const []);
        await tester.pumpWidget(
          _screen(gateway: gateway, session: _sessionWithToken('tok')),
        );
        await tester.pumpAndSettle();

        expect(
          find.text('Vous n\'avez aucun rendez-vous terminé.'),
          findsOneWidget,
        );
      });
    });

    group('session absente', () {
      testWidgets(
          'sans jeton : onRequireLogin est appelé et bouton "Se connecter" affiché',
          (tester) async {
        var loginCalled = false;
        final gateway = _StubGateway(result: const []);
        await tester.pumpWidget(
          _screen(
            gateway: gateway,
            session: _emptySession(),
            onRequireLogin: (_) async {
              loginCalled = true;
              return false; // pas de login effectué
            },
          ),
        );
        await tester.pumpAndSettle();

        expect(loginCalled, isTrue);
        expect(find.text('Se connecter'), findsOneWidget);
      });
    });

    group('UnauthorizedException (jeton expiré, §11.1)', () {
      testWidgets('401 → session effacée (jeton null après règlement)',
          (tester) async {
        final store = InMemoryTokenStore();
        store.write('valid-token-abc');
        final session = AuthSession(store);
        final gateway =
            _StubGateway(error: const UnauthorizedException());
        await tester.pumpWidget(
          _screen(gateway: gateway, session: session),
        );
        await tester.pumpAndSettle();

        expect(await store.read(), isNull);
      });

      testWidgets('401 → message "Session expirée, veuillez vous reconnecter."',
          (tester) async {
        final gateway =
            _StubGateway(error: const UnauthorizedException());
        await tester.pumpWidget(
          _screen(
            gateway: gateway,
            session: _sessionWithToken('expired-token'),
          ),
        );
        await tester.pumpAndSettle();

        expect(
          find.text('Session expirée, veuillez vous reconnecter.'),
          findsOneWidget,
        );
      });

      testWidgets('401 → bouton "Se connecter" affiché', (tester) async {
        final gateway =
            _StubGateway(error: const UnauthorizedException());
        await tester.pumpWidget(
          _screen(
            gateway: gateway,
            session: _sessionWithToken('expired-token'),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text('Se connecter'), findsOneWidget);
      });
    });

    group('erreur réseau / serveur', () {
      testWidgets(
          'AppointmentGatewayException → message d\'erreur + bouton "Réessayer"',
          (tester) async {
        final gateway = _StubGateway(
          error: const AppointmentGatewayException(
            'Impossible de joindre le serveur.',
          ),
        );
        await tester.pumpWidget(
          _screen(
            gateway: gateway,
            session: _sessionWithToken('tok'),
          ),
        );
        await tester.pumpAndSettle();

        expect(
          find.text('Impossible de joindre le serveur.'),
          findsOneWidget,
        );
        expect(find.text('Réessayer'), findsOneWidget);
      });
    });
  });
}
