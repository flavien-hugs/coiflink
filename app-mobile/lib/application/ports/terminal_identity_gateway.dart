// Port (interface) d'identité walk-in de la borne (US-8.5, #159 · US-8.2, #156).
//
// Contrat interne au paquet, indépendant de Flutter et du transport HTTP
// (ADR-0008) : les écrans d'identification/création en dépendent, l'adaptateur
// `HttpTerminalIdentityGateway` l'implémente, et les tests le remplacent par un faux.
//
// #159 **consomme** les contrats de #156 sans les réimplémenter : aucune
// normalisation de téléphone ni validation de nom côté client, aucune écriture
// `customer_profiles`. La projection retournée est **minimale** (prénom seul) —
// jamais le nom complet ni le téléphone (borne = terminal public partagé, §11.3).

/// Projection minimale d'une fiche client renvoyée à la borne (#156) : le
/// `customerId` (= `customer_profile_id` que #157 consommera) et le **prénom seul**.
class WalkInIdentity {
  const WalkInIdentity({required this.customerId, required this.firstName});

  final String customerId;
  final String firstName;
}

/// Échec **neutre** d'une opération d'identité (réseau, `5xx`, `429`, illisible).
class TerminalIdentityException implements Exception {
  const TerminalIdentityException([
    this.message = 'Borne momentanément indisponible.',
  ]);

  final String message;

  @override
  String toString() => 'TerminalIdentityException: $message';
}

/// Levée à la création quand une fiche porte **déjà** ce téléphone dans ce salon
/// (`409`) : la borne invite à revenir à l'identification par téléphone.
class TerminalCustomerAlreadyExistsException extends TerminalIdentityException {
  const TerminalCustomerAlreadyExistsException([
    super.message = 'Une fiche existe déjà pour ce numéro.',
  ]);
}

/// Port d'identité walk-in (recherche + création), réservé au rôle TERMINAL.
abstract class TerminalIdentityGateway {
  /// Retrouve une fiche par téléphone dans le salon de la borne
  /// (`POST /salons/{salon_id}/terminal/customers/lookup`, #156).
  ///
  /// Retourne la projection minimale si trouvée, `null` si aucune fiche (`404`
  /// neutre). Lève [TerminalIdentityException] pour tout échec réseau/serveur.
  Future<WalkInIdentity?> findByPhone(String phone);

  /// Crée une fiche walk-in **sans mot de passe**
  /// (`POST /salons/{salon_id}/terminal/customers`, #156) et retourne sa projection.
  ///
  /// Lève [TerminalCustomerAlreadyExistsException] si le téléphone est déjà fiché
  /// (`409`), [TerminalIdentityException] pour tout autre échec.
  Future<WalkInIdentity> createCustomer({
    required String firstName,
    required String lastName,
    required String phone,
  });
}
