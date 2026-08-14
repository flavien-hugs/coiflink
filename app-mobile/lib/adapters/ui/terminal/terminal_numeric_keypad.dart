// Pavé numérique tactile réutilisable (US-8.5, #159).
//
// Grille de gros boutons 0-9 + correction + validation, chaque cible respectant les
// dimensions « gros boutons » (§D). Recommandé **spécifiquement pour le téléphone**
// (§F.2) : au-delà du confort tactile, un pavé **interne à l'app** évite de déclencher
// le clavier logiciel natif de l'OS pour un champ téléphone — ce qui évite, sur un
// terminal **public et partagé**, toute suggestion/autocomplétion de numéros
// précédemment saisis par un autre client via l'IME natif (§11.3).
//
// Widget **contrôlé** : il ne conserve aucun état ; le parent tient la chaîne saisie
// et réagit à `onDigit`/`onBackspace`/`onSubmit`.

import 'package:flutter/material.dart';

import 'terminal_theme.dart';

class TerminalNumericKeypad extends StatelessWidget {
  const TerminalNumericKeypad({
    super.key,
    required this.onDigit,
    required this.onBackspace,
    this.onSubmit,
    this.submitEnabled = true,
    this.submitLabel = 'Valider',
  });

  /// Appelé avec le chiffre tapé (« 0 » … « 9 »).
  final ValueChanged<String> onDigit;

  /// Appelé sur la touche de correction (efface le dernier chiffre).
  final VoidCallback onBackspace;

  /// Appelé sur la touche de validation, ou `null` pour la masquer.
  final VoidCallback? onSubmit;

  /// Active/désactive la touche de validation (ex. numéro trop court).
  final bool submitEnabled;

  final String submitLabel;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        for (final row in const <List<String>>[
          <String>['1', '2', '3'],
          <String>['4', '5', '6'],
          <String>['7', '8', '9'],
        ])
          _row(<Widget>[for (final digit in row) _digitKey(digit)]),
        _row(<Widget>[
          _actionKey(
            icon: Icons.backspace_outlined,
            semanticLabel: 'Effacer',
            onPressed: onBackspace,
          ),
          _digitKey('0'),
          if (onSubmit != null)
            _actionKey(
              icon: Icons.check,
              semanticLabel: submitLabel,
              onPressed: submitEnabled ? onSubmit : null,
              filled: true,
            )
          else
            const Expanded(child: SizedBox.shrink()),
        ]),
      ],
    );
  }

  Widget _row(List<Widget> children) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: TerminalDimensions.touchSpacing / 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: <Widget>[
          for (var i = 0; i < children.length; i++) ...<Widget>[
            if (i > 0) const SizedBox(width: TerminalDimensions.touchSpacing),
            children[i],
          ],
        ],
      ),
    );
  }

  Widget _digitKey(String digit) {
    return Expanded(
      child: SizedBox(
        height: TerminalDimensions.primaryButtonHeight,
        child: OutlinedButton(
          onPressed: () => onDigit(digit),
          child: Text(
            digit,
            style: const TextStyle(
              fontSize: 30,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ),
    );
  }

  Widget _actionKey({
    required IconData icon,
    required String semanticLabel,
    required VoidCallback? onPressed,
    bool filled = false,
  }) {
    final child = Icon(icon, size: 30, semanticLabel: semanticLabel);
    return Expanded(
      child: SizedBox(
        height: TerminalDimensions.primaryButtonHeight,
        child: filled
            ? FilledButton(onPressed: onPressed, child: child)
            : OutlinedButton(onPressed: onPressed, child: child),
      ),
    );
  }
}
