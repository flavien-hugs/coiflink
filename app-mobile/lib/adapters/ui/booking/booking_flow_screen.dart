// Écran UI : tunnel de réservation guidé (§7.1, #22).
//
// Parcours en étapes ouvert depuis la fiche salon (#19), au-dessus des endpoints
// livrés par #21 : prestation → date → créneau → commentaire → confirmation.
// Consomme les cas d'usage `CheckAvailability` / `BookAppointment` (injectés) ;
// aucune règle métier ni appel HTTP direct ici.
//
// MVP #22 (voir ADR-0024) : **une seule** prestation par réservation (cohérent
// avec la disponibilité mono-`service_id`), réservation **au niveau salon** (pas
// de `hairdresser_id`), horizon de date borné, repère **UTC+0** (Africa/Abidjan).
//
// États honnêtes : chargement des créneaux, aucun créneau (jour fermé/complet),
// erreur réseau (réessayer), `409` créneau pris (retour à l'étape créneaux
// rafraîchie), `409` salon non réservable, `401` (redirection Connexion).
// Sécurité : le corps de réservation n'envoie **jamais** `client_id`/`salon_id`/
// `status` ; le jeton n'est **jamais journalisé** (§11).

import 'package:flutter/material.dart';

import '../../../application/auth_session.dart';
import '../../../application/ports/appointment_gateway.dart';
import '../../../application/use_cases/book_appointment.dart';
import '../../../application/use_cases/check_availability.dart';
import '../../../application/use_cases/modify_appointment.dart';
import '../../../domain/appointment/appointment.dart';
import '../../../domain/appointment/availability_slot.dart';
import '../../../domain/salon/salon_detail.dart';
import '../../../domain/salon/salon_service.dart';
import 'booking_confirmation_screen.dart';
import 'booking_labels.dart';

/// Horizon de sélection de date (jours ouverts à la réservation depuis aujourd'hui).
const int kBookingHorizonDays = 30;

/// Demande une connexion cliente et retourne `true` si une session est établie.
///
/// Câblée par le composition root (pousse `LoginScreen`) ; injectable pour les
/// tests. Le tunnel appelle ce rappel quand la réservation exige une session.
typedef LoginRequester = Future<bool> Function(BuildContext context);

/// Contexte de **modification** d'un RDV existant (US-3.2, #23) : réutilise le
/// tunnel de réservation en mode *modification* (pré-rempli, confirmation via
/// `modify` au lieu de `book`). Absent (`null`) → mode réservation (#22).
class AppointmentModification {
  const AppointmentModification({
    required this.appointment,
    required this.modifyAppointment,
  });

  /// Le RDV à re-planifier (id, date/créneau/note actuels, statut).
  final Appointment appointment;

  /// Cas d'usage de modification (validation amont + délégation au port).
  final ModifyAppointment modifyAppointment;
}

class BookingFlowScreen extends StatefulWidget {
  const BookingFlowScreen({
    super.key,
    required this.salon,
    required this.checkAvailability,
    required this.bookAppointment,
    required this.session,
    required this.onRequireLogin,
    this.modification,
  });

  final SalonDetail salon;
  final CheckAvailability checkAvailability;
  final BookAppointment bookAppointment;
  final AuthSession session;
  final LoginRequester onRequireLogin;

  /// Contexte de modification, ou `null` pour une réservation (#22).
  final AppointmentModification? modification;

  @override
  State<BookingFlowScreen> createState() => _BookingFlowScreenState();
}

class _BookingFlowScreenState extends State<BookingFlowScreen> {
  static const int _stepService = 0;
  static const int _stepDate = 1;
  static const int _stepSlot = 2;
  static const int _stepNote = 3;
  static const int _stepConfirm = 4;

  int _step = _stepService;

  SalonService? _service;
  DateTime? _date;
  AvailabilitySlot? _slot;
  final TextEditingController _note = TextEditingController();

  // État de l'étape « créneaux ».
  bool _slotsLoading = false;
  String? _slotsError;
  List<AvailabilitySlot> _slots = const <AvailabilitySlot>[];

  bool _confirming = false;

  bool get _isModification => widget.modification != null;

