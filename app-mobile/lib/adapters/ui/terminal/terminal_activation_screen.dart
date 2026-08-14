// Activation de la borne par code à 6 chiffres (US-8.5, #159 · consomme #155).
//
// Écran affiché **une seule fois**, au tout premier lancement (tant qu'aucun
// credential n'est stocké localement, voir `terminal_bootstrap.dart`). Le gérant lit
// le code d'activation sur la réponse de provisioning (outillage backend, hors
// périmètre de ce paquet) et le tape ici — pavé numérique interne, comme
// l'identification client (§F.2), jamais le clavier natif sur un terminal public.
//
// À la validation, échange le code contre le credential device
// (`TerminalActivationGateway`, `POST /auth/terminal/activate`) et le persiste
// (`TerminalCredentialStore`) avant d'appeler `onActivated` : la borne ne redemandera
// plus jamais ce code. Erreur (code invalide/expiré/déjà utilisé/réseau) → message
// neutre + réessai, **sans** navigation automatique (décision n°9, « toujours en
// direct »).

import 'package:flutter/material.dart';

import '../../../application/ports/terminal_activation_gateway.dart';
import '../../../application/ports/terminal_auth_gateway.dart';
import '../../../application/ports/terminal_credential_store.dart';
import 'terminal_numeric_keypad.dart';
import 'terminal_theme.dart';

/// Longueur du code d'activation (miroir du backend, #155).
const int _activationCodeLength = 6;

class TerminalActivationScreen extends StatefulWidget {
  const TerminalActivationScreen({
    super.key,
    required this.activationGateway,
    required this.credentialStore,
    required this.onActivated,
  });

  final TerminalActivationGateway activationGateway;
  final TerminalCredentialStore credentialStore;

  /// Appelé une fois le credential obtenu **et** persisté avec succès.
  final ValueChanged<TerminalCredential> onActivated;

  @override
  State<TerminalActivationScreen> createState() => _TerminalActivationScreenState();
}

class _TerminalActivationScreenState extends State<TerminalActivationScreen> {
  String _code = '';
  bool _submitting = false;
  String? _error;

  bool get _canSubmit => _code.length == _activationCodeLength && !_submitting;

  void _onDigit(String digit) {
    if (_submitting || _code.length >= _activationCodeLength) return;
    setState(() {
      _code += digit;
      _error = null;
    });
  }

  void _onBackspace() {
    if (_submitting || _code.isEmpty) return;
    setState(() {
      _code = _code.substring(0, _code.length - 1);
      _error = null;
    });
  }

  Future<void> _submit() async {
    if (!_canSubmit) return;
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final credential = await widget.activationGateway.activate(_code);
      await widget.credentialStore.save(credential);
      if (!mounted) return;
      widget.onActivated(credential);
    } on TerminalActivationException catch (exc) {
      if (!mounted) return;
      setState(() {
        _error = exc.message;
        _submitting = false;
        _code = '';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(TerminalDimensions.screenPadding),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(
                  'Activation de la borne',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.headlineSmall
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 6),
                Text(
                  "Saisissez le code d'activation à 6 chiffres remis lors de "
                  "l'installation.",
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodyMedium
                      ?.copyWith(color: TerminalColors.muted),
                ),
                const SizedBox(height: 28),
                Text(
                  _code.isEmpty ? '—' : _code,
                  style: theme.textTheme.displaySmall?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: TerminalColors.ink,
                    letterSpacing: 8,
                  ),
                ),
                if (_error != null) ...<Widget>[
                  const SizedBox(height: 12),
                  Text(
                    _error!,
                    textAlign: TextAlign.center,
                    style: TextStyle(color: theme.colorScheme.error),
                  ),
                ],
                const SizedBox(height: 28),
                if (_submitting)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: CircularProgressIndicator(),
                  )
                else
                  TerminalNumericKeypad(
                    onDigit: _onDigit,
                    onBackspace: _onBackspace,
                    onSubmit: _submit,
                    submitEnabled: _canSubmit,
                    submitLabel: 'Activer',
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
