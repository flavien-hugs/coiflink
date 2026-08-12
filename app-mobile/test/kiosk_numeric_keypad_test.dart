// Tests widget — KioskNumericKeypad (US-8.5, #159).
//
// Couverture : chaque touche 0-9 appelle onDigit avec le bon chiffre ; la touche
// correction appelle onBackspace ; la touche validation est visible uniquement
// quand onSubmit est fourni ; elle est activée / désactivée par submitEnabled ;
// le libellé sémantique de validation est personnalisable.
//
// `KioskNumericKeypad` est un widget **contrôlé** (stateless) : le parent tient
// la chaîne saisie. Les tests pilotent les callbacks directement.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/kiosk/kiosk_numeric_keypad.dart';

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

Widget _buildKeypad({
  required ValueChanged<String> onDigit,
  required VoidCallback onBackspace,
  VoidCallback? onSubmit,
  bool submitEnabled = true,
  String submitLabel = 'Valider',
}) {
  return MaterialApp(
    home: Scaffold(
      body: KioskNumericKeypad(
        onDigit: onDigit,
        onBackspace: onBackspace,
        onSubmit: onSubmit,
        submitEnabled: submitEnabled,
        submitLabel: submitLabel,
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('KioskNumericKeypad — touches chiffres', () {
    for (final digit in <String>['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']) {
      testWidgets('tap "$digit" → onDigit("$digit")', (tester) async {
        String? captured;
        await tester.pumpWidget(
          _buildKeypad(
            onDigit: (d) => captured = d,
            onBackspace: () {},
          ),
        );
        await tester.pumpAndSettle();

        await tester.tap(find.widgetWithText(OutlinedButton, digit));
        await tester.pump();

        expect(captured, digit);
      });
    }
  });

  group('KioskNumericKeypad — touche correction', () {
    testWidgets('tap backspace appelle onBackspace', (tester) async {
      var backspaceCalled = false;
      await tester.pumpWidget(
        _buildKeypad(
          onDigit: (_) {},
          onBackspace: () => backspaceCalled = true,
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.bySemanticsLabel('Effacer'));
      await tester.pump();

      expect(backspaceCalled, isTrue);
    });
  });

  group('KioskNumericKeypad — touche validation', () {
    testWidgets('visible quand onSubmit est fourni', (tester) async {
      await tester.pumpWidget(
        _buildKeypad(
          onDigit: (_) {},
          onBackspace: () {},
          onSubmit: () {},
        ),
      );
      await tester.pumpAndSettle();

      expect(find.bySemanticsLabel('Valider'), findsOneWidget);
    });

    testWidgets('absente (SizedBox) quand onSubmit est null', (tester) async {
      await tester.pumpWidget(
        _buildKeypad(
          onDigit: (_) {},
          onBackspace: () {},
          // onSubmit non fourni
        ),
      );
      await tester.pumpAndSettle();

      expect(find.bySemanticsLabel('Valider'), findsNothing);
    });

    testWidgets('désactivée quand submitEnabled est false', (tester) async {
      await tester.pumpWidget(
        _buildKeypad(
          onDigit: (_) {},
          onBackspace: () {},
          onSubmit: () {},
          submitEnabled: false,
        ),
      );
      await tester.pumpAndSettle();

      // Le FilledButton contenant l'icône de validation doit avoir onPressed == null.
      final submitButton = tester.widget<FilledButton>(
        find.ancestor(
          of: find.bySemanticsLabel('Valider'),
          matching: find.byType(FilledButton),
        ),
      );
      expect(submitButton.onPressed, isNull);
    });

    testWidgets('activée quand submitEnabled est true', (tester) async {
      var submitted = false;
      await tester.pumpWidget(
        _buildKeypad(
          onDigit: (_) {},
          onBackspace: () {},
          onSubmit: () => submitted = true,
          submitEnabled: true,
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.bySemanticsLabel('Valider'));
      await tester.pump();

      expect(submitted, isTrue);
    });

    testWidgets('le libellé sémantique personnalisé est appliqué', (tester) async {
      await tester.pumpWidget(
        _buildKeypad(
          onDigit: (_) {},
          onBackspace: () {},
          onSubmit: () {},
          submitLabel: 'Rechercher',
        ),
      );
      await tester.pumpAndSettle();

      expect(find.bySemanticsLabel('Rechercher'), findsOneWidget);
      expect(find.bySemanticsLabel('Valider'), findsNothing);
    });
  });

  group('KioskNumericKeypad — interactions enchaînées', () {
    testWidgets('chaque digit tapé appelle onDigit avec la bonne valeur',
        (tester) async {
      final captured = <String>[];
      await tester.pumpWidget(
        _buildKeypad(
          onDigit: captured.add,
          onBackspace: () {},
        ),
      );
      await tester.pumpAndSettle();

      for (final d in <String>['3', '7', '0']) {
        await tester.tap(find.widgetWithText(OutlinedButton, d));
        await tester.pump();
      }

      expect(captured, <String>['3', '7', '0']);
    });
  });
}
