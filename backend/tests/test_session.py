"""Tests pour normaliser_dsn() et database_url() (adapter sortant de persistance).

Vérifie les invariants de sécurité documentés par l'issue #5 :
- normalisation du driver psycopg 3 (ADR-0009) ;
- fail-fast explicite quand DATABASE_URL est absent ou vide — aucun défaut secret
  ne doit exister (politique de secrets, docs/environnements-et-secrets.md).
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch

import pytest

from coiflink_api.adapters.sortant.persistance.session import database_url, get_engine, normaliser_dsn


class TestNormaliserDsn:
    def test_postgresql_scheme_normalise_vers_psycopg(self) -> None:
        result = normaliser_dsn("postgresql://user:pwd@localhost:5432/db")
        assert result == "postgresql+psycopg://user:pwd@localhost:5432/db"

    def test_scheme_psycopg_deja_qualifie_reste_inchange(self) -> None:
        dsn = "postgresql+psycopg://user:pwd@localhost:5432/db"
        assert normaliser_dsn(dsn) == dsn

    def test_scheme_asyncpg_reste_inchange(self) -> None:
        dsn = "postgresql+asyncpg://user:pwd@localhost:5432/db"
        assert normaliser_dsn(dsn) == dsn

    def test_scheme_non_postgresql_reste_inchange(self) -> None:
        dsn = "sqlite:///local.db"
        assert normaliser_dsn(dsn) == dsn

    def test_suffixe_query_string_preservee(self) -> None:
        dsn = "postgresql://u:p@host:5432/mydb?sslmode=require"
        assert normaliser_dsn(dsn) == "postgresql+psycopg://u:p@host:5432/mydb?sslmode=require"

    def test_chaine_vide_reste_vide(self) -> None:
        assert normaliser_dsn("") == ""

    def test_remplace_seulement_le_prefixe(self) -> None:
        dsn = "postgresql://x:y@host/db"
        result = normaliser_dsn(dsn)
        assert result.count("postgresql") == 1
        assert result.startswith("postgresql+psycopg://")

    def test_postgres_scheme_court_passe_sans_normalisation(self) -> None:
        """postgres:// (schéma court, sans 'ql') n'est pas modifié par normaliser_dsn.

        Comportement connu et documenté : certains fournisseurs (Heroku, quelques
        configs Railway) retournent ce schéma court. Il doit être transformé en
        postgresql:// avant injection, par configuration de la plateforme.
        normaliser_dsn ne fait qu'ignorer ce cas — ce test protège contre une
        régression qui normaliserait le schéma court vers postgresql+psycopg://
        de façon incorrecte (le préfixe reste tel quel, l'appelant est responsable).
        """
        dsn = "postgres://u:p@host:5432/db"
        assert normaliser_dsn(dsn) == dsn


class TestDatabaseUrl:
    def test_leve_runtime_error_quand_variable_absente(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            database_url()

    def test_leve_runtime_error_quand_variable_vide(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "")
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            database_url()

    def test_leve_runtime_error_quand_variable_espaces_seuls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "   ")
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            database_url()

    def test_retourne_dsn_normalise_quand_defini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:secret@host:5432/db")
        result = database_url()
        assert result == "postgresql+psycopg://u:secret@host:5432/db"

    def test_preserves_dsn_deja_qualifie(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dsn = "postgresql+psycopg://u:p@host:5432/db"
        monkeypatch.setenv("DATABASE_URL", dsn)
        assert database_url() == dsn

    def test_supprime_espaces_en_tete_et_fin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "  postgresql://u:p@host:5432/db  ")
        result = database_url()
        assert result == "postgresql+psycopg://u:p@host:5432/db"


_SESSION_MODULE = "coiflink_api.adapters.sortant.persistance.session"


class TestGetEngine:
    """get_engine() : fail-fast si DATABASE_URL absent, mémoïsation via lru_cache.

    create_engine est mocké pour éviter toute dépendance au driver psycopg
    (non disponible dans l'environnement de test) — seul le comportement de
    get_engine (fail-fast, cache, normalisation du DSN) est testé ici.
    """

    _DSN = "postgresql://u:p@localhost:5432/testdb"
    _DSN_NORMALISE = "postgresql+psycopg://u:p@localhost:5432/testdb"

    def setup_method(self) -> None:
        get_engine.cache_clear()

    def teardown_method(self) -> None:
        get_engine.cache_clear()

    def test_leve_runtime_error_quand_database_url_absente(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            get_engine()

    def test_retourne_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", self._DSN)
        fake = MagicMock()
        with patch(f"{_SESSION_MODULE}.create_engine", return_value=fake):
            assert get_engine() is fake

    def test_memo_ise_meme_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", self._DSN)
        fake = MagicMock()
        with patch(f"{_SESSION_MODULE}.create_engine", return_value=fake) as mock_ce:
            e1 = get_engine()
            e2 = get_engine()
        assert e1 is e2
        mock_ce.assert_called_once()  # lru_cache : create_engine appelé une seule fois

    def test_dsn_normalise_transmis_a_create_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_engine doit passer le DSN normalisé (psycopg 3) à create_engine."""
        monkeypatch.setenv("DATABASE_URL", self._DSN)
        with patch(f"{_SESSION_MODULE}.create_engine", return_value=MagicMock()) as mock_ce:
            get_engine()
        dsn_utilise = mock_ce.call_args[0][0]
        assert dsn_utilise == self._DSN_NORMALISE