  @override
  void initState() {
    super.initState();
    // Mode modification (#23) : pré-remplir prestation/date/note du RDV existant.
    // Le créneau est re-choisi à l'étape « Créneau » (le serveur exclut le RDV
    // lui-même du calcul, l'ancien créneau reste donc proposé s'il est libre).
    final modification = widget.modification;
    if (modification != null) {
      final appointment = modification.appointment;
      _date = appointment.date;
      _note.text = appointment.clientNote ?? '';
      final serviceId = appointment.services.isNotEmpty
          ? appointment.services.first.serviceId
          : null;
      if (serviceId != null) {
        for (final service in widget.salon.services) {
          if (service.id == serviceId) {
            _service = service;
            break;
          }
        }
      }
    }
  }

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  // ------------------------------------------------------------------------- //
  // Navigation entre étapes.
  // ------------------------------------------------------------------------- //
  bool get _canContinue {
    switch (_step) {
      case _stepService:
        return _service != null;
      case _stepDate:
        return _date != null;
      case _stepSlot:
        return _slot != null;
      case _stepNote:
        return true;
      default:
        return false;
    }
  }

  void _next() {
    if (!_canContinue) return;
    if (_step == _stepDate) {
      setState(() => _step = _stepSlot);
      _loadSlots();
      return;
    }
    setState(() => _step += 1);
  }

  void _back() {
    if (_step == _stepService) {
      Navigator.of(context).pop();
      return;
    }
    setState(() => _step -= 1);
  }

  // ------------------------------------------------------------------------- //
  // Chargement des créneaux libres (étape 3).
  // ------------------------------------------------------------------------- //
  Future<void> _loadSlots() async {
    final service = _service;
    final date = _date;
    if (service == null || date == null) return;
    setState(() {
      _slotsLoading = true;
      _slotsError = null;
    });
    try {
      final slots = await widget.checkAvailability.call(
        salonId: widget.salon.id,
        date: date,
        serviceId: service.id,
      );
      if (!mounted) return;
      setState(() {
        _slots = slots;
        _slotsLoading = false;
      });
    } on NotBookableException catch (exc) {
      if (!mounted) return;
      setState(() {
        _slots = const <AvailabilitySlot>[];
        _slotsError = exc.message;
        _slotsLoading = false;
      });
    } on PastDateException catch (exc) {
      if (!mounted) return;
      setState(() {
        _slots = const <AvailabilitySlot>[];
        _slotsError = exc.message;
        _slotsLoading = false;
      });
    } on AppointmentGatewayException catch (exc) {
      if (!mounted) return;
      setState(() {
        _slotsError = exc.message;
        _slotsLoading = false;
      });
    }
  }

