# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FASTEMBED_CACHE_PATH=/opt/models

WORKDIR /app

# Install dependencies (read from pyproject.toml) first, so code changes don't invalidate
# this layer.
COPY pyproject.toml README.md LICENSE ./
RUN pip install $(python -c "import tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; o = p['optional-dependencies']; print(' '.join(p['dependencies'] + o['local'] + o['celery']))")

# Bake the default embedding model into the image (no download at startup).
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBEDDING_MODEL}')"

COPY app ./app
COPY sample_docs ./sample_docs
COPY alembic.ini ./
RUN pip install --no-deps -e . \
    && useradd --system --uid 10001 --home /app app \
    && chown -R app /opt/models

USER app
EXPOSE 8000
# PaaS platforms (Render, Fly.io, Railway) inject $PORT. Migrations run on startup.
# Behind a platform proxy, set FORWARDED_ALLOW_IPS so client IPs (rate limits, audit log) are real.
ENV PORT=8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/api/v1/health\")"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\" --proxy-headers"]
