// Tests widget — showKioskExitGate / _KioskExitDialog (US-8.5, #159 §H).
//
// Couverture :
//   - Le dialogue s'ouvre à l'appel de showKioskExitGate ;
//   - Les chiffres s'accumulent masqués (points) — jamais affichés en clair ;
//   - La saisie est limitée à 4 chiffres ;
//   - Backspace efface le dernier point ;
//   - La touche validation est désactivée avant 4 chiffres, activée après ;
//   - La validation est **inerte** : affiche « Fonctionnalité de maintenance à venir. »
//     sans fermer le dialogue ni naviguer hors de l'écran d'accueil (garantie §H) ;
//   - Le dialogue se ferme via « Fermer » ;
//   - Le minuteur d'inactivité est suspendu pendant la saisie : le dialogue persiste
//     bien au-delà du timeout.
//
// Utilise le vrai `KioskInactivityGuard` (pas de mock) pour valider la suspension
// du minuteur par comportement observable (le dialogue reste à l'écran).

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_exit_gate.dart';
import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_inactivity_guard.dart';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Dimensionne la surface en tablette pour éviter le débordement de KioskNumericKeypad
/// (les gros boutons de la borne ont besoin de plus de 600 dp de hauteur).
void _setTabletSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Widget _buildApp({
  required GlobalKey<NavigatorState> navKey,
  Duration timeout = const Duration(seconds: 5),
}) {
  return MaterialApp(
    navigatorKey: navKey,
    builder: (context, child) => KioskInactivityGuard(
      navigatorKey: navKey,
      timeout: timeout,
      child: child!,
    ),
    home: Builder(
      builder: (ctx) => Scaffold(
        body: Center(
          child: ElevatedButton(
            onPressed: () => showKioskExitGate(ctx),
            child: const Text('Ouvrir maintenance'),
          ),
        ),
      ),
    ),
  );
}

Future<void> _openDialog(WidgetTester tester) async {
  await tester.tap(find.text('Ouvrir maintenance'));
  await tester.pumpAndSettle();
}

