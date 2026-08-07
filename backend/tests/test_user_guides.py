"""Tests de conformité documentaire pour les guides utilisateur (issue #53).

Ces tests vérifient des invariants *statiques* sur les fichiers Markdown de
``docs/guides/`` : existence, absence de signature IA, absence de PII/secret,
cohérence terminologique, présence des encadrés « À venir » requis, invariants
de confidentialité produit (note privée, isolation par salon) et résolution des
liens relatifs.

Aucune infrastructure live n'est requise — ces tests lisent uniquement des
fichiers du dépôt.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDES_DIR = REPO_ROOT / "docs" / "guides"

# Fichiers livrés par l'issue #53
_INDEX = GUIDES_DIR / "README.md"
_GUIDE_CLIENT = GUIDES_DIR / "guide-client.md"
_GUIDE_GERANT = GUIDES_DIR / "guide-gerant.md"

# Motif de signature IA — identique à la commande de vérification de la spec
_AI_SIGNATURE = re.compile(
    r"claude|anthropic|generated with|généré par\s+(?:l['’])?ia|🤖",
    re.IGNORECASE,
)

# Motifs indicatifs d'un vrai secret (réutilise la convention de test_secrets_policy.py)
_SUSPICIOUS_SECRET_PATTERNS = re.compile(
    r"ghp_[A-Za-z0-9]{36,}"
    r"|ghs_[A-Za-z0-9]{36,}"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|Bearer [A-Za-z0-9+/=]{20,}"
)

# Numéros de téléphone réels ivoiriens : +225 suivi de 10 chiffres sans espaces.
# Les guides doivent utiliser des exemples fictifs — on tolère des textes décrivant
# le concept (« numéro de téléphone ») mais pas de vrais numéros.
_REAL_IVORIAN_PHONE = re.compile(r"\+225\d{10}")

# Adresses e-mail réelles (motif simple : local@domain.tld)
_REAL_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]{2,}@[A-Za-z0-9.\-]{2,}\.[A-Za-z]{2,}")

# Adresses e-mail synthétiques autorisées dans les fixtures de test
_SYNTHETIC_EMAIL_WHITELIST = re.compile(
    r"@example\.com|@example\.org|@test\.|fictif|demo",
    re.IGNORECASE,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _has_real_email(content: str) -> bool:
    """Retourne True si le texte contient une adresse e-mail non-synthétique."""
    for match in _REAL_EMAIL.finditer(content):
        addr = match.group()
        if not _SYNTHETIC_EMAIL_WHITELIST.search(addr):
            return True
    return False


class TestGuideFilesExist:
    """Les trois fichiers de guides utilisateur (issue #53) doivent exister."""

    def test_guides_index_exists(self) -> None:
        assert _INDEX.exists(), (
            "docs/guides/README.md doit être créé par l'issue #53 "
            "(index des guides utilisateur)."
        )

    def test_guide_client_exists(self) -> None:
        assert _GUIDE_CLIENT.exists(), (
            "docs/guides/guide-client.md doit être créé par l'issue #53."
        )

    def test_guide_gerant_exists(self) -> None:
        assert _GUIDE_GERANT.exists(), (
            "docs/guides/guide-gerant.md doit être créé par l'issue #53."
        )

    def test_guides_dir_contains_only_expected_markdown_files(self) -> None:
        """Le dossier docs/guides/ ne doit contenir que les fichiers attendus."""
        md_files = {p.name for p in GUIDES_DIR.glob("*.md")}
        expected = {"README.md", "guide-client.md", "guide-gerant.md"}
        unexpected = md_files - expected
        assert not unexpected, (
            f"docs/guides/ contient des fichiers Markdown inattendus : {unexpected}. "
            "Si un nouveau guide est ajouté, mettez à jour ce test."
        )


class TestNoAiSignature:
    """Aucun fichier de docs/guides/ ne doit contenir de signature IA.

    Invariant de la spec : ``grep -riE "claude|anthropic|generated with|
    généré par (l'|l')?ia|🤖"`` sur ``docs/guides/`` — aucune correspondance.
    """

    @pytest.fixture(
        params=[_INDEX, _GUIDE_CLIENT, _GUIDE_GERANT],
        ids=["index", "guide-client", "guide-gerant"],
    )
    def guide_content(self, request) -> tuple[str, str]:
        path: Path = request.param
        return path.name, path.read_text(encoding="utf-8")

    def test_no_ai_signature(self, guide_content: tuple[str, str]) -> None:
        name, content = guide_content
        match = _AI_SIGNATURE.search(content)
        assert match is None, (
            f"docs/guides/{name} contient une signature IA interdite : "
            f"{match.group()!r} — aucune mention de 'Claude', 'Anthropic', "
            "'generated with', 'généré par IA' ni '🤖' autorisée."
        )


class TestNoPiiOrSecret:
    """Les guides ne doivent contenir ni PII réelle ni secret.

    Spec §Security : « les exemples sont fictifs et manifestement non réels ».
    """

    @pytest.fixture(
        params=[_INDEX, _GUIDE_CLIENT, _GUIDE_GERANT],
        ids=["index", "guide-client", "guide-gerant"],
    )
    def guide_content(self, request) -> tuple[str, str]:
        path: Path = request.param
        return path.name, path.read_text(encoding="utf-8")

    def test_no_suspicious_secret(self, guide_content: tuple[str, str]) -> None:
        name, content = guide_content
        assert not _SUSPICIOUS_SECRET_PATTERNS.search(content), (
            f"docs/guides/{name} contient un motif ressemblant à un vrai token/secret."
        )

    def test_no_real_ivorian_phone_number(self, guide_content: tuple[str, str]) -> None:
        name, content = guide_content
        match = _REAL_IVORIAN_PHONE.search(content)
        assert match is None, (
            f"docs/guides/{name} contient ce qui ressemble à un vrai numéro de téléphone "
            f"ivoirien (+225XXXXXXXXXX) : {match.group()!r}. "
            "Utilisez un préfixe manifestement fictif (ex. +225 00 00 00 00)."
        )

    def test_no_real_email_address(self, guide_content: tuple[str, str]) -> None:
        name, content = guide_content
        assert not _has_real_email(content), (
            f"docs/guides/{name} contient une adresse e-mail qui n'est pas "
            "manifestement fictive (@example.com…). Remplacez par un exemple fictif."
        )


class TestTerminologicalConsistency:
    """Les guides doivent utiliser les termes canoniques du produit.

    Spec §Testing : FCFA, Africa/Abidjan, termes d'IU tels qu'affichés.
    """

    def test_client_guide_mentions_fcfa(self) -> None:
        assert "FCFA" in _read(_GUIDE_CLIENT), (
            "guide-client.md doit mentionner la monnaie 'FCFA' (montants en FCFA)."
        )

    def test_gerant_guide_mentions_fcfa(self) -> None:
        assert "FCFA" in _read(_GUIDE_GERANT), (
            "guide-gerant.md doit mentionner la monnaie 'FCFA'."
        )

    def test_client_guide_mentions_abidjan_timezone(self) -> None:
        assert "Africa/Abidjan" in _read(_GUIDE_CLIENT), (
            "guide-client.md doit mentionner le fuseau 'Africa/Abidjan'."
        )

    def test_gerant_guide_mentions_abidjan_timezone(self) -> None:
        assert "Africa/Abidjan" in _read(_GUIDE_GERANT), (
            "guide-gerant.md doit mentionner le fuseau 'Africa/Abidjan'."
        )

    def test_client_guide_uses_mes_rendez_vous_term(self) -> None:
        assert "Mes rendez-vous" in _read(_GUIDE_CLIENT), (
            "guide-client.md doit employer le terme d'IU exact 'Mes rendez-vous'."
        )

    def test_client_guide_uses_mon_historique_term(self) -> None:
        assert "Mon historique" in _read(_GUIDE_CLIENT), (
            "guide-client.md doit employer le terme d'IU exact 'Mon historique'."
        )

    def test_gerant_guide_uses_encaissements_term(self) -> None:
        assert "Encaissements" in _read(_GUIDE_GERANT), (
            "guide-gerant.md doit employer le terme d'IU exact 'Encaissements'."
        )

    def test_gerant_guide_uses_planning_term(self) -> None:
        assert "Planning" in _read(_GUIDE_GERANT), (
            "guide-gerant.md doit employer le terme d'IU exact 'Planning'."
        )

    def test_gerant_guide_uses_prestations_term(self) -> None:
        assert "Prestations" in _read(_GUIDE_GERANT), (
            "guide-gerant.md doit employer le terme 'Prestations'."
        )

    def test_index_mentions_both_guides(self) -> None:
        content = _read(_INDEX)
        assert "guide-client" in content, (
            "docs/guides/README.md doit référencer guide-client.md."
        )
        assert "guide-gerant" in content, (
            "docs/guides/README.md doit référencer guide-gerant.md."
        )


class TestRequiredAVenirSections:
    """Les encadrés « À venir » sont obligatoires pour les étapes Must non exposées à l'IU.

    Spec §Proposed Implementation : documenter les limitations connues du MVP
    sans laisser croire que des fonctionnalités inexistantes sont disponibles.
    """

    def test_client_guide_has_a_venir_for_account_creation(self) -> None:
        content = _read(_GUIDE_CLIENT)
        assert "À venir" in content, (
            "guide-client.md doit contenir au moins un encadré 'À venir'."
        )
        assert re.search(r"cr[eé]er.{0,30}compte|compte.{0,20}cr[eé]ation|inscription", content, re.IGNORECASE), (
            "guide-client.md doit signaler que la création de compte / l'inscription "
            "depuis l'application n'est pas encore disponible (étape §5.1.2 non exposée à l'IU)."
        )

    def test_client_guide_has_a_venir_for_notifications(self) -> None:
        content = _read(_GUIDE_CLIENT)
        assert re.search(r"notification|rappel|SMS|confirmation", content, re.IGNORECASE), (
            "guide-client.md doit signaler que les notifications/rappels ne sont "
            "pas encore envoyés au MVP (étapes §5.1.8/§5.1.9 non exposées)."
        )
        assert re.search(r"pas encore\s+(?:envoy|reçu)|non.{0,10}envoy", content, re.IGNORECASE), (
            "guide-client.md doit clairement indiquer que les notifications "
            "ne sont PAS encore envoyées (état MVP)."
        )

    def test_client_guide_has_a_venir_for_receipt(self) -> None:
        content = _read(_GUIDE_CLIENT)
        assert re.search(r"reçu.{0,40}(pas encore|à venir)|à venir.{0,80}reçu", content, re.IGNORECASE), (
            "guide-client.md doit signaler que le reçu de paiement n'est pas encore "
            "consultable dans l'application (étape §5.3.9 partiellement couverte)."
        )

    def test_gerant_guide_has_a_venir_for_cash_journal(self) -> None:
        content = _read(_GUIDE_GERANT)
        assert re.search(r"journal.{0,20}(caisse|cais)|caisse.{0,20}journal", content, re.IGNORECASE), (
            "guide-gerant.md doit mentionner le journal de caisse."
        )
        assert re.search(
            r"journal.{0,40}pas encore|pas encore.{0,40}journal|à venir.{0,80}journal",
            content, re.IGNORECASE,
        ), (
            "guide-gerant.md doit signaler que le journal de caisse n'est pas encore "
            "disponible dans l'interface web (livré côté serveur seulement — #34)."
        )

    def test_gerant_guide_has_a_venir_for_admin_zone(self) -> None:
        content = _read(_GUIDE_GERANT)
        assert re.search(
            r"(admin|administration|zone\s+d.administration).{0,60}(pas encore|à venir|n.existe pas)",
            content, re.IGNORECASE,
        ), (
            "guide-gerant.md doit signaler que la zone d'administration "
            "n'existe pas encore dans l'interface web (backend-only)."
        )

    def test_gerant_guide_has_a_venir_for_employee_management(self) -> None:
        content = _read(_GUIDE_GERANT)
        assert re.search(
            r"(employ[eé]s?|coiffeurs?).{0,80}(pas encore|n.existe pas|à venir)",
            content, re.IGNORECASE,
        ), (
            "guide-gerant.md doit signaler que la gestion des employés "
            "n'est pas encore disponible dans l'interface web (backend-only — #13)."
        )

    def test_gerant_guide_has_a_venir_for_notifications_not_sent(self) -> None:
        content = _read(_GUIDE_GERANT)
        # re.DOTALL allows .{0,N} to cross line boundaries (sentence may span two lines).
        assert re.search(
            r"notification.{0,80}(pas encore\s+envoy|enregistr.{0,30}pas.{0,20}envoy|non.{0,10}envoy)",
            content, re.IGNORECASE | re.DOTALL,
        ), (
            "guide-gerant.md doit signaler que les notifications au salon "
            "et au client ne sont pas encore envoyées au MVP (#45–#48)."
        )


class TestSecurityInvariants:
    """Les guides doivent refléter fidèlement les invariants de confidentialité du produit.

    Spec §Security : ne pas affaiblir les garanties documentées (note privée §11.3,
    isolation par salon §11.2, non-remise des notifications ADR-0006).
    """

    def test_gerant_guide_private_note_visible_only_to_salon(self) -> None:
        content = _read(_GUIDE_GERANT)
        assert re.search(
            r"note.{0,30}(uniquement|jamais|interne|invisible|confidentielle?)",
            content, re.IGNORECASE,
        ), (
            "guide-gerant.md doit stipuler que la note client privée est "
            "visible uniquement par le salon et jamais par le client (§11.3 / #32)."
        )

    def test_gerant_guide_private_note_never_visible_to_client(self) -> None:
        content = _read(_GUIDE_GERANT)
        # La note doit être qualifiée de « jamais » partagée / vue par le client.
        assert re.search(
            r"jamais.{0,30}(partagé|visible|client)|note.{0,60}jamais",
            content, re.IGNORECASE,
        ), (
            "guide-gerant.md doit préciser que la note privée n'est JAMAIS "
            "partagée avec le client (invariant §11.3)."
        )

    def test_gerant_guide_states_salon_isolation(self) -> None:
        content = _read(_GUIDE_GERANT)
        assert re.search(
            r"(ne voyez que|ne voit que|seulement votre).{0,30}(salon|données)",
            content, re.IGNORECASE,
        ), (
            "guide-gerant.md doit préciser que le gérant ne voit que son propre salon "
            "(isolation par salon §11.2 / RBAC deny-by-default ADR-0015)."
        )

    def test_client_guide_does_not_imply_notifications_are_sent(self) -> None:
        """Le guide client ne doit pas laisser croire que les rappels SMS sont envoyés."""
        content = _read(_GUIDE_CLIENT)
        # Il ne doit PAS exister une phrase affirmant que le client « reçoit » un SMS/rappel
        # sans la nuancer par « pas encore » ou un encadré « À venir ».
        # On vérifie qu'une telle affirmation non nuancée est absente.
        # Heuristique : "vous recevrez" / "vous recevez" suivi de SMS/rappel sans négation
        # dans la même phrase.
        lines_with_positive_delivery = [
            line for line in content.splitlines()
            if re.search(r"vous receve[zr]|vous sera.{0,10}envoy", line, re.IGNORECASE)
            and re.search(r"SMS|rappel|notification|confirmation", line, re.IGNORECASE)
            and not re.search(r"pas encore|n.est pas|jamais|à venir", line, re.IGNORECASE)
        ]
        assert not lines_with_positive_delivery, (
            "guide-client.md contient des affirmations impliquant que des "
            "SMS/notifications sont envoyés au MVP, sans mise en garde 'pas encore' : "
            + str(lines_with_positive_delivery)
        )

    def test_gerant_guide_does_not_describe_admin_web_ui_as_available(self) -> None:
        """La zone admin web n'existe pas — le guide ne doit pas la décrire comme accessible."""
        content = _read(_GUIDE_GERANT)
        # Le guide ne doit pas contenir de marche à suivre pour atteindre /admin
        # sans signaler que la zone n'existe pas encore.
        lines_describing_admin = [
            line for line in content.splitlines()
            if re.search(r"/admin|espace.{0,10}admin|zone.{0,10}admin", line, re.IGNORECASE)
            and not re.search(r"pas encore|n.existe pas|à venir|non.{0,10}disponible", line, re.IGNORECASE)
        ]
        assert not lines_describing_admin, (
            "guide-gerant.md décrit la zone /admin comme accessible alors "
            "qu'elle n'existe pas encore dans l'interface web : "
            + str(lines_describing_admin)
        )

    def test_gerant_guide_does_not_describe_employee_web_page_as_available(self) -> None:
        """Il n'y a pas de page web de gestion des employés — le guide ne doit pas l'impliquer."""
        content = _read(_GUIDE_GERANT)
        # On recherche une instruction active (impérative ou présente) de navigation
        # vers une page employés, sans encadré « À venir ».
        lines_with_employee_nav = [
            line for line in content.splitlines()
            if re.search(
                r"(?:ouvrez|allez|rendez-vous|cliquez).{0,40}employ[eé]s?",
                line, re.IGNORECASE,
            )
            and not re.search(r"pas encore|à venir|n.existe pas", line, re.IGNORECASE)
        ]
        assert not lines_with_employee_nav, (
            "guide-gerant.md contient des instructions de navigation vers une page "
            "de gestion des employés qui n'existe pas encore dans l'IU web (#13 backend-only) : "
            + str(lines_with_employee_nav)
        )


class TestRelativeLinkResolution:
    """Les liens relatifs entre les guides doivent pointer vers des fichiers existants.

    Spec §Testing : tous les liens relatifs (vers ADR, PRD, README, entre guides) résolvent.
    """

    @staticmethod
    def _extract_relative_md_links(content: str) -> list[str]:
        """Extrait les cibles de liens Markdown qui commencent par '.' (relatifs)."""
        return re.findall(r"\[.*?\]\((\.[^)#\s]+)", content)

    def _resolve(self, source: Path, target: str) -> Path:
        return (source.parent / target).resolve()

    def test_index_links_resolve(self) -> None:
        content = _read(_INDEX)
        links = self._extract_relative_md_links(content)
        assert links, "docs/guides/README.md doit contenir des liens relatifs."
        for target in links:
            resolved = self._resolve(_INDEX, target)
            assert resolved.exists(), (
                f"docs/guides/README.md : le lien relatif '{target}' ne résout pas "
                f"(attendu : {resolved})."
            )

    def test_client_guide_links_resolve(self) -> None:
        content = _read(_GUIDE_CLIENT)
        for target in self._extract_relative_md_links(content):
            resolved = self._resolve(_GUIDE_CLIENT, target)
            assert resolved.exists(), (
                f"docs/guides/guide-client.md : le lien relatif '{target}' ne résout pas "
                f"(attendu : {resolved})."
            )

    def test_gerant_guide_links_resolve(self) -> None:
        content = _read(_GUIDE_GERANT)
        for target in self._extract_relative_md_links(content):
            resolved = self._resolve(_GUIDE_GERANT, target)
            assert resolved.exists(), (
                f"docs/guides/guide-gerant.md : le lien relatif '{target}' ne résout pas "
                f"(attendu : {resolved})."
            )

    def test_index_references_guide_client(self) -> None:
        content = _read(_INDEX)
        links = self._extract_relative_md_links(content)
        assert any("guide-client" in t for t in links), (
            "docs/guides/README.md doit contenir un lien relatif vers guide-client.md."
        )

    def test_index_references_guide_gerant(self) -> None:
        content = _read(_INDEX)
        links = self._extract_relative_md_links(content)
        assert any("guide-gerant" in t for t in links), (
            "docs/guides/README.md doit contenir un lien relatif vers guide-gerant.md."
        )

    def test_index_references_prd(self) -> None:
        content = _read(_INDEX)
        assert "prd-coiflink" in content, (
            "docs/guides/README.md doit référencer prd-coiflink.md (source de vérité produit)."
        )


class TestTraceabilityTables:
    """Chaque guide doit contenir un tableau de traçabilité « section → issue/US ».

    Spec §Proposed Implementation : faciliter la maintenance et éviter la dérive
    documentaire quand de nouvelles issues livrent des fonctionnalités.
    """

    def test_client_guide_has_traceability_section(self) -> None:
        content = _read(_GUIDE_CLIENT)
        assert re.search(r"d.o[uù]\s+vient|traçabilité|source\s+produit", content, re.IGNORECASE), (
            "guide-client.md doit contenir un tableau de traçabilité "
            "'D'où vient chaque fonctionnalité' (lien section → issue)."
        )

    def test_client_guide_traceability_references_booking_issue(self) -> None:
        content = _read(_GUIDE_CLIENT)
        assert "#22" in content, (
            "La table de traçabilité de guide-client.md doit référencer #22 "
            "(tunnel de réservation client)."
        )

    def test_client_guide_traceability_references_search_issue(self) -> None:
        content = _read(_GUIDE_CLIENT)
        assert "#18" in content, (
            "La table de traçabilité de guide-client.md doit référencer #18 "
            "(recherche / liste des salons)."
        )

    def test_gerant_guide_has_traceability_section(self) -> None:
        content = _read(_GUIDE_GERANT)
        assert re.search(r"d.o[uù]\s+vient|traçabilité|source\s+produit", content, re.IGNORECASE), (
            "guide-gerant.md doit contenir un tableau de traçabilité "
            "'D'où vient chaque fonctionnalité' (lien section → issue)."
        )

    def test_gerant_guide_traceability_references_payment_issue(self) -> None:
        content = _read(_GUIDE_GERANT)
        assert "#33" in content, (
            "La table de traçabilité de guide-gerant.md doit référencer #33 "
            "(enregistrement d'un paiement)."
        )

    def test_gerant_guide_traceability_references_dashboard_issues(self) -> None:
        content = _read(_GUIDE_GERANT)
        assert "#39" in content, (
            "La table de traçabilité de guide-gerant.md doit référencer #39 "
            "(RDV du jour)."
        )


class TestRootReadmeUpdated:
    """Le README.md racine doit référencer docs/guides/ après l'issue #53.

    Spec §Implementation Checklist étape 6 : §5 (structure) et §9 (références).
    """

    def test_readme_structure_mentions_guides_dir(self) -> None:
        content = _read(REPO_ROOT / "README.md")
        assert "docs/guides" in content, (
            "README.md doit mentionner docs/guides/ dans la section structure du dépôt (§5)."
        )

    def test_readme_references_guide_client(self) -> None:
        content = _read(REPO_ROOT / "README.md")
        assert "guide-client" in content, (
            "README.md doit référencer docs/guides/guide-client.md dans ses références (§9)."
        )

    def test_readme_references_guide_gerant(self) -> None:
        content = _read(REPO_ROOT / "README.md")
        assert "guide-gerant" in content, (
            "README.md doit référencer docs/guides/guide-gerant.md dans ses références (§9)."
        )

    def test_readme_guides_link_resolves(self) -> None:
        """Le lien docs/guides/README.md cité dans le README racine doit pointer vers un fichier réel."""
        readme = REPO_ROOT / "README.md"
        content = _read(readme)
        links = re.findall(r"\[.*?\]\((\./docs/guides/[^)#\s]*)", content)
        for target in links:
            resolved = (readme.parent / target).resolve()
            assert resolved.exists(), (
                f"README.md : le lien '{target}' vers docs/guides/ ne résout pas "
                f"(attendu : {resolved})."
            )
