// Création de fiche walk-in (US-003, #159 · consomme #156).
//
// Formulaire minimal : prénom, nom, téléphone (repris de l'écran précédent,
// **non modifiable**), genre optionnel (Homme/Femme, #172). Saisie alphabétique →
// clavier logiciel standard (un pavé numérique ne conviendrait pas ; cet écran
// n'est emprunté que par les **nouveaux** clients). Appelle
// `identityGateway.createCustomer(...)` (#156/#172, prénom/nom/téléphone requis,
// genre optionnel, **sans mot de passe**) puis enchaîne vers le choix de prestation.

import 'package:flutter/material.dart';

import '../../../application/ports/terminal_identity_gateway.dart';
import '../../../domain/customer/walk_in_gender.dart';
import 'terminal_deps.dart';
import 'terminal_service_selection_screen.dart';
import 'terminal_theme.dart';
import 'terminal_widgets.dart';

class TerminalCreateCustomerScreen extends StatefulWidget {
  const TerminalCreateCustomerScreen({
    super.key,
    required this.deps,
    required this.phone,
  });

  final TerminalDeps deps;
  final String phone;

  @override
  State<TerminalCreateCustomerScreen> createState() =>
      _TerminalCreateCustomerScreenState();
}

class _TerminalCreateCustomerScreenState extends State<TerminalCreateCustomerScreen> {
  final TextEditingController _firstName = TextEditingController();
  final TextEditingController _lastName = TextEditingController();

  WalkInGender? _gender;
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _firstName.dispose();
    _lastName.dispose();
    super.dispose();
  }

  bool get _canSubmit =>
      _firstName.text.trim().isNotEmpty &&
      _lastName.text.trim().isNotEmpty &&
      !_submitting;

  Future<void> _submit() async {
    if (!_canSubmit) return;
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final identity = await widget.deps.identityGateway.createCustomer(
        firstName: _firstName.text.trim(),
        lastName: _lastName.text.trim(),
        phone: widget.phone,
        gender: _gender,
      );
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => TerminalServiceSelectionScreen(
            deps: widget.deps,
            customerProfileId: identity.customerId,
            customerFirstName: identity.firstName,
          ),
        ),
      );
    } on TerminalCustomerAlreadyExistsException {
      if (!mounted) return;
      // Course rare (fiche créée entre-temps) : inviter à revenir à l'identification.
      setState(() {
        _error = 'Une fiche existe déjà pour ce numéro. Revenez à '
            "l'identification pour la retrouver.";
        _submitting = false;
      });
    } on TerminalIdentityException catch (exc) {
      if (!mounted) return;
      setState(() {
        _error = exc.message;
        _submitting = false;
      });
    }
  }

  /// Retaper l'option déjà sélectionnée la désélectionne (retour à `null`) —
  /// cohérent avec le caractère optionnel du champ (#172).
  void _onGenderTap(WalkInGender value) {
    setState(() => _gender = _gender == value ? null : value);
  }

  Widget _genderOption({required String label, required WalkInGender value}) {
    final selected = _gender == value;
    return selected
        ? FilledButton(
            onPressed: _submitting ? null : () => _onGenderTap(value),
            child: Text(label),
          )
        : OutlinedButton(
            onPressed: _submitting ? null : () => _onGenderTap(value),
            child: Text(label),
          );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: Stack(
        children: <Widget>[
          SafeArea(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(
                TerminalDimensions.screenPadding,
                72,
                TerminalDimensions.screenPadding,
                TerminalDimensions.screenPadding,
              ),
              children: <Widget>[
                Text(
                  'Faisons connaissance',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.headlineSmall
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 6),
                Text(
                  'Quelques informations pour créer votre fiche.',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodyMedium
                      ?.copyWith(color: TerminalColors.muted),
                ),
                const SizedBox(height: TerminalDimensions.screenPadding),
                TextField(
                  controller: _firstName,
                  textCapitalization: TextCapitalization.words,
                  onChanged: (_) => setState(() {}),
                  style: const TextStyle(fontSize: TerminalDimensions.bodyFontSize),
                  decoration: const InputDecoration(
                    labelText: 'Prénom',
                    prefixIcon: Icon(Icons.person_outline),
                  ),
                ),
                const SizedBox(height: TerminalDimensions.touchSpacing),
                TextField(
                  controller: _lastName,
                  textCapitalization: TextCapitalization.words,
                  onChanged: (_) => setState(() {}),
                  style: const TextStyle(fontSize: TerminalDimensions.bodyFontSize),
                  decoration: const InputDecoration(
                    labelText: 'Nom',
                    prefixIcon: Icon(Icons.badge_outlined),
                  ),
                ),
                const SizedBox(height: TerminalDimensions.touchSpacing),
                Text(
                  'Genre (optionnel)',
                  style: theme.textTheme.labelLarge?.copyWith(color: TerminalColors.muted),
                ),
                const SizedBox(height: 8),
                Row(
                  children: <Widget>[
                    Expanded(
                      child: _genderOption(
                        label: 'Femme',
                        value: WalkInGender.female,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: _genderOption(
                        label: 'Homme',
                        value: WalkInGender.male,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: TerminalDimensions.touchSpacing),
                TextField(
                  // Téléphone repris de l'écran précédent, **non modifiable** ici.
                  enabled: false,
                  controller: TextEditingController(text: widget.phone),
                  style: const TextStyle(fontSize: TerminalDimensions.bodyFontSize),
                  decoration: const InputDecoration(
                    labelText: 'Téléphone',
                    prefixIcon: Icon(Icons.phone_outlined),
                  ),
                ),
                if (_error != null) ...<Widget>[
                  const SizedBox(height: TerminalDimensions.touchSpacing),
                  Text(
                    _error!,
                    style: TextStyle(color: theme.colorScheme.error),
                  ),
                ],
                const SizedBox(height: TerminalDimensions.screenPadding),
                FilledButton(
                  onPressed: _canSubmit ? _submit : null,
                  child: _submitting
                      ? const SizedBox(
                          height: 24,
                          width: 24,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Valider'),
                ),
                const SizedBox(height: 12),
                Text(
                  'Clavier tactile standard à l\'écran',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: TerminalColors.muted),
                ),
              ],
            ),
          ),
          const TerminalBackButton(),
        ],
      ),
    );
  }
}
