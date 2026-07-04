#!/usr/bin/env bash
# =============================================================================
# Backlog Synthesizer — container entrypoint with graceful shutdown
#
# Wraps `streamlit run` so that a SIGTERM from the container orchestrator
# (Azure Container Apps, Kubernetes, docker stop) triggers a tidy wind-down:
#
#   1. Writes a flag file ($SHUTDOWN_FLAG_PATH) that the Streamlit polling
#      loop checks every 300 ms.  If a synthesis is running, it finishes the
#      current LLM stage and then cancels instead of being killed mid-call.
#   2. Waits up to $SHUTDOWN_GRACE_SECONDS for Streamlit to exit on its own.
#   3. Sends SIGTERM again to the Streamlit PID if it's still alive after the
#      grace window, then waits for it to exit (the OS will SIGKILL it after
#      its own grace period if it still doesn't stop).
#
# Azure Container Apps default terminationGracePeriodSeconds is 30 s.
# Set it to 90 s in azure_setup.sh so an in-flight LLM stage can finish.
# =============================================================================

set -euo pipefail

SHUTDOWN_FLAG_PATH="${SHUTDOWN_FLAG_PATH:-/tmp/.shutdown_requested}"
SHUTDOWN_GRACE_SECONDS="${SHUTDOWN_GRACE_SECONDS:-75}"
PORT="${PORT:-8502}"

_handle_term() {
    echo "[entrypoint] SIGTERM received — requesting graceful shutdown (grace=${SHUTDOWN_GRACE_SECONDS}s)…" >&2
    touch "$SHUTDOWN_FLAG_PATH"

    local waited=0
    while kill -0 "$STREAMLIT_PID" 2>/dev/null && [ "$waited" -lt "$SHUTDOWN_GRACE_SECONDS" ]; do
        sleep 2
        waited=$((waited + 2))
    done

    if kill -0 "$STREAMLIT_PID" 2>/dev/null; then
        echo "[entrypoint] Grace period elapsed — sending SIGTERM to Streamlit…" >&2
        kill -SIGTERM "$STREAMLIT_PID" 2>/dev/null || true
        wait "$STREAMLIT_PID" 2>/dev/null || true
    fi

    rm -f "$SHUTDOWN_FLAG_PATH"
    echo "[entrypoint] Shutdown complete." >&2
    exit 0
}

trap _handle_term SIGTERM SIGINT

# Remove any stale flag from a previous run (e.g. container restart).
rm -f "$SHUTDOWN_FLAG_PATH"

# Pre-warm the embedding model before Streamlit starts (idempotent — the
# model is baked into the image layer by Dockerfile's RUN python warmup.py).
# This no-op ensures the HF cache is intact even if the image was rebuilt.
if [ -f "src/warmup.py" ]; then
    python src/warmup.py 2>&1 | sed 's/^/[warmup] /' || true
fi

echo "[entrypoint] Starting Streamlit on port ${PORT}…" >&2
exec streamlit run app.py \
    --server.port="$PORT" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false &

STREAMLIT_PID=$!
wait "$STREAMLIT_PID"
