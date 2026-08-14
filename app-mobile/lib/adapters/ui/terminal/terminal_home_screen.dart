// Écran d'accueil de la borne (US-001, #159).
//
// Affiche le logo/nom du salon (via `GetSalonDetail`, avec repli sur l'asset local
// générique si le réseau ou le logo distant échoue), un unique CTA « Commencer » vers
// l'identification, et un point d'ancrage **discret** de sortie du mode terminal
// (appui long sur le logo, §H). Si `GetSalonDetail` échoue, bascule vers
// `TerminalUnavailableScreen` (décision n°9) plutôt que d'afficher un salon vide.

import 'dart:async';

import 'package:flutter/material.dart';

import '../../../application/ports/salon_catalog_gateway.dart';
import '../../../domain/salon/salon_detail.dart';
import 'terminal_deps.dart';
import 'terminal_exit_gate.dart';
import 'terminal_phone_identification_screen.dart';
import 'terminal_theme.dart';
import 'terminal_unavailable_screen.dart';

/// Asset de repli hors-ligne (premier asset local du paquet, décision n°8).
const String terminalFallbackLogoAsset = 'assets/images/terminal_logo_fallback.png';

class TerminalHomeScreen extends StatefulWidget {
  const TerminalHomeScreen({super.key, required this.deps});

  final TerminalDeps deps;

  @override
  State<TerminalHomeScreen> createState() => _TerminalHomeScreenState();
}

class _TerminalHomeScreenState extends State<TerminalHomeScreen> {
  SalonDetail? _detail;
  bool _loading = true;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
    // Connexion imprimante **proactive** (§E/§F.1) : établie dès l'accueil pour que
    // le plafond de 15 s de l'impression (US-007) ne soit pas consommé par une
    // reconnexion. Best-effort : un échec ici ne bloque pas le parcours.
    unawaited(widget.deps.printerGateway.connect());
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _failed = false;
    });
    try {
      final detail = await widget.deps.getSalonDetail.call(widget.deps.salonId);
      if (!mounted) return;
      setState(() {
        _detail = detail;
        _loading = false;
      });
    } on SalonCatalogException {
      if (!mounted) return;
      setState(() {
        _failed = true;
        _loading = false;
      });
    }
  }

  void _start() {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => TerminalPhoneIdentificationScreen(deps: widget.deps),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_failed) {
      return TerminalUnavailableScreen(onRetry: _load);
    }
    if (_loading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }

    final theme = Theme.of(context);
    final salon = _detail;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(TerminalDimensions.screenPadding),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                // Appui long **caché** sur le logo = geste de sortie du terminal (§H) —
                // aucun bouton visible.
                GestureDetector(
                  onLongPress: () => showTerminalExitGate(context),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(24),
                    child: _logo(salon),
                  ),
                ),
                const SizedBox(height: 14),
                Text(
                  salon?.name ?? 'CoifLink',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.titleLarge
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 48),
                Text(
                  'Bienvenue !',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.displaySmall
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 10),
                Text(
                  'Bienvenue dans notre salon de coiffure.',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 12),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 340),
                  child: Text(
                    'Enregistrez-vous pour obtenir votre numéro de passage et '
                    'faciliter votre prise en charge.',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodyLarge
                        ?.copyWith(color: TerminalColors.muted),
                  ),
                ),
                const SizedBox(height: 48),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _start,
                    child: const Text('Commencer'),
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  "Touchez l'écran pour démarrer",
                  textAlign: TextAlign.center,
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: TerminalColors.muted),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _logo(SalonDetail? salon) {
    const double size = 120;
    final logoUrl = salon?.logoUrl;
    final fallback = Image.asset(
      terminalFallbackLogoAsset,
      width: size,
      height: size,
      fit: BoxFit.contain,
    );
    if (logoUrl == null || logoUrl.isEmpty) {
      return fallback;
    }
    return Image.network(
      logoUrl,
      width: size,
      height: size,
      fit: BoxFit.contain,
      // Logo distant injoignable / URL signée expirée → repli sur l'asset bundlé.
      errorBuilder: (context, error, stackTrace) => fallback,
    );
  }
}
