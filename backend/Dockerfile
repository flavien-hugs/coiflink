# Image de production du backend CoifLink (FastAPI / uvicorn) — issue #4.
#
# Principes (cf. spec §Security & docs/adr/0010) :
# - config lue depuis l'environnement à l'exécution : AUCUN secret ni .env dans l'image ;
# - utilisateur NON-root ;
# - image de base slim, épinglée sur la version de référence Python 3.12 (ADR-0007).
# Le push vers un registre est différé (#5) : cette image est construite en CI (build-seul).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production

WORKDIR /app

# Métadonnées de build + code source (le .dockerignore exclut .venv, tests, .env…).
# psycopg[binary] embarque le driver : aucune dépendance système à compiler.
COPY pyproject.toml README.md ./
COPY coiflink_api ./coiflink_api
COPY migrations ./migrations
COPY alembic.ini ./

RUN pip install --no-cache-dir .

# Utilisateur non-root dédié.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# La configuration réelle (DATABASE_URL, JWT_SECRET…) est injectée par variables
# d'environnement au démarrage du conteneur (#5), jamais intégrée à l'image.
CMD ["uvicorn", "coiflink_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
