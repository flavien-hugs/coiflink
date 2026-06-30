// Adapter UI (entrant) — squelette d'initialisation (#2), hexagonal (ADR-0008).
//
// Contient l'application Flutter et ses écrans (présentation). Les écrans
// appellent les cas d'usage de `application/` ; ils ne portent aucune règle
// métier. Écran d'accueil neutre, sans fonctionnalité (réservation, historique,
// rappels → issues M1→). Conforme à ADR-0001 (Flutter, Android prioritaire).

import 'package:flutter/material.dart';

class CoifLinkApp extends StatelessWidget {
  const CoifLinkApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'CoifLink',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
        useMaterial3: true,
      ),
      home: const AccueilEcran(),
    );
  }
}

class AccueilEcran extends StatelessWidget {
  const AccueilEcran({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('CoifLink')),
      body: const Center(
        child: Text('CoifLink'),
      ),
    );
  }
}
