"""Tests de régression sécurité / politique de secrets (issue #5).

Ces tests vérifient des invariants *statiques* sur les fichiers du dépôt :
- .gitignore exclut bien tous les fichiers .env réels et ne cache jamais les .env.example ;
- les fichiers .env.example ne contiennent que des placeholders (secrets vides ou fictifs) ;
- docker-compose.yml utilise la syntaxe :? (fail-fast) pour les secrets requis ;
- les configs Railway ne contiennent pas de secrets en dur.

Aucune infrastructure live n'est requise — ces tests lisent uniquement des fichiers du dépôt.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# Motifs indicatifs d'un vrai secret (token GitHub, clé OpenAI, etc.)
_PATTERNS_SECRET_SUSPECTS = re.compile(
    r"ghp_[A-Za-z0-9]{36,}"          # GitHub PAT
    r"|ghs_[A-Za-z0-9]{36,}"          # GitHub App token
    r"|sk-[A-Za-z0-9]{20,}"           # OpenAI / Stripe secret key
    r"|Bearer [A-Za-z0-9+/=]{20,}"    # Bearer token en clair
)


class TestGitignoreExclusionSecrets:
    """Régression : .gitignore doit continuer à exclure tous les vrais fichiers .env."""

    @pytest.fixture
    def gitignore_lines(self) -> list[str]:
        return (REPO_ROOT / ".gitignore").read_text().splitlines()

    def test_backend_dotenv_exclu(self, gitignore_lines: list[str]) -> None:
        assert any(line.strip() == "backend/.env" for line in gitignore_lines)

    def test_deploy_dotenv_exclu(self, gitignore_lines: list[str]) -> None:
        assert any(line.strip() == "deploy/.env" for line in gitignore_lines)

    def test_web_dashboard_dotenv_local_exclu(self, gitignore_lines: list[str]) -> None:
        assert any(
            "web-dashboard" in line and ".env" in line and not line.strip().startswith("#")
            for line in gitignore_lines
        )

    def test_app_mobile_dotenv_exclu(self, gitignore_lines: list[str]) -> None:
        assert any(line.strip() == "app-mobile/.env" for line in gitignore_lines)

    def test_adw_env_exclu(self, gitignore_lines: list[str]) -> None:
        assert any(line.strip() == "scripts/adw.env" for line in gitignore_lines)

    def test_env_example_non_ignore(self, gitignore_lines: list[str]) -> None:
        """Les .env.example (placeholders) doivent rester versionnés — jamais ignorés."""
        actif = [ln for ln in gitignore_lines if not ln.strip().startswith("#") and ln.strip()]
        assert not any("env.example" in line for line in actif), (
            "Un motif dans .gitignore ignore les fichiers .env.example — "
            "ils doivent rester versionnés car ils ne contiennent que des placeholders."
        )


class TestEnvExamplePlaceholders:
    """Les variables secrètes dans les .env.example doivent rester vides ou fictives."""

    @staticmethod
    def _valeur(lines: list[str], cle: str) -> str | None:
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(f"{cle}="):
                return stripped[len(f"{cle}="):]
        return None

    @staticmethod
    def _lire(chemin: Path) -> list[str]:
        return chemin.read_text().splitlines()

    # --- backend/.env.example ---

    def test_backend_jwt_secret_est_vide(self) -> None:
        lines = self._lire(REPO_ROOT / "backend" / ".env.example")
        valeur = self._valeur(lines, "JWT_SECRET")
        assert valeur is not None, "JWT_SECRET doit être présent dans backend/.env.example"
        assert valeur.strip() == "", f"JWT_SECRET doit être vide dans backend/.env.example, reçu : {valeur!r}"

    def test_backend_database_url_est_un_placeholder(self) -> None:
        lines = self._lire(REPO_ROOT / "backend" / ".env.example")
        valeur = self._valeur(lines, "DATABASE_URL")
        assert valeur is not None
        assert re.search(r"password|<|exemple|placeholder", valeur, re.IGNORECASE), (
            f"DATABASE_URL dans backend/.env.example doit être un placeholder, reçu : {valeur!r}"
        )

    def test_backend_pas_de_secret_suspect(self) -> None:
        contenu = (REPO_ROOT / "backend" / ".env.example").read_text()
        assert not _PATTERNS_SECRET_SUSPECTS.search(contenu), (
            "backend/.env.example contient un motif ressemblant à un vrai token/secret."
        )

    # --- deploy/.env.example ---

    def test_deploy_jwt_secret_est_vide(self) -> None:
        lines = self._lire(REPO_ROOT / "deploy" / ".env.example")
        valeur = self._valeur(lines, "JWT_SECRET")
        assert valeur is not None, "JWT_SECRET doit être présent dans deploy/.env.example"
        assert valeur.strip() == "", f"JWT_SECRET doit être vide dans deploy/.env.example, reçu : {valeur!r}"

    def test_deploy_postgres_password_est_vide(self) -> None:
        lines = self._lire(REPO_ROOT / "deploy" / ".env.example")
        valeur = self._valeur(lines, "POSTGRES_PASSWORD")
        assert valeur is not None, "POSTGRES_PASSWORD doit être présent dans deploy/.env.example"
        assert valeur.strip() == "", (
            f"POSTGRES_PASSWORD doit être vide dans deploy/.env.example, reçu : {valeur!r}"
        )

    def test_deploy_database_url_est_un_placeholder(self) -> None:
        lines = self._lire(REPO_ROOT / "deploy" / ".env.example")
        valeur = self._valeur(lines, "DATABASE_URL")
        assert valeur is not None
        assert "<" in valeur or re.search(r"password|placeholder", valeur, re.IGNORECASE), (
            f"DATABASE_URL dans deploy/.env.example doit être un placeholder, reçu : {valeur!r}"
        )

    def test_deploy_pas_de_secret_suspect(self) -> None:
        contenu = (REPO_ROOT / "deploy" / ".env.example").read_text()
        assert not _PATTERNS_SECRET_SUSPECTS.search(contenu), (
            "deploy/.env.example contient un motif ressemblant à un vrai token/secret."
        )

    # --- web-dashboard/.env.example ---

    def test_web_next_public_api_base_url_est_vide_ou_localhost(self) -> None:
        lines = self._lire(REPO_ROOT / "web-dashboard" / ".env.example")
        valeur = self._valeur(lines, "NEXT_PUBLIC_API_BASE_URL")
        assert valeur is not None, "NEXT_PUBLIC_API_BASE_URL doit être présent dans web-dashboard/.env.example"
        assert valeur.strip() == "" or "localhost" in valeur, (
            f"NEXT_PUBLIC_API_BASE_URL dans web-dashboard/.env.example doit être vide ou localhost, "
            f"reçu : {valeur!r}"
        )

    def test_web_pas_de_secret_suspect(self) -> None:
        contenu = (REPO_ROOT / "web-dashboard" / ".env.example").read_text()
        assert not _PATTERNS_SECRET_SUSPECTS.search(contenu), (
            "web-dashboard/.env.example contient un motif ressemblant à un vrai token/secret."
        )

    # --- invariants APP_ENV / IMAGE_TAG (ne jamais committer staging/prod comme valeur locale) ---

    def test_backend_app_env_est_development(self) -> None:
        lines = self._lire(REPO_ROOT / "backend" / ".env.example")
        valeur = self._valeur(lines, "APP_ENV")
        assert valeur is not None, "APP_ENV doit être présent dans backend/.env.example"
        assert valeur.strip() == "development", (
            f"APP_ENV dans backend/.env.example doit être 'development', reçu : {valeur!r} — "
            "ne jamais committer 'staging' ou 'production' comme valeur locale par défaut."
        )

    def test_deploy_app_env_est_development(self) -> None:
        lines = self._lire(REPO_ROOT / "deploy" / ".env.example")
        valeur = self._valeur(lines, "APP_ENV")
        assert valeur is not None, "APP_ENV doit être présent dans deploy/.env.example"
        assert valeur.strip() == "development", (
            f"APP_ENV dans deploy/.env.example doit être 'development', reçu : {valeur!r}"
        )

    def test_deploy_image_tag_est_local(self) -> None:
        """IMAGE_TAG=local garantit que docker compose utilise un build local, jamais une image de prod."""
        lines = self._lire(REPO_ROOT / "deploy" / ".env.example")
        valeur = self._valeur(lines, "IMAGE_TAG")
        assert valeur is not None, "IMAGE_TAG doit être présent dans deploy/.env.example"
        assert valeur.strip() == "local", (
            f"IMAGE_TAG dans deploy/.env.example doit être 'local', reçu : {valeur!r}"
        )

    def test_web_env_example_ne_contient_pas_secrets_backend(self) -> None:
        """web-dashboard/.env.example ne doit pas exposer de secrets appartenant au backend."""
        lines = self._lire(REPO_ROOT / "web-dashboard" / ".env.example")
        noms = {
            ln.split("=")[0].strip()
            for ln in lines
            if "=" in ln and not ln.strip().startswith("#")
        }
        for secret_backend in ("DATABASE_URL", "JWT_SECRET", "REDIS_URL"):
            assert secret_backend not in noms, (
                f"web-dashboard/.env.example contient {secret_backend} — "
                "les secrets backend ne doivent pas figurer dans l'env du frontend."
            )

    def test_backend_env_example_ne_contient_pas_variables_futures(self) -> None:
        """backend/.env.example ne doit pas lister de variables pour des intégrations non câblées."""
        lines = self._lire(REPO_ROOT / "backend" / ".env.example")
        noms = {
            ln.split("=")[0].strip()
            for ln in lines
            if "=" in ln and not ln.strip().startswith("#")
        }
        for var_future in ("S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "FCM_SERVER_KEY"):
            assert var_future not in noms, (
                f"backend/.env.example contient {var_future} qui correspond à une intégration "
                "non implémentée — ne pas ajouter de variables non lues par le code."
            )


class TestDockerComposeFaillFastSecrets:
    """docker-compose.yml doit utiliser la syntaxe :? pour les secrets requis (fail-fast)."""

    @pytest.fixture
    def compose_raw(self) -> str:
        return (REPO_ROOT / "deploy" / "docker-compose.yml").read_text()

    @pytest.fixture
    def compose(self, compose_raw: str) -> dict:
        return yaml.safe_load(compose_raw)

    def test_yaml_valide(self, compose: dict) -> None:
        assert isinstance(compose, dict)

    def test_quatre_services_definis(self, compose: dict) -> None:
        services = compose.get("services", {})
        assert set(services.keys()) >= {"postgres", "redis", "backend", "web"}

    def test_postgres_password_utilise_syntaxe_fail_fast(self, compose_raw: str) -> None:
        """${POSTGRES_PASSWORD:?...} ne doit PAS avoir de valeur par défaut silencieuse."""
        assert "POSTGRES_PASSWORD:?" in compose_raw, (
            "POSTGRES_PASSWORD doit utiliser la syntaxe :? dans docker-compose.yml "
            "(fail-fast si non défini)."
        )

    def test_database_url_utilise_syntaxe_fail_fast(self, compose_raw: str) -> None:
        """${DATABASE_URL:?...} — le backend ne doit pas démarrer sans DSN explicite."""
        assert "DATABASE_URL:?" in compose_raw, (
            "DATABASE_URL doit utiliser la syntaxe :? dans docker-compose.yml "
            "(fail-fast si non défini)."
        )

    def test_postgres_a_un_healthcheck(self, compose: dict) -> None:
        assert "healthcheck" in compose["services"]["postgres"]

    def test_redis_a_un_healthcheck(self, compose: dict) -> None:
        assert "healthcheck" in compose["services"]["redis"]

    def test_backend_depend_de_postgres_et_redis(self, compose: dict) -> None:
        deps = compose["services"]["backend"].get("depends_on", {})
        assert "postgres" in deps
        assert "redis" in deps

    def test_web_depend_du_backend(self, compose: dict) -> None:
        deps = compose["services"]["web"].get("depends_on", {})
        assert "backend" in deps

    def test_pas_de_secret_suspect_dans_compose(self, compose_raw: str) -> None:
        assert not _PATTERNS_SECRET_SUSPECTS.search(compose_raw), (
            "docker-compose.yml contient un motif ressemblant à un vrai token/secret."
        )

    def test_next_public_prefixe_non_expose_comme_secret(self, compose_raw: str) -> None:
        """NEXT_PUBLIC_* ne doit jamais figurer côté backend (exposé navigateur)."""
        backend_section = compose_raw.split("web:")[0]
        assert "NEXT_PUBLIC_" not in backend_section.split("backend:")[1] if "backend:" in backend_section else True

    def test_next_public_dans_service_web_uniquement(self, compose: dict) -> None:
        """NEXT_PUBLIC_API_BASE_URL doit figurer dans le service web et non dans le backend."""
        web_env = compose["services"]["web"].get("environment", {})
        assert "NEXT_PUBLIC_API_BASE_URL" in web_env, (
            "NEXT_PUBLIC_API_BASE_URL doit être défini dans le service web du docker-compose."
        )
        backend_env = compose["services"]["backend"].get("environment", {})
        assert not any(k.startswith("NEXT_PUBLIC_") for k in backend_env), (
            "Aucune variable NEXT_PUBLIC_* ne doit figurer dans l'environnement du service backend "
            "(ces variables sont exposées au navigateur)."
        )

    def test_backend_service_a_un_healthcheck(self, compose: dict) -> None:
        assert "healthcheck" in compose["services"]["backend"], (
            "Le service backend doit déclarer un healthcheck dans docker-compose.yml."
        )

    def test_volumes_definis(self, compose: dict) -> None:
        volumes = compose.get("volumes", {})
        assert "pgdata" in volumes, "Le volume pgdata doit être déclaré au niveau racine."
        assert "redisdata" in volumes, "Le volume redisdata doit être déclaré au niveau racine."

    def test_jwt_secret_utilise_defaut_silencieux_non_fail_fast(self, compose_raw: str) -> None:
        """JWT_SECRET doit utiliser ${JWT_SECRET:-} (défaut vide, non fail-fast) — non requis avant #8 (auth).

        La syntaxe :? serait prématurément fail-fast : JWT_SECRET n'est consommé
        qu'à partir de l'issue #8. Ce test documente le choix délibéré et empêche
        une régression vers :? qui casserait `docker compose up` avant #8.
        """
        assert "JWT_SECRET:-}" in compose_raw, (
            "JWT_SECRET dans docker-compose.yml doit utiliser la syntaxe ${JWT_SECRET:-} "
            "(défaut vide) et non :? — non requis avant #8 (auth)."
        )
        assert "JWT_SECRET:?" not in compose_raw, (
            "JWT_SECRET ne doit pas utiliser la syntaxe fail-fast :? avant #8."
        )


class TestRailwayConfigPasDeSectrets:
    """Les fichiers de config Railway ne doivent pas intégrer de secrets en dur."""

    def test_backend_json_valide(self) -> None:
        data = json.loads((REPO_ROOT / "deploy" / "railway" / "backend.json").read_text())
        assert "build" in data
        assert "deploy" in data

    def test_web_json_valide(self) -> None:
        data = json.loads((REPO_ROOT / "deploy" / "railway" / "web.json").read_text())
        assert "build" in data
        assert "deploy" in data

    def test_backend_healthcheck_pointe_vers_health(self) -> None:
        data = json.loads((REPO_ROOT / "deploy" / "railway" / "backend.json").read_text())
        assert data["deploy"]["healthcheckPath"] == "/health"

    def test_backend_builder_est_dockerfile(self) -> None:
        data = json.loads((REPO_ROOT / "deploy" / "railway" / "backend.json").read_text())
        assert data["build"]["builder"] == "DOCKERFILE"

    def test_backend_json_pas_de_secret_suspect(self) -> None:
        contenu = (REPO_ROOT / "deploy" / "railway" / "backend.json").read_text()
        assert not _PATTERNS_SECRET_SUSPECTS.search(contenu)

    def test_web_json_pas_de_secret_suspect(self) -> None:
        contenu = (REPO_ROOT / "deploy" / "railway" / "web.json").read_text()
        assert not _PATTERNS_SECRET_SUSPECTS.search(contenu)

    def test_backend_json_pas_de_champ_variables_avec_valeurs(self) -> None:
        """Le JSON Railway ne doit décrire que la topologie, pas les valeurs de variables."""
        data = json.loads((REPO_ROOT / "deploy" / "railway" / "backend.json").read_text())
        # Un champ "variables" avec des valeurs serait une fuite de secrets potentielle.
        variables = data.get("variables", {})
        assert not any(v for v in variables.values() if v), (
            "deploy/railway/backend.json contient des valeurs de variables — "
            "les secrets doivent vivre dans le magasin de la plateforme, pas dans le dépôt."
        )

    def test_web_json_pas_de_champ_variables_avec_valeurs(self) -> None:
        """Le JSON Railway web ne doit pas non plus intégrer de valeurs de variables."""
        data = json.loads((REPO_ROOT / "deploy" / "railway" / "web.json").read_text())
        variables = data.get("variables", {})
        assert not any(v for v in variables.values() if v), (
            "deploy/railway/web.json contient des valeurs de variables — "
            "les secrets doivent vivre dans le magasin de la plateforme, pas dans le dépôt."
        )


class TestDocumentationArtefacts:
    """Les artefacts documentaires créés par l'issue #5 doivent exister et couvrir les sections clés."""

    def test_adr_0011_existe(self) -> None:
        assert (REPO_ROOT / "docs" / "adr" / "0011-deploiement-environnements-secrets.md").exists(), (
            "docs/adr/0011-deploiement-environnements-secrets.md doit être créé par l'issue #5."
        )

    def test_doc_environnements_secrets_existe(self) -> None:
        assert (REPO_ROOT / "docs" / "environnements-et-secrets.md").exists(), (
            "docs/environnements-et-secrets.md doit être créé par l'issue #5."
        )

    def test_deploy_docker_compose_existe(self) -> None:
        assert (REPO_ROOT / "deploy" / "docker-compose.yml").exists(), (
            "deploy/docker-compose.yml doit être créé par l'issue #5."
        )

    def test_deploy_env_example_existe(self) -> None:
        assert (REPO_ROOT / "deploy" / ".env.example").exists(), (
            "deploy/.env.example doit être créé par l'issue #5."
        )

    def test_adr_0011_statut_accepte(self) -> None:
        contenu = (REPO_ROOT / "docs" / "adr" / "0011-deploiement-environnements-secrets.md").read_text()
        assert "Accepté" in contenu or "accepté" in contenu.lower(), (
            "ADR-0011 doit être au statut Accepté."
        )

    def test_politique_mentionne_rotation(self) -> None:
        contenu = (REPO_ROOT / "docs" / "environnements-et-secrets.md").read_text().lower()
        assert "rotation" in contenu, (
            "La politique de secrets doit documenter la rotation des secrets."
        )

    def test_politique_mentionne_non_journalisation(self) -> None:
        contenu = (REPO_ROOT / "docs" / "environnements-et-secrets.md").read_text().lower()
        assert "journali" in contenu, (
            "La politique de secrets doit documenter la règle de non-journalisation."
        )

    def test_politique_mentionne_moindre_privilege(self) -> None:
        contenu = (REPO_ROOT / "docs" / "environnements-et-secrets.md").read_text().lower()
        assert "moindre privilège" in contenu or "least privilege" in contenu, (
            "La politique de secrets doit documenter le principe du moindre privilège."
        )

    def test_matrice_couvre_variables_backend(self) -> None:
        contenu = (REPO_ROOT / "docs" / "environnements-et-secrets.md").read_text()
        for var in ("DATABASE_URL", "REDIS_URL", "JWT_SECRET", "APP_NAME", "APP_ENV"):
            assert var in contenu, (
                f"{var} doit figurer dans la matrice de configuration (docs/environnements-et-secrets.md)."
            )

    def test_matrice_couvre_variable_web(self) -> None:
        contenu = (REPO_ROOT / "docs" / "environnements-et-secrets.md").read_text()
        assert "NEXT_PUBLIC_API_BASE_URL" in contenu, (
            "NEXT_PUBLIC_API_BASE_URL doit figurer dans la matrice de configuration."
        )

    def test_politique_mentionne_fuite(self) -> None:
        contenu = (REPO_ROOT / "docs" / "environnements-et-secrets.md").read_text().lower()
        assert "fuite" in contenu or "compromis" in contenu, (
            "La politique de secrets doit documenter la conduite en cas de fuite "
            "(révoquer, régénérer, purger, auditer)."
        )

    def test_contributing_reference_politique_secrets(self) -> None:
        """CONTRIBUTING.md doit référencer la politique de secrets écrite (docs/environnements-et-secrets.md)."""
        contenu = (REPO_ROOT / "CONTRIBUTING.md").read_text()
        assert "environnements-et-secrets" in contenu, (
            "CONTRIBUTING.md doit renvoyer à docs/environnements-et-secrets.md "
            "dans sa section Secrets."
        )

    def test_adr_readme_indexe_adr_0011(self) -> None:
        """docs/adr/README.md doit indexer ADR-0011."""
        contenu = (REPO_ROOT / "docs" / "adr" / "README.md").read_text()
        assert "0011" in contenu, (
            "docs/adr/README.md doit référencer ADR-0011 dans son index."
        )


