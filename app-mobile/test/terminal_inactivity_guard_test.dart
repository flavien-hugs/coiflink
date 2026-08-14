// Tests widget — TerminalInactivityGuard (US-8.5, #159).
//
// Couverture : retour automatique après le timeout d'inactivité ; réarmement
// sur évènement pointer ; pauseForPrinting (plafond de 15 s) ; resumeAfterPrinting
// (annule le plafond, reprend le minuteur normal) ; pauseForModal (sans plafond) ;
// resumeFromModal (reprend le minuteur) ; maybeOf (accès au contrôleur depuis l'arbre).
//
// Les timers sont pilotés de façon **déterministe** via `tester.pump(Duration)` —
// aucun `sleep` ni `Future.delayed` — conformément à la FakeAsync de flutter_test.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:coiflink_mobile/adapters/ui/terminal/terminal_inactivity_guard.dart';

// ---------------------------------------------------------------------------
// Pages de test minimalistes
// ---------------------------------------------------------------------------

class _HomePage extends StatelessWidget {
  const _HomePage();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(body: Center(child: Text('page-accueil')));
  }
}

class _SecondPage extends StatelessWidget {
  const _SecondPage({this.tag = 'page-2'});

  final String tag;

  @override
  Widget build(BuildContext context) {
    return Scaffold(body: Center(child: Text(tag)));
  }
}

// ---------------------------------------------------------------------------
// Helper : construit un MaterialApp avec TerminalInactivityGuard dans builder:
// ---------------------------------------------------------------------------

