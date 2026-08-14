// Tests widget — TerminalActivationScreen (US-8.5, #159).
//
// Couverture : saisie du code à 6 chiffres (pavé numérique interne) ; validation
// activée seulement à 6 chiffres ; succès → sauvegarde du credential puis
// `onActivated` ; échec → message neutre, code réinitialisé, pas de navigation
// automatique (décision n°9).

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/terminal/terminal_activation_screen.dart';
import 'package:coiflink_mobile/application/ports/terminal_activation_gateway.dart';
import 'package:coiflink_mobile/application/ports/terminal_auth_gateway.dart';
import 'package:coiflink_mobile/application/ports/terminal_credential_store.dart';

// ---------------------------------------------------------------------------
// Faux ports
// ---------------------------------------------------------------------------

class _StubActivationGateway implements TerminalActivationGateway {
  _StubActivationGateway({this.credential, this.error});

  final TerminalCredential? credential;
  final Object? error;
  final List<String> activateCalls = <String>[];

  @override
  Future<TerminalCredential> activate(String code) async {
    activateCalls.add(code);
    if (error != null) throw error!;
    return credential!;
  }
}

class _InMemoryCredentialStore implements TerminalCredentialStore {
  TerminalCredential? saved;

  @override
  Future<TerminalCredential?> read() async => saved;

  @override
  Future<void> save(TerminalCredential credential) async => saved = credential;

  @override
  Future<void> clear() async => saved = null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// La borne est conçue pour une tablette (≥ 10"). Les 800×600 par défaut de
/// flutter_test font déborder le pavé numérique (dernière rangée hors zone
/// cliquable).
void _setTabletSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Widget _buildScreen({
  required TerminalActivationGateway activationGateway,
  required TerminalCredentialStore credentialStore,
  ValueChanged<TerminalCredential>? onActivated,
}) {
  return MaterialApp(
    home: TerminalActivationScreen(
      activationGateway: activationGateway,
      credentialStore: credentialStore,
      onActivated: onActivated ?? (_) {},
    ),
  );
}

Future<void> _typeCode(WidgetTester tester, String code) async {
  for (final digit in code.split('')) {
    await tester.tap(find.widgetWithText(OutlinedButton, digit));
    await tester.pump();
  }
}

/// Le code affiché est le seul `Text` **exact** correspondant à la chaîne tapée :
/// les touches du pavé (0-9) portent aussi un `Text` avec le même chiffre, donc
/// `find.text('1')` seul matcherait la touche « 1 » même si l'écran affichait
/// autre chose. On cible spécifiquement le texte de grande taille du code.
Finder _codeDisplay(String expected) => find.byWidgetPredicate(
      (w) => w is Text && w.data == expected && w.style?.letterSpacing == 8,
    );

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('TerminalActivationScreen — saisie', () {
    testWidgets('affiche un tiret tant qu\'aucun chiffre n\'est saisi', (tester) async {
      _setTabletSurface(tester);
      await tester.pumpWidget(_buildScreen(
        activationGateway: _StubActivationGateway(),
        credentialStore: _InMemoryCredentialStore(),
      ));

      expect(_codeDisplay('—'), findsOneWidget);
    });

    testWidgets('affiche les chiffres saisis', (tester) async {
      _setTabletSurface(tester);
      await tester.pumpWidget(_buildScreen(
        activationGateway: _StubActivationGateway(),
        credentialStore: _InMemoryCredentialStore(),
      ));

      await _typeCode(tester, '123');

      expect(_codeDisplay('123'), findsOneWidget);
    });

    testWidgets('Effacer retire le dernier chiffre', (tester) async {
      _setTabletSurface(tester);
      await tester.pumpWidget(_buildScreen(
        activationGateway: _StubActivationGateway(),
        credentialStore: _InMemoryCredentialStore(),
      ));

      await _typeCode(tester, '12');
      await tester.tap(find.bySemanticsLabel('Effacer'));
      await tester.pump();

      expect(_codeDisplay('1'), findsOneWidget);
    });

    testWidgets('ignore les chiffres au-delà de 6', (tester) async {
      _setTabletSurface(tester);
      await tester.pumpWidget(_buildScreen(
        activationGateway: _StubActivationGateway(),
        credentialStore: _InMemoryCredentialStore(),
      ));

      await _typeCode(tester, '1234567');

      expect(_codeDisplay('123456'), findsOneWidget);
    });
  });