# ---------------------------------------------------------------------------
# Helpers privés pour les tests Dockerfile
# ---------------------------------------------------------------------------

_SECRET_ENV_PATTERN = re.compile(
    r"^\s*(?:DATABASE_URL|JWT_SECRET|REDIS_URL|POSTGRES_PASSWORD|SECRET_KEY)\s*=",
    re.MULTILINE,
)


def _non_comments(text: str) -> str:
    """Supprime les lignes de commentaire d'un Dockerfile pour éviter les faux positifs."""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


class TestDockerfileSecurite:
    """Les Dockerfiles ne doivent pas intégrer de secrets ni copier de fichiers .env.

    Invariant « images Docker sans secret intégré » (spec #4/ADR-0010, renforcé par #5).
    """

    @staticmethod
    def _lire(chemin: Path) -> str:
        return chemin.read_text()

    @staticmethod
    def _copie_env_explicit(contenu: str) -> list[str]:
        """Retourne les lignes COPY qui nomment explicitement un fichier .env comme source."""
        violations = []
        for line in contenu.splitlines():
            stripped = line.strip()
            if not stripped.startswith("COPY"):
                continue
            if "--from=" in stripped:
                continue  # inter-stage : ne touche pas le contexte hôte
            tokens = stripped.split()
            args = [t for t in tokens[1:] if not t.startswith("--")]
            sources = args[:-1] if len(args) > 1 else []
            for src in sources:
                if src not in (".", "./") and (src == ".env" or src.startswith(".env.")):
                    violations.append(stripped)
        return violations

    def test_backend_dockerfile_ne_copie_pas_env_explicitement(self) -> None:
        """backend/Dockerfile ne doit pas nommer un .env comme source dans COPY."""
        contenu = self._lire(REPO_ROOT / "backend" / "Dockerfile")
        violations = self._copie_env_explicit(contenu)
        assert not violations, (
            "backend/Dockerfile copie explicitement un fichier .env dans l'image — "
            "les secrets locaux ne doivent jamais entrer dans l'image : "
            + str(violations)
        )

    def test_web_dockerfile_ne_copie_pas_env_explicitement(self) -> None:
        """web-dashboard/Dockerfile ne doit pas nommer un .env comme source dans COPY."""
        contenu = self._lire(REPO_ROOT / "web-dashboard" / "Dockerfile")
        violations = self._copie_env_explicit(contenu)
        assert not violations, (
            "web-dashboard/Dockerfile copie explicitement un fichier .env dans l'image — "
            "les secrets locaux ne doivent jamais entrer dans l'image : "
            + str(violations)
        )

    def test_backend_dockerfile_pas_de_secret_dans_env_directives(self) -> None:
        """backend/Dockerfile ne doit pas déclarer de secret via ENV."""
        contenu = _non_comments(self._lire(REPO_ROOT / "backend" / "Dockerfile"))
        assert not _SECRET_ENV_PATTERN.search(contenu), (
            "backend/Dockerfile contient une directive ENV pour une variable secrète "
            "(DATABASE_URL, JWT_SECRET, REDIS_URL, POSTGRES_PASSWORD…) — "
            "les secrets doivent être injectés à l'exécution, jamais intégrés à l'image."
        )

    def test_web_dockerfile_pas_de_secret_dans_env_directives(self) -> None:
        """web-dashboard/Dockerfile ne doit pas déclarer de secret via ENV."""
        contenu = _non_comments(self._lire(REPO_ROOT / "web-dashboard" / "Dockerfile"))
        assert not _SECRET_ENV_PATTERN.search(contenu), (
            "web-dashboard/Dockerfile contient une directive ENV pour une variable secrète — "
            "les secrets doivent être injectés à l'exécution, jamais intégrés à l'image."
        )

    def test_backend_dockerfile_declare_utilisateur_non_root(self) -> None:
        """backend/Dockerfile doit déclarer un utilisateur non-root (USER directive)."""
        contenu = self._lire(REPO_ROOT / "backend" / "Dockerfile")
        assert any(
            line.strip().startswith("USER ") for line in contenu.splitlines()
        ), (
            "backend/Dockerfile doit déclarer un utilisateur non-root — "
            "invariant sécurité #4/ADR-0010."
        )

    def test_web_dockerfile_declare_utilisateur_non_root(self) -> None:
        """web-dashboard/Dockerfile doit déclarer un utilisateur non-root (USER directive)."""
        contenu = self._lire(REPO_ROOT / "web-dashboard" / "Dockerfile")
        assert any(
            line.strip().startswith("USER ") for line in contenu.splitlines()
        ), (
            "web-dashboard/Dockerfile doit déclarer un utilisateur non-root — "
            "invariant sécurité #4/ADR-0010."
        )

    def test_backend_dockerfile_pas_de_secret_suspect(self) -> None:
        contenu = self._lire(REPO_ROOT / "backend" / "Dockerfile")
        assert not _PATTERNS_SECRET_SUSPECTS.search(contenu), (
            "backend/Dockerfile contient un motif ressemblant à un vrai token/secret."
        )

    def test_web_dockerfile_pas_de_secret_suspect(self) -> None:
        contenu = self._lire(REPO_ROOT / "web-dashboard" / "Dockerfile")
        assert not _PATTERNS_SECRET_SUSPECTS.search(contenu), (
            "web-dashboard/Dockerfile contient un motif ressemblant à un vrai token/secret."
        )