Widget _buildApp({
  required GlobalKey<NavigatorState> navKey,
  GlobalKey<TerminalInactivityGuardState>? guardKey,
  Duration timeout = const Duration(seconds: 5),
  Duration printSuspensionCap = const Duration(seconds: 3),
}) {
  return MaterialApp(
    navigatorKey: navKey,
    builder: (context, child) => TerminalInactivityGuard(
      key: guardKey,
      navigatorKey: navKey,
      timeout: timeout,
      printSuspensionCap: printSuspensionCap,
      child: child!,
    ),
    home: const _HomePage(),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

void main() {
  group('TerminalInactivityGuard — retour automatique', () {
    testWidgets('retour à l\'accueil après le timeout d\'inactivité', (tester) async {
      final navKey = GlobalKey<NavigatorState>();

      await tester.pumpWidget(_buildApp(navKey: navKey, timeout: const Duration(seconds: 5)));
      await tester.pumpAndSettle();

      navKey.currentState!.push(
        MaterialPageRoute<void>(builder: (_) => const _SecondPage()),
      );
      await tester.pumpAndSettle();

      expect(find.text('page-2'), findsOneWidget);

      // Timeout atteint → retour automatique
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();

      expect(find.text('page-accueil'), findsOneWidget);
      expect(find.text('page-2'), findsNothing);
    });

    testWidgets('un évènement pointer réarme le minuteur', (tester) async {
      final navKey = GlobalKey<NavigatorState>();

      await tester.pumpWidget(_buildApp(navKey: navKey, timeout: const Duration(seconds: 5)));
      await tester.pumpAndSettle();

      navKey.currentState!.push(
        MaterialPageRoute<void>(builder: (_) => const _SecondPage()),
      );
      await tester.pumpAndSettle();

      // Avancer à 4 s (avant le timeout de 5 s)
      await tester.pump(const Duration(seconds: 4));
      expect(find.text('page-2'), findsOneWidget);

      // Interaction → réarmement du minuteur
      await tester.tap(find.text('page-2'));

      // 4 s supplémentaires : le minuteur repart de zéro, pas encore expiré
      await tester.pump(const Duration(seconds: 4));
      expect(find.text('page-2'), findsOneWidget);

      // 1 s de plus → timeout atteint depuis la dernière interaction
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();

      expect(find.text('page-accueil'), findsOneWidget);
    });

    testWidgets('popUntil retourne à l\'accueil depuis plusieurs niveaux de navigation',
        (tester) async {
      final navKey = GlobalKey<NavigatorState>();

      await tester.pumpWidget(_buildApp(navKey: navKey, timeout: const Duration(seconds: 5)));
      await tester.pumpAndSettle();

      // Empile deux pages
      navKey.currentState!.push(
        MaterialPageRoute<void>(builder: (_) => const _SecondPage(tag: 'page-2')),
      );
      navKey.currentState!.push(
        MaterialPageRoute<void>(builder: (_) => const _SecondPage(tag: 'page-3')),
      );
      await tester.pumpAndSettle();

      expect(find.text('page-3'), findsOneWidget);

      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();

      expect(find.text('page-accueil'), findsOneWidget);
      expect(find.text('page-2'), findsNothing);
      expect(find.text('page-3'), findsNothing);
    });
  });

  group('TerminalInactivityGuard — pauseForPrinting', () {
    testWidgets('plafond déclenche le retour si resumeAfterPrinting n\'est pas appelé',
        (tester) async {
      final navKey = GlobalKey<NavigatorState>();
      final guardKey = GlobalKey<TerminalInactivityGuardState>();

      await tester.pumpWidget(
        _buildApp(
          navKey: navKey,
          guardKey: guardKey,
          timeout: const Duration(seconds: 60),
          printSuspensionCap: const Duration(seconds: 5),
        ),
      );
      await tester.pumpAndSettle();

      navKey.currentState!.push(
        MaterialPageRoute<void>(builder: (_) => const _SecondPage()),
      );
      await tester.pumpAndSettle();

      guardKey.currentState!.pauseForPrinting();

      // Avant le plafond (4 s sur 5) → toujours sur page 2
      await tester.pump(const Duration(seconds: 4));
      expect(find.text('page-2'), findsOneWidget);

      // Plafond atteint → retour automatique
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();

      expect(find.text('page-accueil'), findsOneWidget);
    });

    testWidgets('resumeAfterPrinting annule le plafond et reprend le minuteur normal',
        (tester) async {
      final navKey = GlobalKey<NavigatorState>();
      final guardKey = GlobalKey<TerminalInactivityGuardState>();

      await tester.pumpWidget(
        _buildApp(
          navKey: navKey,
          guardKey: guardKey,
          timeout: const Duration(seconds: 10),
          printSuspensionCap: const Duration(seconds: 5),
        ),
      );
      await tester.pumpAndSettle();

      navKey.currentState!.push(
        MaterialPageRoute<void>(builder: (_) => const _SecondPage()),
      );
      await tester.pumpAndSettle();

      guardKey.currentState!.pauseForPrinting();

      // 3 s après la suspension, appeler resumeAfterPrinting
      await tester.pump(const Duration(seconds: 3));
      guardKey.currentState!.resumeAfterPrinting();

      // Le plafond restant (2 s) ne doit pas déclencher le retour
      await tester.pump(const Duration(seconds: 2));
      await tester.pump();
      expect(find.text('page-2'), findsOneWidget);

      // Le minuteur normal (10 s depuis le resume) doit déclencher le retour
      await tester.pump(const Duration(seconds: 8));
      await tester.pumpAndSettle();

      expect(find.text('page-accueil'), findsOneWidget);
    });
  });

  group('TerminalInactivityGuard — pauseForModal', () {
    testWidgets('pauseForModal suspend le minuteur sans plafond', (tester) async {
      final navKey = GlobalKey<NavigatorState>();
      final guardKey = GlobalKey<TerminalInactivityGuardState>();

      await tester.pumpWidget(
        _buildApp(
          navKey: navKey,
          guardKey: guardKey,
          timeout: const Duration(seconds: 5),
        ),
      );
      await tester.pumpAndSettle();

      navKey.currentState!.push(
        MaterialPageRoute<void>(builder: (_) => const _SecondPage()),
      );
      await tester.pumpAndSettle();

      guardKey.currentState!.pauseForModal();

      // Bien au-delà du timeout (30 s) → aucun plafond, toujours sur page 2
      await tester.pump(const Duration(seconds: 30));
      await tester.pump();
      expect(find.text('page-2'), findsOneWidget);
    });

    testWidgets('resumeFromModal reprend le minuteur normal', (tester) async {
      final navKey = GlobalKey<NavigatorState>();
      final guardKey = GlobalKey<TerminalInactivityGuardState>();

      await tester.pumpWidget(
        _buildApp(
          navKey: navKey,
          guardKey: guardKey,
          timeout: const Duration(seconds: 5),
        ),
      );
      await tester.pumpAndSettle();

      navKey.currentState!.push(
        MaterialPageRoute<void>(builder: (_) => const _SecondPage()),
      );
      await tester.pumpAndSettle();

      guardKey.currentState!.pauseForModal();
      await tester.pump(const Duration(seconds: 10)); // hors timeout, mais suspendu

      guardKey.currentState!.resumeFromModal();

      // Timeout reprend depuis le resume (5 s)
      await tester.pump(const Duration(seconds: 4));
      expect(find.text('page-2'), findsOneWidget);

      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();

      expect(find.text('page-accueil'), findsOneWidget);
    });
  });

  group('TerminalInactivityGuard.maybeOf', () {
    testWidgets('retourne le contrôleur depuis un widget enfant', (tester) async {
      final navKey = GlobalKey<NavigatorState>();
      TerminalInactivityController? captured;

      await tester.pumpWidget(
        MaterialApp(
          navigatorKey: navKey,
          builder: (context, child) => TerminalInactivityGuard(
            navigatorKey: navKey,
            child: child!,
          ),
          home: Builder(
            builder: (context) {
              captured = TerminalInactivityGuard.maybeOf(context);
              return const SizedBox.shrink();
            },
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(captured, isA<TerminalInactivityController>());
    });

    testWidgets('retourne null hors d\'un TerminalInactivityGuard', (tester) async {
      TerminalInactivityController? captured;

      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) {
              captured = TerminalInactivityGuard.maybeOf(context);
              return const SizedBox.shrink();
            },
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(captured, isNull);
    });
  });

  group('TerminalInactivityGuard — onPointerMove', () {
    testWidgets('un évènement onPointerMove réarme également le minuteur',
        (tester) async {
      final navKey = GlobalKey<NavigatorState>();

      await tester.pumpWidget(_buildApp(navKey: navKey, timeout: const Duration(seconds: 5)));
      await tester.pumpAndSettle();

      navKey.currentState!.push(
        MaterialPageRoute<void>(builder: (_) => const _SecondPage()),
      );
      await tester.pumpAndSettle();

      // Avancer à 4 s (avant le timeout de 5 s)
      await tester.pump(const Duration(seconds: 4));
      expect(find.text('page-2'), findsOneWidget);

      // Simuler un déplacement — `tester.drag` génère onPointerDown + onPointerMove
      await tester.drag(find.text('page-2'), const Offset(0, 1));

      // 4 s supplémentaires depuis le move : minuteur reparti de zéro, pas encore expiré
      await tester.pump(const Duration(seconds: 4));
      expect(find.text('page-2'), findsOneWidget);

      // 1 s de plus → timeout atteint depuis le dernier move
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();

      expect(find.text('page-accueil'), findsOneWidget);
    });
  });

  group('TerminalInactivityGuard — suspension pendant l\'impression', () {
    testWidgets(
        'les interactions pendant pauseForPrinting ne réarment pas le minuteur principal',
        (tester) async {
      final navKey = GlobalKey<NavigatorState>();
      final guardKey = GlobalKey<TerminalInactivityGuardState>();

      await tester.pumpWidget(
        _buildApp(
          navKey: navKey,
          guardKey: guardKey,
          timeout: const Duration(seconds: 60),
          printSuspensionCap: const Duration(seconds: 5),
        ),
      );
      await tester.pumpAndSettle();

      navKey.currentState!.push(
        MaterialPageRoute<void>(builder: (_) => const _SecondPage()),
      );
      await tester.pumpAndSettle();

      // Démarrer la suspension d'impression (plafond : 5 s)
      guardKey.currentState!.pauseForPrinting();

      // Taper l'écran plusieurs fois pendant la suspension
      await tester.pump(const Duration(seconds: 2));
      await tester.tap(find.text('page-2'));
      await tester.pump(const Duration(seconds: 2));
      await tester.tap(find.text('page-2'));

      // Les taps ont été ignorés (_suspended) : le plafond de 5 s court toujours
      // depuis pauseForPrinting, pas depuis le dernier tap.
      // 1 s de plus → plafond atteint (5 s écoulées depuis pauseForPrinting)
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();

      // Le plafond a déclenché le retour automatique malgré les interactions.
      expect(find.text('page-accueil'), findsOneWidget);
    });
  });
}