  // ------------------------------------------------------------------------- //
  // Confirmation & réservation (étape 5).
  // ------------------------------------------------------------------------- //
  Future<void> _confirm() async {
    if (_confirming) return;
    setState(() => _confirming = true);

    // Session requise : si absente, rediriger vers Connexion puis revenir.
    var token = await widget.session.currentToken();
    if (token == null) {
      final ok = await _requestLogin();
      if (!ok) {
        _stopConfirming();
        return;
      }
      token = await widget.session.currentToken();
      if (token == null) {
        _stopConfirming();
        return;
      }
    }

    final draft = BookingDraft(
      date: _date!,
      startTime: _slot!.start,
      serviceIds: <String>[_service!.id],
      clientNote: _note.text,
    );

    final modification = widget.modification;
    try {
      if (modification != null) {
        // Mode modification (#23) : re-planifie le RDV puis revient à la liste.
        await modification.modifyAppointment.call(
          appointment: modification.appointment,
          draft: draft,
          accessToken: token,
        );
        if (!mounted) return;
        Navigator.of(context).pop(true);
        return;
      }
      final appointment = await widget.bookAppointment.call(
        salonId: widget.salon.id,
        draft: draft,
        accessToken: token,
      );
      if (!mounted) return;
      // Succès : écran de confirmation (statut « En attente »), remplace le tunnel.
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => BookingConfirmationScreen(
            appointment: appointment,
            salonName: widget.salon.name,
            serviceName: _service!.name,
          ),
        ),
      );
    } on UnauthorizedException {
      // Jeton expiré : invalider la session locale, proposer de se reconnecter.
      await widget.session.clear();
      if (!mounted) return;
      _stopConfirming();
      await _requestLogin();
      _showMessage('Session expirée. Reconnectez-vous puis confirmez à nouveau.');
    } on NotModifiableException {
      // Verrou serveur (§8.1) : le RDV est devenu non modifiable (p. ex. terminé).
      // Rien à re-choisir : revenir à la liste (qui se rafraîchit).
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on AppointmentNotFoundException {
      // RDV disparu/hors appartenance : revenir à la liste (qui se rafraîchit).
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on SlotTakenException {
      // Course perdue (§8.1) : retour à l'étape créneaux avec rafraîchissement.
      if (!mounted) return;
      setState(() {
        _confirming = false;
        _slot = null;
        _step = _stepSlot;
      });
      _showMessage('Ce créneau vient d\'être pris, choisissez-en un autre.');
      _loadSlots();
    } on NotBookableException catch (exc) {
      if (!mounted) return;
      _stopConfirming();
      _showMessage(exc.message);
    } on AppointmentGatewayException catch (exc) {
      if (!mounted) return;
      _stopConfirming();
      _showMessage(exc.message);
    }
  }

  Future<bool> _requestLogin() async {
    final ok = await widget.onRequireLogin(context);
    return ok;
  }

  void _stopConfirming() {
    if (!mounted) return;
    setState(() => _confirming = false);
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
    final title = _isModification
        ? 'Modifier — ${widget.salon.name}'
        : 'Réserver — ${widget.salon.name}';
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: SafeArea(
        child: Column(
          children: <Widget>[
            _StepIndicator(step: _step),
            const Divider(height: 1),
            Expanded(child: _buildStepBody()),
            const Divider(height: 1),
            _buildNavBar(),
          ],
        ),
      ),
    );
  }

  Widget _buildStepBody() {
    switch (_step) {
      case _stepService:
        return _ServiceStep(
          services: widget.salon.services,
          selected: _service,
          onSelected: (s) => setState(() => _service = s),
        );
      case _stepDate:
        return _DateStep(
          selected: _date,
          onSelected: (d) => setState(() => _date = d),
        );
      case _stepSlot:
        return _SlotStep(
          loading: _slotsLoading,
          error: _slotsError,
          slots: _slots,
          selected: _slot,
          onSelected: (s) => setState(() => _slot = s),
          onRetry: _loadSlots,
        );
      case _stepNote:
        return _NoteStep(controller: _note);
      case _stepConfirm:
      default:
        return _ConfirmStep(
          salonName: widget.salon.name,
          service: _service!,
          date: _date!,
          slot: _slot!,
          note: _note.text,
          isModification: _isModification,
        );
    }
  }

  Widget _buildNavBar() {
    final isConfirmStep = _step == _stepConfirm;
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: <Widget>[
          Expanded(
            child: OutlinedButton(
              onPressed: _confirming ? null : _back,
              child: Text(_step == _stepService ? 'Annuler' : 'Retour'),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: FilledButton(
              onPressed: isConfirmStep
                  ? (_confirming ? null : _confirm)
                  : (_canContinue ? _next : null),
              child: _confirming
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Text(isConfirmStep ? 'Confirmer' : 'Continuer'),
            ),
          ),
        ],
      ),
    );
  }
}

// --------------------------------------------------------------------------- //
// Widgets d'étape.
// --------------------------------------------------------------------------- //
class _StepIndicator extends StatelessWidget {
  const _StepIndicator({required this.step});

  final int step;

  static const List<String> _titles = <String>[
    'Prestation',
    'Date',
    'Créneau',
    'Commentaire',
    'Confirmation',
  ];

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        children: <Widget>[
          Text(
            'Étape ${step + 1}/${_titles.length}',
            style: Theme.of(context).textTheme.labelMedium,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              _titles[step],
              style: Theme.of(context).textTheme.titleMedium,
              textAlign: TextAlign.end,
            ),
          ),
        ],
      ),
    );
  }
}

class _ServiceStep extends StatelessWidget {
  const _ServiceStep({
    required this.services,
    required this.selected,
    required this.onSelected,
  });

  final List<SalonService> services;
  final SalonService? selected;
  final ValueChanged<SalonService> onSelected;

  @override
  Widget build(BuildContext context) {
    if (services.isEmpty) {
      return const _CenteredMessage('Ce salon ne propose aucune prestation.');
    }
    return ListView(
      padding: const EdgeInsets.all(8),
      children: <Widget>[
        for (final service in services)
          ListTile(
            selected: selected?.id == service.id,
            onTap: () => onSelected(service),
            leading: Icon(
              selected?.id == service.id
                  ? Icons.radio_button_checked
                  : Icons.radio_button_unchecked,
            ),
            title: Text(service.name),
            subtitle: _serviceSubtitle(service).isEmpty
                ? null
                : Text(_serviceSubtitle(service)),
          ),
      ],
    );
  }