  group('TerminalActivationScreen — succès', () {
    testWidgets('code complet → active, sauvegarde le credential et appelle onActivated',
        (tester) async {
      _setTabletSurface(tester);
      const credential = TerminalCredential(deviceId: 'device-001', secret: 's3cr3t');
      final gateway = _StubActivationGateway(credential: credential);
      final store = _InMemoryCredentialStore();
      TerminalCredential? activated;

      await tester.pumpWidget(_buildScreen(
        activationGateway: gateway,
        credentialStore: store,
        onActivated: (c) => activated = c,
      ));

      await _typeCode(tester, '123456');
      await tester.tap(find.bySemanticsLabel('Activer'));
      // Pas de `pumpAndSettle()` : sur succès, l'écran ne réinitialise jamais
      // `_submitting` lui-même (c'est au parent de le démonter, voir
      // `TerminalBootstrap`) — l'indicateur de chargement resterait affiché indéfiniment
      // et ferait boucler `pumpAndSettle()` sans fin.
      await tester.pump();
      await tester.pump();

      expect(gateway.activateCalls, <String>['123456']);
      expect(store.saved, credential);
      expect(activated, credential);
    });

    testWidgets('affiche un indicateur de chargement pendant l\'activation', (tester) async {
      _setTabletSurface(tester);
      const credential = TerminalCredential(deviceId: 'device-001', secret: 's3cr3t');
      await tester.pumpWidget(_buildScreen(
        activationGateway: _StubActivationGateway(credential: credential),
        credentialStore: _InMemoryCredentialStore(),
      ));

      await _typeCode(tester, '123456');
      await tester.tap(find.bySemanticsLabel('Activer'));
      await tester.pump();

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });
  });

  group('TerminalActivationScreen — échec', () {
    testWidgets('code refusé → message neutre, code réinitialisé, reste sur l\'écran',
        (tester) async {
      _setTabletSurface(tester);
      final gateway = _StubActivationGateway(
        error: const TerminalActivationException(),
      );
      TerminalCredential? activated;

      await tester.pumpWidget(_buildScreen(
        activationGateway: gateway,
        credentialStore: _InMemoryCredentialStore(),
        onActivated: (c) => activated = c,
      ));

      await _typeCode(tester, '999999');
      await tester.tap(find.bySemanticsLabel('Activer'));
      await tester.pumpAndSettle();

      expect(find.text("Code d'activation invalide ou expiré."), findsOneWidget);
      expect(_codeDisplay('—'), findsOneWidget, reason: 'le code doit être réinitialisé');
      expect(activated, isNull);
      expect(find.byType(TerminalActivationScreen), findsOneWidget);
    });

    testWidgets('permet de ressaisir un code après un échec', (tester) async {
      _setTabletSurface(tester);
      const credential = TerminalCredential(deviceId: 'device-001', secret: 's3cr3t');
      var firstAttempt = true;
      final gateway = _FlakyActivationGateway(
        onFirstCall: () => firstAttempt,
        credential: credential,
      );

      await tester.pumpWidget(_buildScreen(
        activationGateway: gateway,
        credentialStore: _InMemoryCredentialStore(),
      ));

      await _typeCode(tester, '111111');
      await tester.tap(find.bySemanticsLabel('Activer'));
      await tester.pumpAndSettle();
      expect(find.text("Code d'activation invalide ou expiré."), findsOneWidget);

      firstAttempt = false;
      await _typeCode(tester, '222222');
      await tester.tap(find.bySemanticsLabel('Activer'));
      // Deuxième tentative réussie : pas de `pumpAndSettle()`, même raison que
      // ci-dessus (l'indicateur de chargement persiste après succès).
      await tester.pump();
      await tester.pump();

      expect(gateway.calls, <String>['111111', '222222']);
    });
  });
}

class _FlakyActivationGateway implements TerminalActivationGateway {
  _FlakyActivationGateway({required this.onFirstCall, required this.credential});

  final bool Function() onFirstCall;
  final TerminalCredential credential;
  final List<String> calls = <String>[];

  @override
  Future<TerminalCredential> activate(String code) async {
    calls.add(code);
    if (onFirstCall()) throw const TerminalActivationException();
    return credential;
  }
}
