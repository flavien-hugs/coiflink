// Minuteur d'inactivité global de la borne (US-8.5, #159).
//
// Placé **une seule fois** au-dessus du `Navigator` du `MaterialApp` (via son
// `builder:`, voir `kiosk_app.dart`), il ramène systématiquement à l'accueil après
// 60 s sans interaction et purge l'état du parcours en cours — un écran poussé plus
// tard hérite de la détection sans avoir à l'envelopper.
//
// Mécanisme :
//  - `Listener` (et non `GestureDetector`) : reçoit les évènements de pointeur
//    **bruts** avant toute résolution d'arène de gestes, donc toute interaction —
//    y compris celle remportée par un `ListTile`/`TextField` descendant — réarme le
//    compte à rebours. `HitTestBehavior.translucent` : il observe, il ne consomme pas.
//  - `GlobalKey<NavigatorState>` : `popUntil((r) => r.isFirst)` revient à l'accueil
//    depuis n'importe quelle profondeur, sans compter les `pop()`.
//  - La purge d'état n'est **pas** un mécanisme séparé : rien du parcours walk-in
//    n'est écrit hors du `State` de l'écran courant (téléphone tapé, fiche
//    trouvée/créée, prestations sélectionnées) — revenir à la racine *est* la purge.
//    Le credential device (identité du terminal) n'est pas concerné : il est persisté
//    et survit délibérément au retour à l'accueil.

import 'dart:async';

import 'package:flutter/material.dart';

/// Commandes exposées aux écrans pour suspendre/reprendre le minuteur.
abstract class KioskInactivityController {
  /// Suspend le minuteur pendant l'impression du ticket, avec un **plafond**
  /// indépendant du signal de reprise : même si `resumeAfterPrinting()` n'est jamais
  /// rappelé (plantage du plugin d'impression), le retour à l'accueil a malgré tout
  /// lieu au bout du plafond.
  void pauseForPrinting();

  /// Reprend le minuteur normal après l'impression (succès **ou** échec).
  void resumeAfterPrinting();

  /// Suspend le minuteur pendant une interaction modale non-cliente (saisie du PIN
  /// gérant à la sortie du kiosque) — **sans** plafond : un gérant ne doit pas être
  /// renvoyé à l'accueil en pleine saisie. L'appelant garantit `resumeFromModal()`
  /// (via `try/finally`).
  void pauseForModal();

  /// Reprend le minuteur normal après une interaction modale.
  void resumeFromModal();
}

class KioskInactivityGuard extends StatefulWidget {
  const KioskInactivityGuard({
    super.key,
    required this.navigatorKey,
    required this.child,
    this.timeout = const Duration(seconds: 60),
    this.printSuspensionCap = const Duration(seconds: 15),
  });

  final GlobalKey<NavigatorState> navigatorKey;
  final Widget child;

  /// Délai d'inactivité avant retour automatique à l'accueil (décision n°7 : 60 s).
  final Duration timeout;

  /// Plafond de suspension pendant l'impression, indépendant du signal de reprise
  /// (décision n°7 : 15 s).
  final Duration printSuspensionCap;

  @override
  State<KioskInactivityGuard> createState() => KioskInactivityGuardState();

  /// Contrôleur du guard le plus proche, ou `null` hors d'un `KioskInactivityGuard`.
  static KioskInactivityController? maybeOf(BuildContext context) {
    return context
        .dependOnInheritedWidgetOfExactType<_KioskInactivityScope>()
        ?.controller;
  }
}

class KioskInactivityGuardState extends State<KioskInactivityGuard>
    implements KioskInactivityController {
  Timer? _timer;
  Timer? _suspensionCapTimer;
  bool _suspended = false;

  @override
  void initState() {
    super.initState();
    _resetTimer();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _suspensionCapTimer?.cancel();
    super.dispose();
  }

  void _resetTimer() {
    if (_suspended) return; // une suspension en cours ignore les resets normaux
    _timer?.cancel();
    _timer = Timer(widget.timeout, _returnToHome);
  }

  void _suspend() {
    _suspended = true;
    _timer?.cancel();
  }

  @override
  void pauseForPrinting() {
    _suspend();
    _suspensionCapTimer?.cancel();
    _suspensionCapTimer = Timer(widget.printSuspensionCap, _returnToHome);
  }

  @override
  void resumeAfterPrinting() {
    _suspensionCapTimer?.cancel();
    _suspended = false;
    _resetTimer();
  }

  @override
  void pauseForModal() {
    _suspend();
  }

  @override
  void resumeFromModal() {
    _suspended = false;
    _resetTimer();
  }

  void _returnToHome() {
    _suspended = false;
    _suspensionCapTimer?.cancel();
    widget.navigatorKey.currentState?.popUntil((route) => route.isFirst);
    _resetTimer();
  }

  @override
  Widget build(BuildContext context) {
    return Listener(
      behavior: HitTestBehavior.translucent, // ne vole aucun geste aux enfants
      onPointerDown: (_) => _resetTimer(),
      onPointerMove: (_) => _resetTimer(),
      child: _KioskInactivityScope(controller: this, child: widget.child),
    );
  }
}

/// Rend le contrôleur du guard accessible à tout écran poussé sous le `Navigator`.
class _KioskInactivityScope extends InheritedWidget {
  const _KioskInactivityScope({
    required this.controller,
    required super.child,
  });

  final KioskInactivityController controller;

  @override
  bool updateShouldNotify(_KioskInactivityScope oldWidget) =>
      controller != oldWidget.controller;
}