  static String _serviceSubtitle(SalonService service) {
    final parts = <String>[
      if (service.durationMinutes != null) '${service.durationMinutes} min',
      if (service.price != null && service.price!.trim().isNotEmpty)
        '${service.price} FCFA',
    ];
    return parts.join(' · ');
  }
}

class _DateStep extends StatelessWidget {
  const _DateStep({required this.selected, required this.onSelected});

  final DateTime? selected;
  final ValueChanged<DateTime> onSelected;

  @override
  Widget build(BuildContext context) {
    final today = DateTime.now();
    final days = <DateTime>[
      for (int i = 0; i < kBookingHorizonDays; i++)
        DateTime(today.year, today.month, today.day + i),
    ];
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        Text(
          'Choisissez une date',
          style: Theme.of(context).textTheme.titleSmall,
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: <Widget>[
            for (final day in days)
              ChoiceChip(
                label: Text(formatDateChip(day)),
                selected: _sameDay(selected, day),
                onSelected: (_) => onSelected(day),
              ),
          ],
        ),
      ],
    );
  }

  static bool _sameDay(DateTime? a, DateTime b) =>
      a != null && a.year == b.year && a.month == b.month && a.day == b.day;
}

class _SlotStep extends StatelessWidget {
  const _SlotStep({
    required this.loading,
    required this.error,
    required this.slots,
    required this.selected,
    required this.onSelected,
    required this.onRetry,
  });

  final bool loading;
  final String? error;
  final List<AvailabilitySlot> slots;
  final AvailabilitySlot? selected;
  final ValueChanged<AvailabilitySlot> onSelected;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(error!, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton(onPressed: onRetry, child: const Text('Réessayer')),
            ],
          ),
        ),
      );
    }
    if (slots.isEmpty) {
      return const _CenteredMessage(
        'Aucun créneau disponible ce jour-là. Essayez une autre date.',
      );
    }
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        Text(
          'Créneaux disponibles',
          style: Theme.of(context).textTheme.titleSmall,
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: <Widget>[
            for (final slot in slots)
              ChoiceChip(
                label: Text(slot.start),
                selected: selected == slot,
                onSelected: (_) => onSelected(slot),
              ),
          ],
        ),
      ],
    );
  }
}

class _NoteStep extends StatelessWidget {
  const _NoteStep({required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            'Commentaire (optionnel)',
            style: Theme.of(context).textTheme.titleSmall,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: controller,
            maxLength: 500,
            maxLines: 4,
            decoration: const InputDecoration(
              hintText: 'Une précision pour le salon ?',
              border: OutlineInputBorder(),
            ),
          ),
        ],
      ),
    );
  }
}

class _ConfirmStep extends StatelessWidget {
  const _ConfirmStep({
    required this.salonName,
    required this.service,
    required this.date,
    required this.slot,
    required this.note,
    this.isModification = false,
  });

  final String salonName;
  final SalonService service;
  final DateTime date;
  final AvailabilitySlot slot;
  final String note;
  final bool isModification;

  @override
  Widget build(BuildContext context) {
    final trimmedNote = note.trim();
    final footer = isModification
        ? 'En confirmant, votre rendez-vous est mis à jour.'
        : 'En confirmant, votre rendez-vous est enregistré au statut « En attente ».';
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        Text('Récapitulatif', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 16),
        _Line(label: 'Salon', value: salonName),
        _Line(label: 'Prestation', value: service.name),
        _Line(label: 'Date', value: formatFullDate(date)),
        _Line(label: 'Créneau', value: '${slot.start} – ${slot.end}'),
        if (trimmedNote.isNotEmpty) _Line(label: 'Commentaire', value: trimmedNote),
        const SizedBox(height: 24),
        Text(footer, style: Theme.of(context).textTheme.bodySmall),
      ],
    );
  }
}

class _Line extends StatelessWidget {
  const _Line({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SizedBox(
            width: 110,
            child: Text(label, style: Theme.of(context).textTheme.labelLarge),
          ),
          Expanded(child: Text(value)),
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
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(message, textAlign: TextAlign.center),
      ),
    );
  }
}
