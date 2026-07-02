// Composition root de l'application mobile CoifLink (Flutter), hexagonal (ADR-0008).
//
// N'assemble que l'application : délègue toute la présentation à l'adapter UI
// (`adapters/ui/app.dart`). Le domaine (`domain/`) et les cas d'usage
// (`application/`) restent indépendants de Flutter. Conforme à ADR-0001.

import 'package:flutter/material.dart';

import 'adapters/ui/app.dart';

// Réexporté pour que `CoifLinkApp` reste accessible via `package:coiflink_mobile/main.dart`
// (compatibilité des tests et points d'entrée d'outillage).
export 'adapters/ui/app.dart';

void main() {
  runApp(const CoifLinkApp());
}
