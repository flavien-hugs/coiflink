// État « borne indisponible » (US-8.5, #159 — résilience réseau, décision n°9).
//
// Repli affiché quand un appel réseau **bloquant** échoue de façon non récupérable
// par un simple réessai (ex. `GetSalonDetail` au démarrage, ou le login device) :
// message **neutre**, aucun détail technique, un bouton « Réessayer ». Les actions
// sensibles (identification, création de ticket) restent, elles, **toujours en
// direct** — jamais de mode dégradé (voir §G).

import 'package:flutter/material.dart';

import 'terminal_theme.dart';

class TerminalUnavailableScreen extends StatelessWidget {
  const TerminalUnavailableScreen({super.key, this.onRetry});

  /// Réessaie l'appel bloquant (recharge). `null` masque le bouton.
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final retry = onRetry;
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(TerminalDimensions.screenPadding),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: <Widget>[
              Icon(
                Icons.cloud_off,
                size: 96,
                color: theme.colorScheme.onSurfaceVariant,
              ),
              const SizedBox(height: TerminalDimensions.touchSpacing),
              Text(
                'La borne est momentanément indisponible.',
                textAlign: TextAlign.center,
                style: theme.textTheme.headlineSmall,
              ),
              if (retry != null) ...<Widget>[
                const SizedBox(height: TerminalDimensions.screenPadding),
                FilledButton.icon(
                  onPressed: retry,
                  icon: const Icon(Icons.refresh),
                  label: const Text('Réessayer'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
