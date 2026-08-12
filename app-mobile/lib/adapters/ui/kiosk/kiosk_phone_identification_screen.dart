// Identification par téléphone (US-002, #159 · consomme #156).
//
// La saisie passe par un **pavé numérique interne** (`KioskNumericKeypad`), pas le
// clavier logiciel natif (§F.2/§11.3). Les deux états du parcours (US-002a saisie,
// US-002b fiche retrouvée) vivent dans le **même** écran/route — seul l'état
// `_found` bascule l'affichage, pas une navigation.
//
// À la validation, appelle `identityGateway.findByPhone(phone)` (#156) :
//  - **trouvé**   → affiche **uniquement le prénom** (jamais le nom complet ni le
//    téléphone), puis enchaîne **automatiquement** vers le choix de prestation
//    après un court délai (aucune confirmation manuelle, US-002b) ;
//  - **absent**   → écran de création de fiche ;
//  - **erreur réseau** → message neutre + « Réessayer », **sans** navigation auto
//    (identification « toujours en direct », décision n°9).

import 'dart:async';

import 'package:flutter/material.dart';

import '../../../application/ports/kiosk_identity_gateway.dart';
import 'kiosk_create_customer_screen.dart';
import 'kiosk_deps.dart';
import 'kiosk_numeric_keypad.dart';
import 'kiosk_service_selection_screen.dart';
import 'kiosk_theme.dart';
import 'kiosk_widgets.dart';

/// Nombre minimal de chiffres avant d'activer la recherche (garde-fou de frappe ;
/// la normalisation réelle du numéro reste côté backend, #156).
const int _minPhoneDigits = 8;

/// Délai avant l'enchaînement automatique une fois la fiche retrouvée (US-002b) —
/// assez court pour ne pas ralentir le parcours, assez long pour lire le prénom.
const Duration _foundTransitionDelay = Duration(milliseconds: 1100);

class KioskPhoneIdentificationScreen extends StatefulWidget {
  const KioskPhoneIdentificationScreen({super.key, required this.deps});

  final KioskDeps deps;

  @override
  State<KioskPhoneIdentificationScreen> createState() =>
      _KioskPhoneIdentificationScreenState();
}

class _KioskPhoneIdentificationScreenState
    extends State<KioskPhoneIdentificationScreen> {
  String _phone = '';
  bool _submitting = false;
  String? _error;

  /// Fiche trouvée : le parcours enchaîne seul vers le choix de prestation.
  WalkInIdentity? _found;
  Timer? _transitionTimer;

  bool get _canSubmit => _phone.length >= _minPhoneDigits && !_submitting;

  @override
  void dispose() {
    _transitionTimer?.cancel();
    super.dispose();
  }

  void _onDigit(String digit) {
    if (_submitting) return;
    setState(() {
      _phone += digit;
      _error = null;
    });
  }

  void _onBackspace() {
    if (_submitting || _phone.isEmpty) return;
    setState(() {
      _phone = _phone.substring(0, _phone.length - 1);
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
      final identity = await widget.deps.identityGateway.findByPhone(_phone);
      if (!mounted) return;
      if (identity == null) {
        // Absent : création de fiche (le téléphone est repris, non modifiable).
        setState(() => _submitting = false);
        _goToCreate();
        return;
      }
      setState(() {
        _found = identity;
        _submitting = false;
      });
      // Aucune confirmation manuelle (US-002b) : la fiche retrouvée enchaîne seule.
      _transitionTimer = Timer(_foundTransitionDelay, () {
        if (!mounted) return;
        _goToServices(identity);
      });
    } on KioskIdentityException catch (exc) {
      if (!mounted) return;
      setState(() {
        _error = exc.message;
        _submitting = false;
      });
    }
  }

  void _goToCreate() {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => KioskCreateCustomerScreen(
          deps: widget.deps,
          phone: _phone,
        ),
      ),
    );
  }

  void _goToServices(WalkInIdentity identity) {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute<void>(
        builder: (_) => KioskServiceSelectionScreen(
          deps: widget.deps,
          customerProfileId: identity.customerId,
          customerFirstName: identity.firstName,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final found = _found;
    return Scaffold(
      body: Stack(
        children: <Widget>[
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                KioskDimensions.screenPadding,
                72,
                KioskDimensions.screenPadding,
                KioskDimensions.screenPadding,
              ),
              child: found != null ? _foundPanel(found) : _entryPanel(),
            ),
          ),
          if (found == null) const KioskBackButton(),
        ],
      ),
    );
  }

  Widget _entryPanel() {
    final theme = Theme.of(context);
    return SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Text(
            'Votre numéro',
            textAlign: TextAlign.center,
            style: theme.textTheme.headlineSmall
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 6),
          Text(
            'Nous retrouvons votre fiche automatiquement.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(color: KioskColors.muted),
          ),
          const SizedBox(height: 28),
          Text(
            _phone.isEmpty ? '—' : _groupedPhone(_phone),
            style: theme.textTheme.displaySmall?.copyWith(
              fontWeight: FontWeight.bold,
              color: KioskColors.ink,
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
            KioskNumericKeypad(
              onDigit: _onDigit,
              onBackspace: _onBackspace,
              onSubmit: _submit,
              submitEnabled: _canSubmit,
              submitLabel: 'Rechercher',
            ),
        ],
      ),
    );
  }

  Widget _foundPanel(WalkInIdentity identity) {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          _InitialAvatar(firstName: identity.firstName),
          const SizedBox(height: KioskDimensions.touchSpacing),
          // **Prénom seul** — jamais le nom complet ni le téléphone (§11.3, miroir #156).
          Text(
            'Bonjour, ${identity.firstName} !',
            textAlign: TextAlign.center,
            style: theme.textTheme.headlineMedium
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 10),
          Text(
            'Nous préparons votre prise en charge…',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(color: KioskColors.muted),
          ),
          const SizedBox(height: 18),
          const _LoadingDots(),
        ],
      ),
    );
  }
}

/// Regroupe les chiffres par paires (« 07 12 34 56 78 ») — lisibilité sur un grand
/// écran, à distance de bras.
String _groupedPhone(String digits) {
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && i.isEven) buffer.write(' ');
    buffer.write(digits[i]);
  }
  return buffer.toString();
}

class _InitialAvatar extends StatelessWidget {
  const _InitialAvatar({required this.firstName});

  final String firstName;

  @override
  Widget build(BuildContext context) {
    final trimmed = firstName.trim();
    final letter = trimmed.isEmpty ? '?' : trimmed[0].toUpperCase();
    return Container(
      width: 72,
      height: 72,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: KioskColors.nude,
        shape: BoxShape.circle,
        border: Border.all(color: KioskColors.border, width: 2),
      ),
      child: Text(
        letter,
        style: Theme.of(context).textTheme.headlineMedium?.copyWith(
              color: KioskColors.accent,
              fontWeight: FontWeight.w600,
            ),
      ),
    );
  }
}

/// Trois puces d'attente statiques (opacité dégressive) — indique un enchaînement
/// en cours sans dépendre d'une animation (simplicité, cohérent avec la borne).
class _LoadingDots extends StatelessWidget {
  const _LoadingDots();

  @override
  Widget build(BuildContext context) {
    const opacities = <double>[0.9, 0.55, 0.3];
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        for (final opacity in opacities)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: KioskColors.gold.withValues(alpha: opacity),
              ),
            ),
          ),
      ],
    );
  }
}
