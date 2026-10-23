# Image du backend : la même sert à l'API et au surveillant (seule la commande change, voir docker-compose.yml).
FROM python:3.14-slim

# uv copié depuis son image officielle, même version que sur le PC de développement.
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv

# Python de l'image (pas de téléchargement), fichiers .pyc préparés à l'avance (démarrage plus rapide).
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Dépendances d'abord, figées par uv.lock et sans les outils de test : cette couche n'est reconstruite
# que si pyproject.toml ou uv.lock changent, pas à chaque modification du code.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY migrations ./migrations
COPY data ./data
COPY app ./app

# Pas de root : si l'API était compromise, l'attaquant n'aurait pas les droits d'administrateur du conteneur.
# /app/demo : fichier de stationTest, partagé par l'API et le surveillant (volume, voir docker-compose.yml).
RUN useradd --create-home stationalerte && mkdir /app/demo && chown -R stationalerte /app/data /app/demo
USER stationalerte

EXPOSE 8000
CMD ["fastapi", "run", "app/main.py", "--port", "8000"]
