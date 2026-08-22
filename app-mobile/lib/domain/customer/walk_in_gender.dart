// Genre optionnel d'une fiche walk-in créée à la borne (US-8.2, #156 · #172).
//
// Domaine pur (ADR-0008), volontairement restreint aux **deux** choix proposés à
// l'écran borne (Homme/Femme) — l'énumération backend (`domain.enums.Gender`) a
// aussi `OTHER`, non exposé ici par décision produit (#172). Le mapping vers la
// valeur transmise à l'API (`FEMALE`/`MALE`) est la responsabilité de l'adaptateur
// HTTP (`HttpTerminalIdentityGateway`), pas de ce fichier.

enum WalkInGender { female, male }
