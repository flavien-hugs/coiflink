// Tests widget — KioskBootstrap (US-8.5, #159).
//
// Couverture : credential absent → KioskActivationScreen ; indicateur de
// chargement pendant l'authentification silencieuse ; authentification réussie →
// KioskHomeScreen (deps construits après authentification) ; credential refusé
// (401) → credential effacé + retour à l'activation ; échec réseau →
// KioskUnavailableScreen (credential conservé) + Réessayer relance
// l'authentification ; activation réussie depuis l'écran d'activation → enchaîne
// sur l'authentification silencieuse. seedDevSalon (--dart-define=KIOSK_SALON_ID)
// n'est pas testé ici (lit une constante de compilation globale, non substituable
// par test).
//
// `KioskBootstrap` est extrait de `KioskApp` précisément pour être testable sans le
// binaire réel (aucun écran de saisie de credential : le credential est injecté au
// build, voir l'en-tête de `kiosk_bootstrap.dart`).

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_activation_screen.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_bootstrap.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_deps.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_home_screen.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_unavailable_screen.dart';
import 'package:coiflink_mobile/application/kiosk_device_session.dart';
import 'package:coiflink_mobile/application/ports/kiosk_activation_gateway.dart';
import 'package:coiflink_mobile/application/ports/kiosk_auth_gateway.dart';
import 'package:coiflink_mobile/application/ports/kiosk_credential_store.dart';
import 'package:coiflink_mobile/application/ports/kiosk_identity_gateway.dart';
import 'package:coiflink_mobile/application/ports/kiosk_queue_gateway.dart';
import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/ports/ticket_printer_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/get_salon_detail.dart';
import 'package:coiflink_mobile/domain/salon/salon_detail.dart';
import 'package:coiflink_mobile/domain/ticket/ticket_print_payload.dart';

// ---------------------------------------------------------------------------
// Faux ports — session device
// ---------------------------------------------------------------------------

class _StubAuthGateway implements KioskAuthGateway {
  _StubAuthGateway({this.tokens, this.error, this.completer});

  final KioskDeviceTokens? tokens;
  final Object? error;
  final Completer<KioskDeviceTokens>? completer;
  int callCount = 0;

  @override
  Future<KioskDeviceTokens> login(KioskCredential credential) async {
    callCount++;
    if (completer != null) return completer!.future;
    if (error != null) throw error!;
    return tokens!;
  }
}

// ---------------------------------------------------------------------------
// Faux ports — activation / credential store
// ---------------------------------------------------------------------------

class _InMemoryCredentialStore implements KioskCredentialStore {
  _InMemoryCredentialStore({KioskCredential? initial}) : _stored = initial;

  KioskCredential? _stored;
  int clearCalls = 0;

  @override
  Future<KioskCredential?> read() async => _stored;

  @override
  Future<void> save(KioskCredential credential) async => _stored = credential;

  @override
  Future<void> clear() async {
    clearCalls++;
    _stored = null;
  }
}

class _StubActivationGateway implements KioskActivationGateway {
  _StubActivationGateway({this.credential});

  final KioskCredential? credential;

  @override
  Future<KioskCredential> activate(String code) async => credential!;
}

// ---------------------------------------------------------------------------
// Faux ports — deps de l'accueil (nécessaires pour atteindre KioskHomeScreen)
// ---------------------------------------------------------------------------

class _StubCatalogGateway implements SalonCatalogGateway {
  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) =>
      throw UnimplementedError();

  @override
  Future<SalonDetail> getSalon(String id) async =>
      const SalonDetail(id: 'salon-1', name: 'Salon Test', isBookable: true);
}

class _StubIdentityGateway implements KioskIdentityGateway {
  @override
  Future<WalkInIdentity?> findByPhone(String phone) => throw UnimplementedError();

  @override
  Future<WalkInIdentity> createCustomer({
    required String firstName,
    required String lastName,
    required String phone,
  }) =>
      throw UnimplementedError();
}

class _StubQueueGateway implements KioskQueueGateway {
  @override
  Future<QueueTicket> joinQueue({
    String? customerProfileId,
    required List<String> serviceIds,
  }) =>
      throw UnimplementedError();
}

class _StubPrinterGateway implements TicketPrinterGateway {
  @override
  Future<void> connect() async {}

  @override
  Future<void> print(TicketPrintPayload payload) async {}

