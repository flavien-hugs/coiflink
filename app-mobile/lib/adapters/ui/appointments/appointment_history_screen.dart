// Écran UI : « Mon historique » — historique de prestations client (US-4.4, #30).
//
// Liste, **en lecture seule**, les RDV **terminés** (`COMPLETED`) du client (via
// `ListMyAppointmentHistory`) : date, horaires, statut « Terminé », prestations et
// leurs montants **figés** (`priceAtBooking`). Un RDV terminé est terminal (§8.1) :
// **aucune** action de modification/annulation. Le serveur ne renvoie que ses
// propres RDV terminés (statut forcé serveur — « rien d'autre »). Aucune règle métier
// ni appel HTTP direct ici ; le jeton n'est **jamais journalisé** (§11).

import 'package:flutter/material.dart';

import '../../../application/auth_session.dart';
import '../../../application/ports/appointment_gateway.dart';
import '../../../application/use_cases/list_my_appointment_history.dart';
import '../../../domain/appointment/appointment.dart';
import '../booking/booking_flow_screen.dart' show LoginRequester;
import '../booking/booking_labels.dart';

class AppointmentHistoryScreen extends StatefulWidget {
  const AppointmentHistoryScreen({
    super.key,
    required this.listMyAppointmentHistory,
    required this.session,
    required this.onRequireLogin,
  });

  final ListMyAppointmentHistory listMyAppointmentHistory;
  final AuthSession session;
  final LoginRequester onRequireLogin;

  @override
  State<AppointmentHistoryScreen> createState() =>
      _AppointmentHistoryScreenState();
}

class _AppointmentHistoryScreenState extends State<AppointmentHistoryScreen> {
  bool _loading = true;
  bool _needsLogin = false;
  String? _error;
  List<Appointment> _appointments = const <Appointment>[];

  @override
  void initState() {
    super.initState();
    _load();
  }

  // ------------------------------------------------------------------------- //
  // Chargement de l'historique du client (session requise).
  // ------------------------------------------------------------------------- //
  Future<void> _load() async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      _error = null;
      _needsLogin = false;
    });

    var token = await widget.session.currentToken();
    if (token == null) {
      if (!mounted) return;
      final ok = await widget.onRequireLogin(context);
      if (!ok) {
        _showNeedsLogin();
        return;
      }
      token = await widget.session.currentToken();
      if (token == null) {
        _showNeedsLogin();
        return;
      }
    }

    try {
      final items =
          await widget.listMyAppointmentHistory.call(accessToken: token);
      if (!mounted) return;
      setState(() {
        _appointments = items;
        _loading = false;
      });
    } on UnauthorizedException {
      // Jeton expiré : invalider la session locale, proposer de se reconnecter.
      await widget.session.clear();
      if (!mounted) return;
      setState(() {
        _loading = false;
        _needsLogin = true;
        _error = 'Session expirée, veuillez vous reconnecter.';
      });
    } on AppointmentGatewayException catch (exc) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = exc.message;
      });
    }
  }

  void _showNeedsLogin() {
    if (!mounted) return;
    setState(() {
      _loading = false;
      _needsLogin = true;
    });
  }

  // ------------------------------------------------------------------------- //
  // Rendu.
  // ------------------------------------------------------------------------- //
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Mon historique')),
      body: SafeArea(child: _buildBody()),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_needsLogin) {
      return _CenteredAction(
        message: _error ?? 'Connectez-vous pour voir votre historique.',
        actionLabel: 'Se connecter',
        onAction: _load,
      );
    }
    if (_error != null) {
      return _CenteredAction(
        message: _error!,
        actionLabel: 'Réessayer',
        onAction: _load,
      );
    }
    if (_appointments.isEmpty) {
      return const _CenteredMessage(
        'Vous n\'avez aucun rendez-vous terminé.',
      );
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: _appointments.length,
        separatorBuilder: (_, _) => const SizedBox(height: 12),
        itemBuilder: (context, index) =>
            _HistoryCard(appointment: _appointments[index]),
      ),
    );
  }
}

/// Carte d'historique **en lecture seule** : date, horaires, statut « Terminé » et
/// prestations réalisées avec leur montant figé. Aucun bouton d'action (§8.1).
class _HistoryCard extends StatelessWidget {
  const _HistoryCard({required this.appointment});

  final Appointment appointment;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(
                    formatFullDate(appointment.date),
                    style: theme.textTheme.titleMedium,
                  ),
                ),
                Chip(label: Text(appointment.status.label)),
              ],
            ),
            const SizedBox(height: 4),
            Text('${appointment.startTime} – ${appointment.endTime}'),
            if (appointment.services.isNotEmpty) ...<Widget>[
              const SizedBox(height: 12),
              for (final service in appointment.services)
                _ServiceLine(service: service),
            ],
          ],
        ),
      ),
    );
  }
}

/// Ligne d'une prestation réalisée : montant **figé** à droite (§ historique #30).
class _ServiceLine extends StatelessWidget {
  const _ServiceLine({required this.service});

  final BookedService service;

  @override
  Widget build(BuildContext context) {
    final price = service.priceAtBooking;
    final hasPrice = price != null && price.trim().isNotEmpty;
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Row(
        children: <Widget>[
          const Expanded(child: Text('Prestation')),
          if (hasPrice) Text('$price FCFA'),
        ],
      ),
    );
  }
}

class _CenteredMessage extends StatelessWidget {
  const _CenteredMessage(this.message);

  final String message;

  @override
  Widget build(BuildContext context) {
    // Une liste défilable garde le pull-to-refresh actif même quand elle est vide.
    return ListView(
      padding: const EdgeInsets.all(24),
      children: <Widget>[
        const SizedBox(height: 48),
        Text(message, textAlign: TextAlign.center),
      ],
    );
  }
}

class _CenteredAction extends StatelessWidget {
  const _CenteredAction({
    required this.message,
    required this.actionLabel,
    required this.onAction,
  });

  final String message;
  final String actionLabel;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: onAction, child: Text(actionLabel)),
          ],
        ),
      ),
    );
  }
}
