// Port (interface) de disponibilité & réservation — application, #22.
//
// Contrat interne au paquet, indépendant de Flutter et du transport HTTP
// (ADR-0008) : les cas d'usage `CheckAvailability`/`BookAppointment` en dépendent,
// l'adapter `HttpAppointmentGateway` l'implémente, et les tests le remplacent par
// un faux (patron `SalonCatalogGateway`).
//
// Les exceptions sont **neutres** (patron `SalonCatalogException`) : elles ne
// transportent **jamais** d'URL, de jeton, de corps de requête ni de PII (§11).

import '../../domain/appointment/appointment.dart';
import '../../domain/appointment/availability_slot.dart';

/// Brouillon de réservation soumis au backend.
///
/// Ne porte **jamais** `client_id`, `salon_id` ni `status` : le `salon_id` vient
/// du chemin, le `client_id` du jeton, `status` est forcé `PENDING` côté serveur
/// (anti-élévation §11.2). Le mobile ne les envoie pas.
class BookingDraft {
  BookingDraft({
    required this.date,
    required this.startTime,
    required List<String> serviceIds,
    this.hairdresserId,
    this.clientNote,
  }) : serviceIds = List<String>.unmodifiable(serviceIds);

  /// Jour du créneau visé (composantes de date ; repère UTC+0).
  final DateTime date;

  /// Heure de début `HH:MM` du créneau choisi.
  final String startTime;

  /// Prestations réservées (**≥ 1**) — un RDV est lié à ≥ 1 prestation (#22).
  final List<String> serviceIds;

  /// Coiffeur ciblé, ou `null` (réservation au niveau salon, MVP #22).
  final String? hairdresserId;

  /// Commentaire libre optionnel.
  final String? clientNote;
}

/// Échec générique de la passerelle de réservation (réseau, HTTP non géré,
/// réponse illisible). Ne transporte **jamais** d'URL, de jeton ni de PII.
class AppointmentGatewayException implements Exception {
  const AppointmentGatewayException(this.message);

  final String message;

  @override
  String toString() => 'AppointmentGatewayException: $message';
}

/// Levée quand le créneau vient d'être **pris** (`409`, course perdue) : le
/// verdict d'intégrité base est final (§8.1) — l'UI propose un autre créneau.
class SlotTakenException extends AppointmentGatewayException {
  const SlotTakenException([
    super.message = 'Ce créneau vient d\'être pris.',
  ]);

  @override
  String toString() => 'SlotTakenException: $message';
}

/// Levée quand le salon n'est **pas réservable** ou le créneau est hors offre
/// (`409`, §8.3). Distincte de [SlotTakenException] : rien à re-choisir ici.
class NotBookableException extends AppointmentGatewayException {
  const NotBookableException([
    super.message = 'Ce salon n\'accepte pas de réservation pour le moment.',
  ]);

  @override
  String toString() => 'NotBookableException: $message';
}

/// Levée quand la requête n'est **pas authentifiée** (`401`, jeton absent/expiré) :
/// l'UI invalide la session locale et redirige vers la connexion.
class UnauthorizedException extends AppointmentGatewayException {
  const UnauthorizedException([
    super.message = 'Session expirée, veuillez vous reconnecter.',
  ]);

  @override
  String toString() => 'UnauthorizedException: $message';
}

/// Levée quand le RDV n'est **plus modifiable** (`409`, terminé/terminal, §8.1) :
/// le verrou serveur est final — rien à re-choisir, l'UI rafraîchit la liste.
class NotModifiableException extends AppointmentGatewayException {
  const NotModifiableException([
    super.message = 'Ce rendez-vous n\'est plus modifiable.',
  ]);

  @override
  String toString() => 'NotModifiableException: $message';
}

