// Écran UI : « Mes rendez-vous » & point d'entrée de modification (US-3.2, #23).
//
// Liste les RDV **actifs** du client (via `ListMyAppointments`) et ouvre le tunnel
// de réservation en mode *modification* pour un RDV modifiable. Le bouton
// « Modifier » est **désactivé** pour un RDV terminé/terminal (`!isClientModifiable`),
// avec une mention explicite — le verrou serveur (§8.1) reste juge, l'UI n'est
// qu'un confort. Aucune règle métier ni appel HTTP direct ici ; le jeton n'est
// **jamais journalisé** (§11).

import 'package:flutter/material.dart';

import '../../../application/auth_session.dart';
import '../../../application/ports/appointment_gateway.dart';
import '../../../application/use_cases/list_my_appointments.dart';
import '../../../domain/appointment/appointment.dart';
import '../booking/booking_flow_screen.dart' show LoginRequester;
import '../booking/booking_labels.dart';

/// Ouvre le flux de modification pour [appointment] ; retourne `true` si le RDV a
/// été modifié (la liste se rafraîchit alors). Câblé par le composition root
/// (charge la fiche salon puis pousse le tunnel pré-rempli) ; injectable en test.
typedef AppointmentModifier = Future<bool?> Function(
  BuildContext context,
  Appointment appointment,
);

/// Annule [appointment] avec un motif optionnel, authentifié par [accessToken]
/// (miroir de la signature du use case `CancelAppointment.call`). Câblé par le
/// composition root ; injectable en test par un faux. Propage les exceptions
/// **neutres** du port (`NotCancellableException`, `UnauthorizedException`, …) que
/// l'écran traduit en messages/rafraîchissement.
typedef AppointmentCanceller = Future<Appointment> Function({
  required Appointment appointment,
  String? reason,
  required String accessToken,
});

class MyAppointmentsScreen extends StatefulWidget {
  const MyAppointmentsScreen({
    super.key,
    required this.listMyAppointments,
    required this.session,
    required this.onRequireLogin,
    this.onModify,
    this.onCancel,
  });

  final ListMyAppointments listMyAppointments;
  final AuthSession session;
  final LoginRequester onRequireLogin;

  /// Ouvre le tunnel de modification ; `null` désactive la modification (lecture
  /// seule). Retourne `true` si le RDV a été modifié.
  final AppointmentModifier? onModify;

  /// Annule un RDV (motif optionnel) ; `null` désactive l'annulation (lecture
  /// seule). L'écran gère la confirmation, le motif facultatif et les issues.
  final AppointmentCanceller? onCancel;

  @override
  State<MyAppointmentsScreen> createState() => _MyAppointmentsScreenState();
}

class _MyAppointmentsScreenState extends State<MyAppointmentsScreen> {
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
  // Chargement des RDV du client (session requise).
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
      final items = await widget.listMyAppointments.call(accessToken: token);
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

  Future<void> _onModifyTap(Appointment appointment) async {
    final modifier = widget.onModify;
    if (modifier == null) return;
    final changed = await modifier(context, appointment);
    if (!mounted) return;
    if (changed == true) {
      _showMessage('Rendez-vous mis à jour.');
      await _load();
    }
  }

