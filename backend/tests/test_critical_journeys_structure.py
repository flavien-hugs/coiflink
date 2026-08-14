"""Tests non-e2e pour les invariants structurels de la suite de parcours critiques (#50).

Ces tests vérifient des propriétés déterministes et sans I/O externe :

- Le préfixe de téléphones réservé (`+225068999`) n'entre pas en collision avec les autres
  suites e2e (prévention de corruption du nettoyage FK en CI).
- Les constantes de numéros locaux sont cohérentes avec le préfixe réservé.
- Le `_TEST_JWT_SECRET` de test ne ressemble pas à un vrai token (politique §11.4).
- `_wipe_test_data()` supprime les tables walk-in (`cash_journal`/`payments`/
  `queue_ticket_services`/`queue_tickets`) dans l'ordre FK-safe imposé par le pivot
  walk-in exclusif (#148, migration `0017`) — régression statique.
- Les trois classes de parcours portent toutes un `@pytest.mark.skipif` (skip propre).
- `docs/strategie-de-tests.md` reflète #50 comme **livré** (invariant documentaire).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_TESTS_DIR = REPO_ROOT / "backend" / "tests"
_JOURNEYS_FILE = _TESTS_DIR / "test_critical_journeys_e2e.py"
_STRATEGY_DOC = REPO_ROOT / "docs" / "strategie-de-tests.md"

# Importation des helpers purs et constantes depuis le module e2e (pas d'I/O).
from .test_critical_journeys_e2e import (  # noqa: E402
    _E2E_PHONE_PREFIX,
    _PHONE_CLIENT_A_LOCAL,
    _PHONE_CLIENT_B_LOCAL,
    _PHONE_HAIRDRESSER_LOCAL,
    _PHONE_MANAGER_LOCAL,
    _TEST_JWT_SECRET,
)

_SUSPICIOUS_SECRET_PATTERNS = re.compile(
    r"ghp_[A-Za-z0-9]{36,}"
    r"|ghs_[A-Za-z0-9]{36,}"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|Bearer [A-Za-z0-9+/=]{20,}"
)


class TestPhonePrefixConsistency:
    """Les constantes de numéros locaux correspondent au préfixe réservé après normalisation E.164."""

    @staticmethod
    def _normalize(local: str) -> str:
        """Réplique la normalisation E.164 (pays 225) : préfixe +225 + numéro complet.

        Conforme à `normalize_phone` du domaine : `normalize_phone("0700000000") ==
        "+2250700000000"` — le zéro initial est conservé, non supprimé.
        """
        return "+225" + local

    def _assert_matches_prefix(self, local: str) -> None:
        normalized = self._normalize(local)
        assert normalized.startswith(_E2E_PHONE_PREFIX), (
            f"Le numéro normalisé {normalized!r} ne commence pas par le préfixe "
            f"réservé {_E2E_PHONE_PREFIX!r} — collision de nettoyage possible en CI."
        )

    def test_manager_phone_matches_prefix(self) -> None:
        self._assert_matches_prefix(_PHONE_MANAGER_LOCAL)

    def test_hairdresser_phone_matches_prefix(self) -> None:
        self._assert_matches_prefix(_PHONE_HAIRDRESSER_LOCAL)

    def test_client_a_phone_matches_prefix(self) -> None:
        self._assert_matches_prefix(_PHONE_CLIENT_A_LOCAL)

    def test_client_b_phone_matches_prefix(self) -> None:
        self._assert_matches_prefix(_PHONE_CLIENT_B_LOCAL)


class TestPhonePrefixUniqueness:
    """Le préfixe `+225068999` ne doit pas apparaître dans d'autres fichiers `*_e2e.py`.

    Deux suites qui partagent un même préfixe se nettoient mutuellement dans la même
    base CI — corruption silencieuse garantie.
    """

    def _other_e2e_files(self) -> list[Path]:
        return [
            p for p in _TESTS_DIR.glob("*_e2e.py")
            if p.name != "test_critical_journeys_e2e.py"
        ]

    def test_prefix_absent_from_other_e2e_files(self) -> None:
        collisions = [
            p.name
            for p in self._other_e2e_files()
            if _E2E_PHONE_PREFIX in p.read_text()
        ]
        assert not collisions, (
            f"Le préfixe {_E2E_PHONE_PREFIX!r} est utilisé dans d'autres suites e2e "
            f"— collision de nettoyage en CI : {collisions}"
        )

    def test_prefix_present_in_journeys_file(self) -> None:
        """Sanity-check : le préfixe doit bien figurer dans le fichier cible."""
        assert _E2E_PHONE_PREFIX in _JOURNEYS_FILE.read_text()


class TestJwtSecretPolicy:
    """Le `_TEST_JWT_SECRET` ne doit pas ressembler à un vrai token (§11.4/politique #5)."""

    def test_secret_not_suspicious(self) -> None:
        assert not _SUSPICIOUS_SECRET_PATTERNS.search(_TEST_JWT_SECRET), (
            "_TEST_JWT_SECRET ressemble à un vrai token/secret — "
            "utiliser un secret factice lisible, jamais une valeur d'apparence réelle."
        )

    def test_secret_contains_test_marker(self) -> None:
        assert "test" in _TEST_JWT_SECRET.lower(), (
            "_TEST_JWT_SECRET doit contenir 'test' pour indiquer clairement son usage non-production."
        )

    def test_secret_contains_not_for_production_marker(self) -> None:
        assert "not-for-production" in _TEST_JWT_SECRET.lower(), (
            "_TEST_JWT_SECRET doit contenir 'not-for-production' (invariant de la politique de secrets)."
        )


class TestFkSafeWipeOrder:
    """Régression statique : `_wipe_test_data()` doit supprimer les tables dans l'ordre FK-safe.

    Depuis le pivot walk-in exclusif (#148, migration `0017`), le module Rendez-vous
    et les notifications de RDV ont disparu **avec leurs tables** — les seules
    contraintes FK `RESTRICT` pertinentes ici portent sur la chaîne walk-in
    (`cash_journal` → `payments` → `queue_ticket_services` → `queue_tickets` →
    `customer_profiles`) et sur les comptes (`salons` → `users`). Un ordre incorrect
    provoque une violation de contrainte au nettoyage — erreur silencieuse en CI si
    les données de test s'accumulent.
    """

    def _delete_order(self) -> list[str]:
        """Extrait l'ordre des `DELETE FROM <table>` dans `_wipe_test_data()`."""
        source = _JOURNEYS_FILE.read_text()
        # Isoler le corps de la fonction (du def jusqu'à la prochaine def/class)
        match = re.search(
            r"def _wipe_test_data\(\).*?(?=\n(?:def |class |\Z))",
            source,
            re.DOTALL,
        )
        assert match, "_wipe_test_data() introuvable dans test_critical_journeys_e2e.py"
        body = match.group(0)
        return re.findall(r"DELETE FROM (\w+)", body)

    def test_cash_journal_before_payments(self) -> None:
        order = self._delete_order()
        assert "cash_journal" in order, "cash_journal manquant dans _wipe_test_data()"
        assert "payments" in order, "payments manquant dans _wipe_test_data()"
        assert order.index("cash_journal") < order.index("payments"), (
            "cash_journal doit être supprimé AVANT payments (FK sur transaction_id)."
        )

    def test_payments_before_queue_tickets(self) -> None:
        order = self._delete_order()
        assert "queue_tickets" in order, "queue_tickets manquant dans _wipe_test_data()"
        assert order.index("payments") < order.index("queue_tickets"), (
            "payments doit être supprimé AVANT queue_tickets (FK queue_ticket_id)."
        )

    def test_queue_ticket_services_before_queue_tickets(self) -> None:
        order = self._delete_order()
        assert "queue_ticket_services" in order, (
            "queue_ticket_services manquant dans _wipe_test_data()"
        )
        assert order.index("queue_ticket_services") < order.index("queue_tickets"), (
            "queue_ticket_services doit être supprimé AVANT queue_tickets (jonction)."
        )

    def test_queue_tickets_before_customer_profiles(self) -> None:
        order = self._delete_order()
        assert "customer_profiles" in order, (
            "customer_profiles manquant dans _wipe_test_data()"
        )
        assert order.index("queue_tickets") < order.index("customer_profiles"), (
            "queue_tickets doit être supprimé AVANT customer_profiles "
            "(FK RESTRICT customer_profile_id)."
        )

    def test_salons_before_users(self) -> None:
        order = self._delete_order()
        assert "salons" in order, "salons manquant dans _wipe_test_data()"
        assert "users" in order, "users manquant dans _wipe_test_data()"
        assert order.index("salons") < order.index("users"), (
            "salons doit être supprimé AVANT users (owner_id FK)."
        )


class TestSkipMarkersPresent:
    """Les trois classes de parcours doivent toutes porter un `@pytest.mark.skipif`.

    Sans ce décorateur, le test lèverait une `OperationalError` (connexion PostgreSQL
    absente) au lieu d'un skip propre — régression silencieuse dans le gate ADW.
    """

    def test_all_journey_classes_have_skipif(self) -> None:
        source = _JOURNEYS_FILE.read_text()
        journey_classes = [
            "TestQueueJourneyE2E",
            "TestManagerQueueJourneyE2E",
            "TestCheckoutJourneyE2E",
        ]
        for cls in journey_classes:
            pattern = re.compile(
                r"@pytest\.mark\.skipif[^\n]*\nclass " + cls
            )
            assert pattern.search(source), (
                f"{cls} doit porter @pytest.mark.skipif immédiatement avant `class` "
                f"(skip propre sans DATABASE_URL)."
            )


class TestStrategyDocumentation:
    """Invariants documentaires : `strategie-de-tests.md` doit refléter #50 comme livré."""

    def _doc(self) -> str:
        return _STRATEGY_DOC.read_text()

    def test_strategy_doc_exists(self) -> None:
        assert _STRATEGY_DOC.exists(), (
            "docs/strategie-de-tests.md doit exister (document de référence de la stratégie)."
        )

    def test_strategy_doc_marks_50_as_delivered(self) -> None:
        doc = self._doc()
        assert "livré" in doc.lower() or "livré" in doc, (
            "docs/strategie-de-tests.md doit indiquer que #50 est livré."
        )
        assert "#50" in doc, (
            "docs/strategie-de-tests.md doit référencer #50."
        )

    def test_strategy_doc_references_critical_journeys_file(self) -> None:
        assert "test_critical_journeys_e2e.py" in self._doc(), (
            "docs/strategie-de-tests.md doit référencer test_critical_journeys_e2e.py."
        )

    def test_strategy_doc_mentions_phone_prefix_reservation(self) -> None:
        doc = self._doc()
        assert "plage de téléphones" in doc or "plage" in doc, (
            "docs/strategie-de-tests.md doit documenter la convention de plage de téléphones réservée "
            "pour les suites e2e de parcours."
        )
