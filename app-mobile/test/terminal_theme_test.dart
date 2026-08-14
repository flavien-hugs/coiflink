// Tests — buildTerminalTheme (US-8.5, #159).
//
// Couverture : chaque style du TextTheme a un `fontSize` non nul — régression
// directe sur le bug qui a provoqué le crash au lancement réel de l'app
// (`TextTheme.apply(fontSizeFactor: …)` avec un facteur ≠ 1.0 échoue à l'exécution
// sur tout style à `fontSize` nul ; aucun test d'écran ne le détectait puisque
// ceux-ci pompent `MaterialApp` sans passer `theme:`).
//
// Test **synchrone et pur** — pas de `testWidgets`, pas de pompage de widget : le
// chargement réseau de `google_fonts` (fire-and-forget, non attendu par le paquet
// lui-même) rend tout test qui pompe un widget avec ce thème non déterministe dans
// un environnement sans accès à fonts.gstatic.com. Ce test n'a besoin d'aucun accès
// réseau : il inspecte uniquement les propriétés du `TextTheme` retourné.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/terminal/terminal_theme.dart';

void main() {
  // Requis pour que l'accès à `rootBundle`/`ServicesBinding.instance` (déclenché
  // en interne par `google_fonts` lors du chargement de police) ne lève pas en
  // l'absence de binding Flutter initialisé — un `test()` nu n'en crée aucun.
  TestWidgetsFlutterBinding.ensureInitialized();

  test('chaque style du TextTheme a un fontSize non nul', () {
    final textTheme = buildTerminalTheme().textTheme;
    final styles = <String, TextStyle?>{
      'displayLarge': textTheme.displayLarge,
      'displayMedium': textTheme.displayMedium,
      'displaySmall': textTheme.displaySmall,
      'headlineLarge': textTheme.headlineLarge,
      'headlineMedium': textTheme.headlineMedium,
      'headlineSmall': textTheme.headlineSmall,
      'titleLarge': textTheme.titleLarge,
      'titleMedium': textTheme.titleMedium,
      'titleSmall': textTheme.titleSmall,
      'bodyLarge': textTheme.bodyLarge,
      'bodyMedium': textTheme.bodyMedium,
      'bodySmall': textTheme.bodySmall,
      'labelLarge': textTheme.labelLarge,
      'labelMedium': textTheme.labelMedium,
      'labelSmall': textTheme.labelSmall,
    };

    for (final entry in styles.entries) {
      expect(
        entry.value?.fontSize,
        isNotNull,
        reason: '${entry.key} a un fontSize nul — ferait échouer '
            'TextTheme.apply(fontSizeFactor: …) au premier rendu réel.',
      );
    }
  });
}
