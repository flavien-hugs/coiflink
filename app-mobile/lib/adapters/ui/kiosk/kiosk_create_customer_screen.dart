// Création de fiche walk-in (US-003, #159 · consomme #156).
//
// Formulaire minimal : prénom, nom, téléphone (repris de l'écran précédent,
// **non modifiable**). Saisie alphabétique → clavier logiciel standard (un pavé
// numérique ne conviendrait pas ; cet écran n'est emprunté que par les **nouveaux**
// clients). Appelle `identityGateway.createCustomer(...)` (#156, trois champs
// requis, **sans mot de passe**) puis enchaîne vers le choix de prestation.

import 'package:flutter/material.dart';

import '../../../application/ports/kiosk_identity_gateway.dart';
import 'kiosk_deps.dart';
import 'kiosk_service_selection_screen.dart';
import 'kiosk_theme.dart';
import 'kiosk_widgets.dart';

class KioskCreateCustomerScreen extends StatefulWidget {
  const KioskCreateCustomerScreen({
    super.key,
    required this.deps,
    required this.phone,
  });

  final KioskDeps deps;
  final String phone;

  @override
  State<KioskCreateCustomerScreen> createState() =>
      _KioskCreateCustomerScreenState();
}

class _KioskCreateCustomerScreenState extends State<KioskCreateCustomerScreen> {
  final TextEditingController _firstName = TextEditingController();
  final TextEditingController _lastName = TextEditingController();

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
      );
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => KioskServiceSelectionScreen(
            deps: widget.deps,
            customerProfileId: identity.customerId,
            customerFirstName: identity.firstName,
          ),
        ),
      );
    } on KioskCustomerAlreadyExistsException {
      if (!mounted) return;
      // Course rare (fiche créée entre-temps) : inviter à revenir à l'identification.
      setState(() {
        _error = 'Une fiche existe déjà pour ce numéro. Revenez à '
            "l'identification pour la retrouver.";
        _submitting = false;
      });
    } on KioskIdentityException catch (exc) {
      if (!mounted) return;
      setState(() {
        _error = exc.message;
        _submitting = false;
      });
    }
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
                KioskDimensions.screenPadding,
                72,
                KioskDimensions.screenPadding,
                KioskDimensions.screenPadding,
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
                      ?.copyWith(color: KioskColors.muted),
                ),
                const SizedBox(height: KioskDimensions.screenPadding),
                TextField(
                  controller: _firstName,
                  textCapitalization: TextCapitalization.words,
                  onChanged: (_) => setState(() {}),
                  style: const TextStyle(fontSize: KioskDimensions.bodyFontSize),
                  decoration: const InputDecoration(
                    labelText: 'Prénom',
                    prefixIcon: Icon(Icons.person_outline),
                  ),
                ),
                const SizedBox(height: KioskDimensions.touchSpacing),
                TextField(
                  controller: _lastName,
                  textCapitalization: TextCapitalization.words,
                  onChanged: (_) => setState(() {}),
                  style: const TextStyle(fontSize: KioskDimensions.bodyFontSize),
                  decoration: const InputDecoration(
                    labelText: 'Nom',
                    prefixIcon: Icon(Icons.badge_outlined),
                  ),
                ),
                const SizedBox(height: KioskDimensions.touchSpacing),
                TextField(
                  // Téléphone repris de l'écran précédent, **non modifiable** ici.
                  enabled: false,
                  controller: TextEditingController(text: widget.phone),
                  style: const TextStyle(fontSize: KioskDimensions.bodyFontSize),
                  decoration: const InputDecoration(
                    labelText: 'Téléphone',
                    prefixIcon: Icon(Icons.phone_outlined),
                  ),
                ),
                if (_error != null) ...<Widget>[
                  const SizedBox(height: KioskDimensions.touchSpacing),
                  Text(
                    _error!,
                    style: TextStyle(color: theme.colorScheme.error),
                  ),
                ],
                const SizedBox(height: KioskDimensions.screenPadding),
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
                      ?.copyWith(color: KioskColors.muted),
                ),
              ],
            ),
          ),
          const KioskBackButton(),
        ],
      ),
    );
  }
}