  @override
  Future<TicketPrinterStatus> status() async => TicketPrinterStatus.unknown;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// La borne est conçue pour une tablette (≥ 10"). Les 800×600 par défaut de
/// flutter_test font déborder le pavé numérique de l'écran d'activation
/// (dernière rangée hors zone cliquable).
void _setTabletSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

const _credential = KioskCredential(deviceId: 'device-001', secret: 's3cr3t');

Widget _buildBootstrap({
  KioskAuthGateway? auth,
  KioskCredentialStore? credentialStore,
  KioskActivationGateway? activationGateway,
}) {
  final session = KioskDeviceSession(
    auth ??
        _StubAuthGateway(
          tokens: const KioskDeviceTokens(accessToken: 'tok', salonId: 'salon-1'),
        ),
  );
  return MaterialApp(
    home: KioskBootstrap(
      session: session,
      credentialStore: credentialStore ?? _InMemoryCredentialStore(initial: _credential),
      activationGateway: activationGateway ?? _StubActivationGateway(),
      buildDeps: () => KioskDeps(
        salonId: session.salonId,
        getSalonDetail: GetSalonDetail(_StubCatalogGateway()),
        identityGateway: _StubIdentityGateway(),
        queueGateway: _StubQueueGateway(),
        printerGateway: _StubPrinterGateway(),
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('KioskBootstrap — borne jamais activée', () {
    testWidgets('credential absent → affiche KioskActivationScreen', (tester) async {
      await tester.pumpWidget(
        _buildBootstrap(credentialStore: _InMemoryCredentialStore()),
      );
      await tester.pumpAndSettle();

      expect(find.byType(KioskActivationScreen), findsOneWidget);
    });
  });

  group('KioskBootstrap — chargement', () {
    testWidgets('affiche un indicateur de chargement pendant l\'authentification',
        (tester) async {
      final completer = Completer<KioskDeviceTokens>();
      await tester.pumpWidget(
        _buildBootstrap(auth: _StubAuthGateway(completer: completer)),
      );
      await tester.pump(); // premier frame : initState déclenche _bootstrap()

      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      completer.complete(const KioskDeviceTokens(accessToken: 'tok', salonId: 'salon-1'));
      await tester.pumpAndSettle();
    });
  });

  group('KioskBootstrap — credential refusé (401)', () {
    testWidgets('efface le credential et retourne à l\'activation', (tester) async {
      final store = _InMemoryCredentialStore(initial: _credential);
      await tester.pumpWidget(
        _buildBootstrap(
          auth: _StubAuthGateway(error: const KioskInvalidCredentialException()),
          credentialStore: store,
        ),
      );
      await tester.pumpAndSettle();

      expect(find.byType(KioskActivationScreen), findsOneWidget);
      expect(store.clearCalls, 1);
      expect(await store.read(), isNull);
    });
  });

  group('KioskBootstrap — échec réseau', () {
    testWidgets('affiche KioskUnavailableScreen sans effacer le credential', (tester) async {
      final store = _InMemoryCredentialStore(initial: _credential);
      await tester.pumpWidget(
        _buildBootstrap(
          auth: _StubAuthGateway(error: const KioskAuthException()),
          credentialStore: store,
        ),
      );
      await tester.pumpAndSettle();

      expect(find.byType(KioskUnavailableScreen), findsOneWidget);
      expect(store.clearCalls, 0);
      expect(await store.read(), _credential);
    });

    testWidgets('Réessayer relance l\'authentification', (tester) async {
      final auth = _StubAuthGateway(error: const KioskAuthException());
      await tester.pumpWidget(_buildBootstrap(auth: auth));
      await tester.pumpAndSettle();
      expect(find.byType(KioskUnavailableScreen), findsOneWidget);

      final callsBeforeRetry = auth.callCount;
      await tester.tap(find.text('Réessayer'));
      await tester.pumpAndSettle();

      // Le gateway continue de refuser : toujours indisponible, mais un nouvel
      // essai a bien été déclenché (pas de plantage, pas de blocage).
      expect(auth.callCount, greaterThan(callsBeforeRetry));
      expect(find.byType(KioskUnavailableScreen), findsOneWidget);
    });
  });

  group('KioskBootstrap — succès', () {
    testWidgets('credential stocké valide → authentifie silencieusement → KioskHomeScreen',
        (tester) async {
      await tester.pumpWidget(_buildBootstrap());
      await tester.pumpAndSettle();

      expect(find.byType(KioskHomeScreen), findsOneWidget);
    });
  });

  group('KioskBootstrap — activation puis authentification', () {
    testWidgets('activation réussie → enchaîne sur l\'authentification silencieuse',
        (tester) async {
      _setTabletSurface(tester);
      final store = _InMemoryCredentialStore();
      await tester.pumpWidget(
        _buildBootstrap(
          credentialStore: store,
          activationGateway: _StubActivationGateway(credential: _credential),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(KioskActivationScreen), findsOneWidget);

      for (final digit in '123456'.split('')) {
        await tester.tap(find.widgetWithText(OutlinedButton, digit));
        await tester.pump();
      }
      await tester.tap(find.bySemanticsLabel('Activer'));
      await tester.pumpAndSettle();

      expect(await store.read(), _credential);
      expect(find.byType(KioskHomeScreen), findsOneWidget);
    });
  });
}