class TestDockerignoreSecurite:
    """Les .dockerignore doivent empêcher les fichiers .env d'entrer dans le contexte de build.

    Si .dockerignore omet cette exclusion, un `COPY . .` dans le Dockerfile
    copierait silencieusement les secrets locaux dans l'image.
    """

    @staticmethod
    def _actif(chemin: Path) -> list[str]:
        """Retourne les lignes actives (non commentées) du .dockerignore."""
        return [
            line.strip()
            for line in chemin.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def test_backend_dockerignore_exclut_dotenv(self) -> None:
        lines = self._actif(REPO_ROOT / "backend" / ".dockerignore")
        assert any(line in (".env", ".env.*", ".env*") for line in lines), (
            "backend/.dockerignore doit exclure les fichiers .env pour empêcher "
            "les secrets locaux d'entrer dans l'image via COPY."
        )

    def test_backend_dockerignore_exclut_dotenv_variantes(self) -> None:
        lines = self._actif(REPO_ROOT / "backend" / ".dockerignore")
        assert any(line in (".env.*", ".env*") for line in lines), (
            "backend/.dockerignore doit exclure les variantes .env.* "
            "(.env.local, .env.production…)."
        )

    def test_web_dockerignore_exclut_dotenv(self) -> None:
        lines = self._actif(REPO_ROOT / "web-dashboard" / ".dockerignore")
        assert any(line in (".env", ".env.*", ".env*") for line in lines), (
            "web-dashboard/.dockerignore doit exclure les fichiers .env — "
            "le Dockerfile web utilise COPY . . dans l'étape builder."
        )

    def test_web_dockerignore_exclut_dotenv_variantes(self) -> None:
        lines = self._actif(REPO_ROOT / "web-dashboard" / ".dockerignore")
        assert any(line in (".env.*", ".env*") for line in lines), (
            "web-dashboard/.dockerignore doit exclure les variantes .env.* "
            "(.env.local, .env.production…)."
        )
