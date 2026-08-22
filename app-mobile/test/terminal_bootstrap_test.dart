// Tests widget — TerminalBootstrap (US-8.5, #159).
//
// Couverture : credential absent → TerminalActivationScreen ; indicateur de
// chargement pendant l'authentification silencieuse ; authentification réussie →
// TerminalHomeScreen (deps construits après authentification) ; credential refusé
// (401) → credential effacé + retour à l'activation ; échec réseau →
// TerminalUnavailableScreen (credential conservé) + Réessayer relance
// l'authentification ; activation réussie depuis l'écran d'activation → enchaîne
// sur l'authentification silencieuse ; imprimante jamais configurée →
// TerminalPrinterSetupScreen une seule fois avant l'accueil (#160). seedDevSalon
// (--dart-define=TERMINAL_SALON_ID) n'est pas testé ici (lit une constante de
// compilation globale, non substituable par test).
//
// `TerminalBootstrap` est extrait de `TerminalApp` précisément pour être testable sans le
// binaire réel (aucun écran de saisie de credential : le credential est injecté au
// build, voir l'en-tête de `terminal_bootstrap.dart`).

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/terminal/terminal_activation_screen.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_bootstrap.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_deps.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_home_screen.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_printer_setup_screen.dart';
import 'package:coiflink_mobile/adapters/ui/terminal/terminal_unavailable_screen.dart';
import 'package:coiflink_mobile/application/terminal_device_session.dart';
import 'package:coiflink_mobile/application/ports/printer_device_scan_gateway.dart';
import 'package:coiflink_mobile/application/ports/terminal_activation_gateway.dart';
import 'package:coiflink_mobile/application/ports/terminal_auth_gateway.dart';
import 'package:coiflink_mobile/application/ports/terminal_credential_store.dart';
import 'package:coiflink_mobile/application/ports/terminal_identity_gateway.dart';
import 'package:coiflink_mobile/application/ports/terminal_queue_gateway.dart';
import 'package:coiflink_mobile/application/ports/salon_catalog_gateway.dart';
import 'package:coiflink_mobile/application/ports/ticket_printer_device_store.dart';
import 'package:coiflink_mobile/application/ports/ticket_printer_gateway.dart';
import 'package:coiflink_mobile/application/use_cases/get_salon_detail.dart';
import 'package:coiflink_mobile/domain/customer/walk_in_gender.dart';
import 'package:coiflink_mobile/domain/salon/salon_detail.dart';
import 'package:coiflink_mobile/domain/ticket/ticket_print_payload.dart';

// ---------------------------------------------------------------------------
// Faux ports — session device
// ---------------------------------------------------------------------------

class _StubAuthGateway implements TerminalAuthGateway {
  _StubAuthGateway({this.tokens, this.error, this.completer});

  final TerminalDeviceTokens? tokens;
  final Object? error;
  final Completer<TerminalDeviceTokens>? completer;
  int callCount = 0;

  @override
  Future<TerminalDeviceTokens> login(TerminalCredential credential) async {
    callCount++;
    if (completer != null) return completer!.future;
    if (error != null) throw error!;
    return tokens!;
  }
}

// ---------------------------------------------------------------------------
// Faux ports — activation / credential store
// ---------------------------------------------------------------------------

class _InMemoryCredentialStore implements TerminalCredentialStore {
  _InMemoryCredentialStore({TerminalCredential? initial}) : _stored = initial;

  TerminalCredential? _stored;
  int clearCalls = 0;

  @override
  Future<TerminalCredential?> read() async => _stored;

  @override
  Future<void> save(TerminalCredential credential) async => _stored = credential;

  @override
  Future<void> clear() async {
    clearCalls++;
    _stored = null;
  }
}

class _StubActivationGateway implements TerminalActivationGateway {
  _StubActivationGateway({this.credential});

  final TerminalCredential? credential;

  @override
  Future<TerminalCredential> activate(String code) async => credential!;
}

// ---------------------------------------------------------------------------
// Faux ports — deps de l'accueil (nécessaires pour atteindre TerminalHomeScreen)
// ---------------------------------------------------------------------------

class _StubCatalogGateway implements SalonCatalogGateway {
  @override
  Future<SalonPage> searchSalons(SalonSearchQuery query) =>
      throw UnimplementedError();

