// Entité de domaine « rendez-vous » côté client (domaine réservation, #22).
//
// Domaine **pur** : aucune dépendance à Flutter ni à un client HTTP (ADR-0008).
// Reflète l'`AppointmentResponse` renvoyée par `POST /salons/{id}/appointments`
// (#21) au statut `PENDING`. Ne porte que **les données du RDV du client** —
// jamais l'identité d'autres clients ni de donnée de gestion (§11.3).

import 'appointment_status.dart';

/// Prestation réservée : identifiant + prix **figé** au moment de la réservation.
class BookedService {
  const BookedService({required this.serviceId, this.priceAtBooking});

  /// Identifiant opaque de la prestation (UUID côté backend).
  final String serviceId;

  /// Prix figé (chaîne décimale, p. ex. « 5000.00 ») ou `null` si non fourni.
  /// Conservé en chaîne pour ne pas introduire d'imprécision flottante.
  final String? priceAtBooking;
}

/// Rendez-vous créé, tel que renvoyé par le backend à la réservation.
class Appointment {
  const Appointment({
    required this.id,
    required this.salonId,
    required this.date,
    required this.startTime,
    required this.endTime,
    required this.status,
    this.hairdresserId,
    this.clientNote,
    this.services = const <BookedService>[],
  });

  /// Identifiant opaque du RDV (UUID côté backend).
  final String id;

  /// Salon auquel le RDV est lié (critère d'acceptation #22).
  final String salonId;

  /// Coiffeur assigné, ou `null` (réservation au niveau salon, MVP #22).
  final String? hairdresserId;

  /// Jour du RDV (composantes de date seules ; repère UTC+0).
  final DateTime date;

  /// Heures de début/fin, format `HH:MM` (repère UTC+0).
  final String startTime;
  final String endTime;

  /// Statut du RDV — `pending` (« En attente ») à la création (#22).
  final AppointmentStatus status;

  /// Commentaire libre du client, ou `null`.
  final String? clientNote;

  /// Prestations réservées (≥ 1) — un RDV est lié à ≥ 1 prestation (#22).
  final List<BookedService> services;
}