/// Levée quand le RDV n'est **plus annulable** (`409`, terminé/terminal/déjà
/// annulé, §8.1, #24) : le verrou serveur est final — rien à re-choisir, l'UI
/// rafraîchit la liste. Distincte de [NotModifiableException] (deux règles métier
/// séparées, même si le jeu d'états coïncide au MVP).
class NotCancellableException extends AppointmentGatewayException {
  const NotCancellableException([
    super.message = 'Ce rendez-vous ne peut plus être annulé.',
  ]);

  @override
  String toString() => 'NotCancellableException: $message';
}

/// Levée quand le RDV visé est **introuvable** ou **hors appartenance** (`404`) :
/// indiscernables (aucun oracle §11.2) — l'UI rafraîchit la liste « Mes RDV ».
class AppointmentNotFoundException extends AppointmentGatewayException {
  const AppointmentNotFoundException([
    super.message = 'Rendez-vous introuvable.',
  ]);

  @override
  String toString() => 'AppointmentNotFoundException: $message';
}

/// Port de disponibilité & réservation consommé par le tunnel client.
abstract class AppointmentGateway {
  /// Retourne les créneaux **libres** d'un salon `ACTIVE` pour une prestation
  /// (et un coiffeur optionnel), à la date donnée — via `GET .../availability`
  /// (**public**, aucun jeton requis).
  ///
  /// Lève [NotBookableException] (`409`, salon non réservable),
  /// [AppointmentGatewayException] (réseau / `404` / réponse invalide).
  Future<List<AvailabilitySlot>> availableSlots({
    required String salonId,
    required DateTime date,
    required String serviceId,
    String? hairdresserId,
  });

  /// Réserve un créneau via `POST /salons/{salonId}/appointments` avec l'en-tête
  /// `Authorization: Bearer <accessToken>`. Crée le RDV au statut `PENDING`.
  ///
  /// Lève [UnauthorizedException] (`401`), [SlotTakenException] /
  /// [NotBookableException] (`409`), [AppointmentGatewayException] (`404` /
  /// réseau / réponse invalide).
  Future<Appointment> book({
    required String salonId,
    required BookingDraft draft,
    required String accessToken,
  });

  /// Liste les rendez-vous **du client** authentifié via `GET /appointments`
  /// (en-tête `Authorization: Bearer <accessToken>`). Ne renvoie que ses RDV actifs.
  ///
  /// Lève [UnauthorizedException] (`401`), [AppointmentGatewayException] (réseau /
  /// réponse invalide).
  Future<List<Appointment>> myAppointments({required String accessToken});

  /// Re-planifie **son** rendez-vous via `PATCH /appointments/{appointmentId}` avec
  /// l'en-tête `Authorization: Bearer <accessToken>` (corps sans `client_id`/
  /// `salon_id`/`status`, §11.2). Sémantique *replace* (miroir de [book]).
  ///
  /// Lève [UnauthorizedException] (`401`), [NotModifiableException] (`409`, RDV
  /// terminé) / [SlotTakenException] (`409`, créneau pris) / [NotBookableException]
  /// (`409`, salon non réservable), [AppointmentNotFoundException] (`404`),
  /// [AppointmentGatewayException] (réseau / réponse invalide).
  Future<Appointment> modify({
    required String appointmentId,
    required BookingDraft draft,
    required String accessToken,
  });

  /// Annule **son** rendez-vous via `POST /appointments/{appointmentId}/cancellation`
  /// avec l'en-tête `Authorization: Bearer <accessToken>`. Le corps ne porte qu'un
  /// **motif optionnel** (`reason`) — jamais `client_id`/`salon_id`/`status`
  /// (anti-élévation §11.2) ; le `status = CANCELLED` est forcé serveur. Le motif est
  /// une donnée cliente : **jamais** journalisé. Retourne le RDV au statut `cancelled`.
  ///
  /// Lève [UnauthorizedException] (`401`), [NotCancellableException] (`409`, RDV
  /// terminé/terminal), [AppointmentNotFoundException] (`404`),
  /// [AppointmentGatewayException] (réseau / réponse invalide).
  Future<Appointment> cancel({
    required String appointmentId,
    String? reason,
    required String accessToken,
  });
}