/// Tape [count] fois le chiffre '1' sur le pavé numérique du dialogue.
Future<void> _typeDigits(WidgetTester tester, int count) async {
  for (var i = 0; i < count; i++) {
    await tester.tap(find.widgetWithText(OutlinedButton, '1').first);
    await tester.pump();
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('showKioskExitGate — ouverture du dialogue', () {
    testWidgets('affiche le dialogue après l\'appel', (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);

      expect(find.byType(AlertDialog), findsOneWidget);
    });

    testWidgets('affiche le titre « Accès maintenance »', (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);

      expect(find.text('Accès maintenance'), findsWidgets);
    });

    testWidgets('affiche l\'invite initiale « Saisissez le code gérant. »',
        (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);

      expect(find.text('Saisissez le code gérant.'), findsOneWidget);
    });
  });

  group('showKioskExitGate — saisie du PIN', () {
    testWidgets('les chiffres sont masqués par des points (jamais en clair)',
        (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);
      await _typeDigits(tester, 3);

      // L'affichage doit montrer exactement trois points — jamais les chiffres
      expect(find.text('•••'), findsOneWidget);
      expect(find.text('111'), findsNothing);
    });

    testWidgets('la saisie est limitée à 4 chiffres', (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);
      // Tenter 6 chiffres (limite : 4)
      await _typeDigits(tester, 6);

      // Le quatrième point seulement doit s'afficher — le cinquième et sixième ignorés
      expect(find.text('••••'), findsOneWidget);
    });

    testWidgets('backspace efface le dernier point', (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);
      await _typeDigits(tester, 3);
      expect(find.text('•••'), findsOneWidget);

      await tester.tap(find.bySemanticsLabel('Effacer'));
      await tester.pump();

      expect(find.text('••'), findsOneWidget);
    });

    testWidgets('touche validation désactivée avant 4 chiffres', (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);
      await _typeDigits(tester, 3);

      final submitButton = tester.widget<FilledButton>(
        find.ancestor(
          of: find.bySemanticsLabel('Valider'),
          matching: find.byType(FilledButton),
        ),
      );
      expect(submitButton.onPressed, isNull);
    });

    testWidgets('touche validation activée après 4 chiffres', (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);
      await _typeDigits(tester, 4);

      final submitButton = tester.widget<FilledButton>(
        find.ancestor(
          of: find.bySemanticsLabel('Valider'),
          matching: find.byType(FilledButton),
        ),
      );
      expect(submitButton.onPressed, isNotNull);
    });
  });

  group('showKioskExitGate — invariant de sécurité (§H)', () {
    testWidgets(
        'la validation est inerte : affiche le message « maintenance à venir »',
        (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);
      await _typeDigits(tester, 4);

      await tester.tap(
        find.ancestor(
          of: find.bySemanticsLabel('Valider'),
          matching: find.byType(FilledButton),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        find.text('Fonctionnalité de maintenance à venir.'),
        findsOneWidget,
      );
    });

    testWidgets(
        'la validation ne ferme pas le dialogue (le kiosque ne quitte pas son mode)',
        (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);
      await _typeDigits(tester, 4);

      await tester.tap(
        find.ancestor(
          of: find.bySemanticsLabel('Valider'),
          matching: find.byType(FilledButton),
        ),
      );
      await tester.pumpAndSettle();

      // Le dialogue doit encore être visible (il affiche le message « à venir »,
      // mais n'a jamais appelé Navigator.pop ni popUntil).
      expect(find.byType(AlertDialog), findsOneWidget);
    });

    testWidgets(
        'la validation ne navigue pas hors de l\'écran d\'accueil',
        (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);
      await _typeDigits(tester, 4);

      await tester.tap(
        find.ancestor(
          of: find.bySemanticsLabel('Valider'),
          matching: find.byType(FilledButton),
        ),
      );
      await tester.pumpAndSettle();

      // L'écran d'accueil (home: route initiale) doit être dans l'arbre.
      expect(find.text('Ouvrir maintenance'), findsOneWidget);
    });
  });

  group('showKioskExitGate — fermeture du dialogue', () {
    testWidgets('le bouton « Fermer » ferme le dialogue', (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();
      await tester.pumpWidget(_buildApp(navKey: navKey));
      await tester.pumpAndSettle();

      await _openDialog(tester);
      expect(find.byType(AlertDialog), findsOneWidget);

      await tester.tap(find.text('Fermer'));
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsNothing);
    });
  });

  group('showKioskExitGate — suspension du minuteur d\'inactivité', () {
    testWidgets(
        'le dialogue persiste au-delà du timeout (minuteur suspendu pendant la saisie)',
        (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();

      await tester.pumpWidget(
        _buildApp(navKey: navKey, timeout: const Duration(seconds: 5)),
      );
      await tester.pumpAndSettle();

      await _openDialog(tester);
      expect(find.byType(AlertDialog), findsOneWidget);

      // Avancer de 10 s (deux fois le timeout) — le minuteur doit rester suspendu.
      await tester.pump(const Duration(seconds: 10));
      await tester.pump();

      expect(
        find.byType(AlertDialog),
        findsOneWidget,
        reason:
            'Le dialogue doit rester ouvert : pauseForModal() suspend le minuteur '
            'sans plafond, un gérant ne doit pas être renvoyé à l\'accueil en pleine saisie.',
      );
    });

    testWidgets(
        'le minuteur reprend après fermeture : le retour auto a lieu après le timeout',
        (tester) async {
      _setTabletSurface(tester);
      final navKey = GlobalKey<NavigatorState>();

      await tester.pumpWidget(
        _buildApp(navKey: navKey, timeout: const Duration(seconds: 5)),
      );
      await tester.pumpAndSettle();

      // Pousser une deuxième page avec un marqueur distinct pour détecter le retour.
      const page2Tag = 'marqueur-page-2';
      navKey.currentState!.push(
        MaterialPageRoute<void>(
          builder: (ctx) => Scaffold(
            body: Column(
              children: <Widget>[
                const Text(page2Tag),
                ElevatedButton(
                  onPressed: () => showKioskExitGate(ctx),
                  child: const Text('Ouvrir maintenance'),
                ),
              ],
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Ouvrir puis fermer le dialogue depuis la page 2.
      await _openDialog(tester);
      await tester.tap(find.text('Fermer'));
      await tester.pumpAndSettle();

      // Avant le timeout, le marqueur de la page 2 est toujours visible.
      await tester.pump(const Duration(seconds: 4));
      expect(find.text(page2Tag), findsOneWidget);

      // Après le timeout, le minuteur ramène à l'accueil (page-2 dépilée).
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();

      expect(find.text(page2Tag), findsNothing);
    });
  });
}
