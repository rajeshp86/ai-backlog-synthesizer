# syntax=docker/dockerfile:1.6
#
# Backlog Synthesizer — multi-stage container image.
#
# Stage 1 (builder): installs build tools + compiles all wheels.
# Stage 2 (runtime): copies only the installed packages — no compiler toolchain.
# This halves the attack surface and reduces image size by ~200 MB.
#
# Run UI:  docker run -d -p 8502:8502 --env-file .env backlog-synthesizer:latest
# Health:  curl -f http://localhost:8502/_stcore/health
#
# CLI (override entrypoint):
#   docker run --rm --env-file .env -v "$PWD/outputs:/app/outputs" \
#     backlog-synthesizer:latest \
#     python src/main.py \
#       --transcript samples/meeting_notes.txt \
#       --constraints samples/architecture_constraints.md \
#       --backlog samples/jira_backlog.json

# ── Stage 1: builder ──────────────────────────────────────────────────────────
# Python 3.13 matches local development and the pip-compiled requirements-lock.txt.
# To pin to a specific digest (recommended for production):
#   docker pull python:3.13-slim-bookworm
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.13-slim-bookworm
FROM python:3.13-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential is needed by some transitive deps that compile from source.
# It lives only in this builder stage — the final image never sees it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt requirements-lock.txt ./

RUN pip install --upgrade pip \
 && pip install --prefix=/install -r requirements-lock.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    # Tell Python where the builder-stage packages landed.
    PYTHONPATH=/usr/local/lib/python3.13/site-packages

# curl: required by HEALTHCHECK.
# libgomp1: required by sentence-transformers / numpy on slim images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy the compiled packages from the builder stage (no compiler in final image).
COPY --from=builder /install /usr/local

WORKDIR /app

# Application code. Mirror these paths in .dockerignore for build-context
# size, but this explicit COPY is the actual guarantee.
COPY app.py ./
COPY entrypoint.sh ./
COPY .streamlit/ ./.streamlit/
COPY src/ ./src/
COPY prompts/ ./prompts/
COPY samples/ ./samples/
COPY evaluation/ ./evaluation/
COPY config/ ./config/

# Bake the sentence-transformers embedding model into the image layer so the
# first synthesis has zero cold-start delay in the "detecting duplicates" stage.
RUN python src/warmup.py

# Pre-create runtime dirs so they exist with non-root ownership.
# In production these are replaced by Azure File Share volume mounts.
RUN mkdir -p outputs logs

# Non-root user — Streamlit doesn't need root.
RUN useradd --create-home --uid 1000 appuser \
 && chown -R appuser:appuser /app \
 && chmod +x /app/entrypoint.sh
USER appuser

EXPOSE 8502

# Tell the container runtime which signal to send on `docker stop` / scale-in.
STOPSIGNAL SIGTERM

# Streamlit's /_stcore/health endpoint is the cleanest liveness probe.
# start-period covers warmup + Streamlit boot on cold start.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl --fail --silent http://localhost:8502/_stcore/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