  @override
  Future<SalonDetail> getSalon(String id) async =>
      const SalonDetail(id: 'salon-1', name: 'Salon Test', isBookable: true);
}

class _StubIdentityGateway implements TerminalIdentityGateway {
  @override
  Future<WalkInIdentity?> findByPhone(String phone) => throw UnimplementedError();

  @override
  Future<WalkInIdentity> createCustomer({
    required String firstName,
    required String lastName,
    required String phone,
    WalkInGender? gender,
  }) =>
      throw UnimplementedError();
}

class _StubQueueGateway implements TerminalQueueGateway {
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
// Faux ports — setup imprimante (#160)
// ---------------------------------------------------------------------------

class _InMemoryPrinterDeviceStore implements TicketPrinterDeviceStore {
  _InMemoryPrinterDeviceStore({String? initial}) : _stored = initial;

  String? _stored;

  @override
  Future<String?> read() async => _stored;

  @override
  Future<void> save(String deviceId) async => _stored = deviceId;

  @override
  Future<void> clear() async => _stored = null;
}

class _StubPrinterScanGateway implements PrinterDeviceScanGateway {
  _StubPrinterScanGateway({this.devices = const <PrinterDeviceInfo>[]});

  final List<PrinterDeviceInfo> devices;

  @override
  Future<List<PrinterDeviceInfo>> scan() async => devices;
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

const _credential = TerminalCredential(deviceId: 'device-001', secret: 's3cr3t');

Widget _buildBootstrap({
  TerminalAuthGateway? auth,
  TerminalCredentialStore? credentialStore,
  TerminalActivationGateway? activationGateway,
  PrinterDeviceScanGateway? printerScanGateway,
  TicketPrinterDeviceStore? printerDeviceStore,
}) {
  final session = TerminalDeviceSession(
    auth ??
        _StubAuthGateway(
          tokens: const TerminalDeviceTokens(accessToken: 'tok', salonId: 'salon-1'),
        ),
  );
  return MaterialApp(
    home: TerminalBootstrap(
      session: session,
      credentialStore: credentialStore ?? _InMemoryCredentialStore(initial: _credential),
      activationGateway: activationGateway ?? _StubActivationGateway(),
      printerScanGateway: printerScanGateway ?? _StubPrinterScanGateway(),
      // Déjà configurée par défaut : les tests qui ne portent pas sur #160 ne
      // doivent pas transiter par `TerminalPrinterSetupScreen`.
      printerDeviceStore:
          printerDeviceStore ?? _InMemoryPrinterDeviceStore(initial: 'printer-1'),
      buildDeps: () => TerminalDeps(
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
  group('TerminalBootstrap — borne jamais activée', () {
    testWidgets('credential absent → affiche TerminalActivationScreen', (tester) async {
      await tester.pumpWidget(
        _buildBootstrap(credentialStore: _InMemoryCredentialStore()),
      );
      await tester.pumpAndSettle();

      expect(find.byType(TerminalActivationScreen), findsOneWidget);
    });
  });

  group('TerminalBootstrap — chargement', () {
    testWidgets('affiche un indicateur de chargement pendant l\'authentification',
        (tester) async {
      final completer = Completer<TerminalDeviceTokens>();
      await tester.pumpWidget(
        _buildBootstrap(auth: _StubAuthGateway(completer: completer)),
      );
      await tester.pump(); // premier frame : initState déclenche _bootstrap()

      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      completer.complete(const TerminalDeviceTokens(accessToken: 'tok', salonId: 'salon-1'));
      await tester.pumpAndSettle();
    });
  });

  group('TerminalBootstrap — credential refusé (401)', () {
    testWidgets('efface le credential et retourne à l\'activation', (tester) async {
      final store = _InMemoryCredentialStore(initial: _credential);
      await tester.pumpWidget(
        _buildBootstrap(
          auth: _StubAuthGateway(error: const TerminalInvalidCredentialException()),
          credentialStore: store,
        ),
      );
      await tester.pumpAndSettle();

      expect(find.byType(TerminalActivationScreen), findsOneWidget);
      expect(store.clearCalls, 1);
      expect(await store.read(), isNull);
    });
  });

  group('TerminalBootstrap — échec réseau', () {
    testWidgets('affiche TerminalUnavailableScreen sans effacer le credential', (tester) async {
      final store = _InMemoryCredentialStore(initial: _credential);
      await tester.pumpWidget(
        _buildBootstrap(
          auth: _StubAuthGateway(error: const TerminalAuthException()),
          credentialStore: store,
        ),
      );
      await tester.pumpAndSettle();

      expect(find.byType(TerminalUnavailableScreen), findsOneWidget);
      expect(store.clearCalls, 0);
      expect(await store.read(), _credential);
    });

    testWidgets('Réessayer relance l\'authentification', (tester) async {
      final auth = _StubAuthGateway(error: const TerminalAuthException());
      await tester.pumpWidget(_buildBootstrap(auth: auth));
      await tester.pumpAndSettle();
      expect(find.byType(TerminalUnavailableScreen), findsOneWidget);

      final callsBeforeRetry = auth.callCount;
      await tester.tap(find.text('Réessayer'));
      await tester.pumpAndSettle();

      // Le gateway continue de refuser : toujours indisponible, mais un nouvel
      // essai a bien été déclenché (pas de plantage, pas de blocage).
      expect(auth.callCount, greaterThan(callsBeforeRetry));
      expect(find.byType(TerminalUnavailableScreen), findsOneWidget);
    });
  });

  group('TerminalBootstrap — succès', () {
    testWidgets('credential stocké valide → authentifie silencieusement → TerminalHomeScreen',
        (tester) async {
      await tester.pumpWidget(_buildBootstrap());
      await tester.pumpAndSettle();

      expect(find.byType(TerminalHomeScreen), findsOneWidget);
    });
  });

  group('TerminalBootstrap — activation puis authentification', () {
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
      expect(find.byType(TerminalActivationScreen), findsOneWidget);

      for (final digit in '123456'.split('')) {
        await tester.tap(find.widgetWithText(OutlinedButton, digit));
        await tester.pump();
      }
      await tester.tap(find.bySemanticsLabel('Activer'));
      await tester.pumpAndSettle();

      expect(await store.read(), _credential);
      expect(find.byType(TerminalHomeScreen), findsOneWidget);
    });
  });

  group('TerminalBootstrap — setup imprimante (#160)', () {
    testWidgets(
        'imprimante jamais configurée → affiche TerminalPrinterSetupScreen après authentification',
        (tester) async {
      await tester.pumpWidget(
        _buildBootstrap(printerDeviceStore: _InMemoryPrinterDeviceStore()),
      );
      await tester.pumpAndSettle();

      expect(find.byType(TerminalPrinterSetupScreen), findsOneWidget);
      expect(find.byType(TerminalHomeScreen), findsNothing);
    });

    testWidgets('« Configurer plus tard » enchaîne sur TerminalHomeScreen sans persister',
        (tester) async {
      final printerStore = _InMemoryPrinterDeviceStore();
      await tester.pumpWidget(_buildBootstrap(printerDeviceStore: printerStore));
      await tester.pumpAndSettle();
      expect(find.byType(TerminalPrinterSetupScreen), findsOneWidget);

      await tester.tap(find.text('Configurer plus tard'));
      await tester.pumpAndSettle();

      expect(find.byType(TerminalHomeScreen), findsOneWidget);
      expect(await printerStore.read(), isNull);
    });

    testWidgets('sélection d\'une imprimante persiste puis enchaîne sur TerminalHomeScreen',
        (tester) async {
      final printerStore = _InMemoryPrinterDeviceStore();
      await tester.pumpWidget(
        _buildBootstrap(
          printerDeviceStore: printerStore,
          printerScanGateway: _StubPrinterScanGateway(
            devices: const <PrinterDeviceInfo>[
              PrinterDeviceInfo(id: 'AA:BB:CC', name: 'Imprimante Salon'),
            ],
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Imprimante Salon'), findsOneWidget);

      await tester.tap(find.text('Imprimante Salon'));
      await tester.pumpAndSettle();

      expect(await printerStore.read(), 'AA:BB:CC');
      expect(find.byType(TerminalHomeScreen), findsOneWidget);
    });

    testWidgets('imprimante déjà configurée → passe directement à TerminalHomeScreen',
        (tester) async {
      await tester.pumpWidget(
        _buildBootstrap(
          printerDeviceStore: _InMemoryPrinterDeviceStore(initial: 'printer-1'),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.byType(TerminalPrinterSetupScreen), findsNothing);
      expect(find.byType(TerminalHomeScreen), findsOneWidget);
    });
  });
}
