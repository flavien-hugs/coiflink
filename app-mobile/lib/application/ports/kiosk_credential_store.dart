// Port (interface) de persistance du **credential device** de la borne (US-8.5, #159).
//
// Contrat interne au paquet, indépendant de Flutter et du stockage concret
// (ADR-0008) : la composition root kiosque en dépend, l'adaptateur
// `SecureKioskCredentialStore` (Keystore/Keychain) l'implémente, et les tests le
// remplacent par un faux en mémoire.
//
// Ce credential appartient au **terminal**, jamais au client de passage : il est
// obtenu **une seule fois**, à l'activation (`KioskActivationGateway`, code à 6
// chiffres — jamais saisi directement), puis persisté ici pour survivre aux
// redémarrages **et** au retour à l'accueil du minuteur d'inactivité.

import 'kiosk_auth_gateway.dart' show KioskCredential;

/// Port de persistance sécurisée du credential device.
abstract class KioskCredentialStore {
  /// Lit le credential stocké, ou `null` si la borne n'a pas encore été activée.
  Future<KioskCredential?> read();

  /// Persiste le credential device (écrase un éventuel credential précédent).
  Future<void> save(KioskCredential credential);

  /// Efface le credential (credential refusé au login → réactivation nécessaire).
  Future<void> clear();
}
