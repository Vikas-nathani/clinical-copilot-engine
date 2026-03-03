#!/usr/bin/env bash
# ── pull_model.sh ─────────────────────────────────────────────────
# One-time script to pull the BioMistral-7B model into the Ollama
# container. Run this after `docker compose up` has started.
#
# Usage:
#   chmod +x scripts/pull_model.sh
#   ./scripts/pull_model.sh
# ──────────────────────────────────────────────────────────────────

set -euo pipefail

MODEL="${OLLAMA_MODEL:-cniongolo/biomistral}"
OLLAMA_HOST="${OLLAMA_URL:-http://localhost:11434}"

echo "⏳ Pulling model '${MODEL}' from Ollama at ${OLLAMA_HOST}..."
echo "   This is a one-time download (~4.4 GB). Please be patient."
echo ""

# Wait for Ollama to be ready (up to 60 seconds)
for i in $(seq 1 12); do
  if curl -sf "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; then
    echo "✅ Ollama is ready."
    break
  fi
  if [ "$i" -eq 12 ]; then
    echo "❌ Ollama not reachable at ${OLLAMA_HOST} after 60s. Is it running?"
    exit 1
  fi
  echo "   Waiting for Ollama to start... (${i}/12)"
  sleep 5
done

# Pull the model
curl -# -X POST "${OLLAMA_HOST}/api/pull" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"${MODEL}\"}"

echo ""
echo "✅ Model '${MODEL}' pulled successfully."
echo "   The backend will detect it on next health check or restart."
