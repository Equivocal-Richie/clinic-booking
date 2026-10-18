# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# Application code and migrations.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x entrypoint.sh

# Render (and most PaaS) inject $PORT at runtime; default for local use.
ENV PORT=8000
EXPOSE 8000

# Runs DB migrations, then starts gunicorn with multiple uvicorn workers.
# Multiple workers is deliberate: it is exactly why slot exclusivity must be
# enforced in the database, not in process memory.
ENTRYPOINT ["./entrypoint.sh"]