  // ------------------------------------------------------------------------- //
  // Annulation d'un RDV (US-3.3, #24) : confirmation + motif facultatif.
  // ------------------------------------------------------------------------- //
  Future<void> _onCancelTap(Appointment appointment) async {
    final canceller = widget.onCancel;
    if (canceller == null) return;

    // Confirmation avec champ **motif facultatif**. `null` = l'utilisateur a
    // renoncé (ne rien faire) ; sinon le texte saisi (éventuellement vide).
    final reason = await showDialog<String>(
      context: context,
      builder: (_) => const _CancelAppointmentDialog(),
    );
    if (reason == null || !mounted) return;

    // Session requise pour l'appel (jeton jamais journalisé, §11.1).
    var token = await widget.session.currentToken();
    if (token == null) {
      if (!mounted) return;
      final ok = await widget.onRequireLogin(context);
      if (!ok || !mounted) return;
      token = await widget.session.currentToken();
      if (token == null) return;
    }

    try {
      await canceller(
        appointment: appointment,
        reason: reason,
        accessToken: token,
      );
      if (!mounted) return;
      _showMessage('Rendez-vous annulé.');
      await _load();
    } on NotCancellableException {
      // Verrou serveur final (RDV déjà terminé/annulé entre-temps) : informer et
      // rafraîchir — le RDV a peut-être changé d'état.
      if (!mounted) return;
      _showMessage('Ce rendez-vous ne peut plus être annulé.');
      await _load();
    } on UnauthorizedException {
      // Jeton expiré : invalider la session locale, proposer de se reconnecter.
      await widget.session.clear();
      if (!mounted) return;
      setState(() {
        _needsLogin = true;
        _error = 'Session expirée, veuillez vous reconnecter.';
      });
    } on AppointmentGatewayException catch (exc) {
      // Couvre aussi `AppointmentNotFoundException` (`404`) : message neutre + refresh.
      if (!mounted) return;
      _showMessage(exc.message);
      await _load();
    }
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  // ------------------------------------------------------------------------- //
  // Rendu.
  // ------------------------------------------------------------------------- //
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Mes rendez-vous')),
      body: SafeArea(child: _buildBody()),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_needsLogin) {
      return _CenteredAction(
        message: _error ?? 'Connectez-vous pour voir vos rendez-vous.',
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
        'Vous n\'avez aucun rendez-vous à venir.',
      );
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: _appointments.length,
        separatorBuilder: (_, _) => const SizedBox(height: 12),
        itemBuilder: (context, index) => _AppointmentCard(
          appointment: _appointments[index],
          onModify: widget.onModify == null
              ? null
              : () => _onModifyTap(_appointments[index]),
          onCancel: widget.onCancel == null
              ? null
              : () => _onCancelTap(_appointments[index]),
        ),
      ),
    );
  }
}

class _AppointmentCard extends StatelessWidget {
  const _AppointmentCard({
    required this.appointment,
    this.onModify,
    this.onCancel,
  });

  final Appointment appointment;

  /// Rappel de modification, ou `null` (lecture seule). Toujours **désactivé**
  /// quand le RDV n'est pas modifiable (terminé/terminal).
  final VoidCallback? onModify;

  /// Rappel d'annulation, ou `null` (lecture seule). Toujours **désactivé** quand
  /// le RDV n'est pas annulable (terminé/terminal — verrou serveur §8.1, #24).
  final VoidCallback? onCancel;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final modifiable = appointment.isClientModifiable;
    final cancellable = appointment.isClientCancellable;
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
            const SizedBox(height: 12),
            OverflowBar(
              alignment: MainAxisAlignment.end,
              spacing: 8,
              children: <Widget>[
                OutlinedButton.icon(
                  icon: const Icon(Icons.close),
                  label: const Text('Annuler'),
                  // Désactivé si le RDV est terminé/terminal (verrou §8.1) ou si
                  // aucun rappel d'annulation n'est câblé (lecture seule).
                  onPressed: (cancellable && onCancel != null) ? onCancel : null,
                ),
                FilledButton.tonalIcon(
                  icon: const Icon(Icons.edit),
                  label: const Text('Modifier'),
                  // Désactivé si le RDV est terminé/terminal (verrou §8.1) ou si
                  // aucun rappel de modification n'est câblé (lecture seule).
                  onPressed: (modifiable && onModify != null) ? onModify : null,
                ),
              ],
            ),
            if (!modifiable && !cancellable)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  'Rendez-vous ${appointment.status.label.toLowerCase()} : '
                  'aucune action possible.',
                  style: theme.textTheme.bodySmall,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// Boîte de dialogue de confirmation d'annulation avec **motif facultatif** (#24).
///
/// Retourne (`Navigator.pop`) le **texte du motif** (éventuellement vide) à la
/// confirmation, ou `null` si l'utilisateur renonce. Le motif est une donnée
/// cliente : il n'est **jamais journalisé** (transmis tel quel au use case, qui le
/// trime/omet s'il est vide). Aucune règle métier ici — simple saisie UI.
class _CancelAppointmentDialog extends StatefulWidget {
  const _CancelAppointmentDialog();

  @override
  State<_CancelAppointmentDialog> createState() =>
      _CancelAppointmentDialogState();
}

class _CancelAppointmentDialogState extends State<_CancelAppointmentDialog> {
  final TextEditingController _reasonController = TextEditingController();

  @override
  void dispose() {
    _reasonController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Annuler ce rendez-vous ?'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const Text('Cette action est définitive.'),
          const SizedBox(height: 12),
          TextField(
            controller: _reasonController,
            maxLines: 3,
            maxLength: 500,
            decoration: const InputDecoration(
              labelText: 'Motif (facultatif)',
              border: OutlineInputBorder(),
            ),
          ),
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Retour'),
        ),
        FilledButton(
          onPressed: () =>
              Navigator.of(context).pop(_reasonController.text),
          child: const Text('Confirmer l\'annulation'),
        ),
      ],
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
