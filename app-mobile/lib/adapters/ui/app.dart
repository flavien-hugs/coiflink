// Adapter UI (entrant) — application Flutter (hexagonal, ADR-0008).
//
// Assemble la couche réseau (config API + gateways HTTP), la session cliente et
// les cas d'usage, puis les injecte dans les écrans. Les écrans appellent les cas
// d'usage de `application/` ; ils ne portent aucune règle métier ni appel HTTP
// direct. Conforme à ADR-0001 (Flutter, Android prioritaire) et ADR-0024
// (réservation côté client).

import 'package:flutter/material.dart';

import '../../application/auth_session.dart';
import '../../application/ports/token_store.dart';
import '../../application/use_cases/book_appointment.dart';
import '../../application/use_cases/check_availability.dart';
import '../../application/use_cases/get_salon_detail.dart';
import '../../application/use_cases/search_salons.dart';
import '../../application/use_cases/sign_in.dart';
import '../../domain/salon/salon_detail.dart';
import '../data/api_config.dart';
import '../data/http_appointment_gateway.dart';
import '../data/http_auth_gateway.dart';
import '../data/http_salon_catalog_gateway.dart';
import 'auth/login_screen.dart';
import 'booking/booking_flow_screen.dart';
import 'salon_detail_screen.dart';
import 'salon_search_screen.dart';

class CoifLinkApp extends StatelessWidget {
  const CoifLinkApp({super.key});

  @override
  Widget build(BuildContext context) {
    // Composition root de la couche data : l'URL d'API vient de `--dart-define`
    // (`API_BASE_URL`), jamais codée en dur (spec §Security 7).
    final config = ApiConfig.fromEnvironment();
    final catalogGateway = HttpSalonCatalogGateway(config: config);
    final appointmentGateway = HttpAppointmentGateway(config: config);
    final authGateway = HttpAuthGateway(config: config);

    // Session cliente : magasin de jeton **en mémoire** au MVP (#22 / ADR-0024) ;
    // la bascule vers un magasin sécurisé de plateforme est un remplacement de
    // `TokenStore` (aucun autre code ne dépend de sa nature). Jeton jamais journalisé.
    final session = AuthSession(InMemoryTokenStore());

    final searchSalons = SearchSalons(catalogGateway);
    final getSalonDetail = GetSalonDetail(catalogGateway);
    final checkAvailability = CheckAvailability(appointmentGateway);
    final bookAppointment = BookAppointment(appointmentGateway);
    final signIn = SignIn(authGateway, session);

    // Lanceur du tunnel de réservation (#22) : pousse le tunnel, qui redirige
    // vers la connexion via `onRequireLogin` quand une session est requise.
    void openBooking(BuildContext context, SalonDetail salon) {
      Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => BookingFlowScreen(
            salon: salon,
            checkAvailability: checkAvailability,
            bookAppointment: bookAppointment,
            session: session,
            onRequireLogin: (ctx) => _requireLogin(ctx, signIn),
          ),
        ),
      );
    }

    return MaterialApp(
      title: 'CoifLink',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
        useMaterial3: true,
      ),
      home: AccueilEcran(
        searchSalons: searchSalons,
        getSalonDetail: getSalonDetail,
        onBook: openBooking,
      ),
    );
  }

  /// Pousse l'écran de connexion et retourne `true` si une session est établie.
  static Future<bool> _requireLogin(BuildContext context, SignIn signIn) async {
    final ok = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) => LoginScreen(signIn: signIn),
      ),
    );
    return ok ?? false;
  }
}

class AccueilEcran extends StatelessWidget {
  const AccueilEcran({
    super.key,
    required this.searchSalons,
    required this.getSalonDetail,
    this.onBook,
  });

  final SearchSalons searchSalons;
  final GetSalonDetail getSalonDetail;
  final BookingLauncher? onBook;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('CoifLink')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: <Widget>[
            const Text('CoifLink'),
            const SizedBox(height: 24),
            FilledButton.icon(
              icon: const Icon(Icons.search),
              label: const Text('Rechercher un salon'),
              onPressed: () {
                Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => SalonSearchScreen(
                      searchSalons: searchSalons,
                      getSalonDetail: getSalonDetail,
                      onBook: onBook,
                    ),
                  ),
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}
