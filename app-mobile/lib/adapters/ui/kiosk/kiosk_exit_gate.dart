// Sortie du mode kiosque — geste d'entrée (US-8.5, #159, périmètre volontairement limité).
//
// La décision produit n°11 exige que la sortie du mode kiosque et la maintenance
// soient « protégées par PIN gérant, journalisées ». #159 pose le **geste d'entrée**
// (appui long caché sur le logo d'accueil → dialogue de saisie réutilisant le pavé
// numérique) **sans trancher la vérification** (Option A : réutiliser `/auth/login` ;
// Option B : PIN local coordonné avec #161). Voir §H de la spec.
//
// Tant que la vérification n'est pas tranchée, ce geste reste **inerte** : il affiche
// un message « maintenance à venir » et **ne sort jamais** du mode kiosque sans
// vérification (Security & Privacy Considerations). Pendant la saisie, le minuteur
// d'inactivité est suspendu (`pauseForModal`) puis systématiquement repris (`finally`).

import 'package:flutter/material.dart';

import 'kiosk_inactivity_guard.dart';
import 'kiosk_numeric_keypad.dart';
import 'kiosk_theme.dart';

/// Longueur attendue du code de maintenance (affichage seulement — inerte à ce stade).
const int _kioskExitPinLength = 4;

/// Ouvre le dialogue de saisie du code de maintenance (geste de sortie du kiosque).
///
/// Suspend le minuteur d'inactivité le temps de la saisie et le reprend toujours.
Future<void> showKioskExitGate(BuildContext context) async {
  final guard = KioskInactivityGuard.maybeOf(context);
  guard?.pauseForModal();
  try {
    await showDialog<void>(
      context: context,
      barrierDismissible: true,
      builder: (context) => const _KioskExitDialog(),
    );
  } finally {
    guard?.resumeFromModal();
  }
}

class _KioskExitDialog extends StatefulWidget {
  const _KioskExitDialog();

  @override
  State<_KioskExitDialog> createState() => _KioskExitDialogState();
}

class _KioskExitDialogState extends State<_KioskExitDialog> {
  String _pin = '';
  bool _submitted = false;

  void _onDigit(String digit) {
    if (_pin.length >= _kioskExitPinLength) return;
    setState(() => _pin += digit);
  }

  void _onBackspace() {
    if (_pin.isEmpty) return;
    setState(() => _pin = _pin.substring(0, _pin.length - 1));
  }

  void _onSubmit() {
    // Inerte à ce stade (vérification non tranchée, §H) : jamais de sortie du mode
    // kiosque sans vérification — on affiche un message neutre et on ne fait rien
    // d'autre. Le code saisi n'est ni transmis ni journalisé.
    setState(() => _submitted = true);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AlertDialog(
      title: const Text('Accès maintenance'),
      content: SizedBox(
        width: 320,
        child: _submitted
            ? Text(
                'Fonctionnalité de maintenance à venir.',
                style: theme.textTheme.bodyLarge,
              )
            : Column(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  Text(
                    _pin.isEmpty
                        ? 'Saisissez le code gérant.'
                        : '•' * _pin.length,
                    style: theme.textTheme.headlineSmall,
                  ),
                  const SizedBox(height: KioskDimensions.touchSpacing),
                  KioskNumericKeypad(
                    onDigit: _onDigit,
                    onBackspace: _onBackspace,
                    onSubmit: _onSubmit,
                    submitEnabled: _pin.length == _kioskExitPinLength,
                  ),
                ],
              ),
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Fermer'),
        ),
      ],
    );
  }
}
