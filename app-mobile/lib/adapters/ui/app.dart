// Adapter UI (entrant) — application Flutter (hexagonal, ADR-0008).
//
// Assemble la couche réseau (config API + gateway HTTP) et les cas d'usage, puis
// les injecte dans les écrans. Les écrans appellent les cas d'usage de
// `application/` ; ils ne portent aucune règle métier ni appel HTTP direct.
// Conforme à ADR-0001 (Flutter, Android prioritaire).

import 'package:flutter/material.dart';

import '../../application/use_cases/search_salons.dart';
import '../data/api_config.dart';
import '../data/http_salon_catalog_gateway.dart';
import 'salon_search_screen.dart';

class CoifLinkApp extends StatelessWidget {
  const CoifLinkApp({super.key});

  @override
  Widget build(BuildContext context) {
    // Composition root de la couche data : l'URL d'API vient de `--dart-define`
    // (`API_BASE_URL`), jamais codée en dur (spec §Security 7).
    final gateway = HttpSalonCatalogGateway(config: ApiConfig.fromEnvironment());
    final searchSalons = SearchSalons(gateway);

    return MaterialApp(
      title: 'CoifLink',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
        useMaterial3: true,
      ),
      home: AccueilEcran(searchSalons: searchSalons),
    );
  }
}

class AccueilEcran extends StatelessWidget {
  const AccueilEcran({super.key, required this.searchSalons});

  final SearchSalons searchSalons;

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
                    builder: (_) =>
                        SalonSearchScreen(searchSalons: searchSalons),
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
