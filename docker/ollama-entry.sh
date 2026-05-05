#!/bin/sh
# CPU-friendly Ollama: start API, wait until it answers, pull a small default model, then keep serving.
set -e

MODEL="${OLLAMA_START_MODEL:-qwen2.5:7b}"

echo "Starting Ollama server (CPU)..."
ollama serve &
SERVE_PID=$!

echo "Waiting for Ollama API to accept commands..."
i=0
while [ "$i" -lt 120 ]; do
  if ollama list >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 1
done

if ! ollama list >/dev/null 2>&1; then
  echo "Ollama API did not become ready in time." >&2
  kill "${SERVE_PID}" 2>/dev/null || true
  exit 1
fi

echo "Pulling default model (first run may take a while): ${MODEL}"
ollama pull "${MODEL}"

echo "Ollama is ready on :11434 (model: ${MODEL})."
wait "${SERVE_PID}"
