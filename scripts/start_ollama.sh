#!/usr/bin/env bash
set -euo pipefail

if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama is not installed or not on PATH" >&2
  exit 1
fi

if ! curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "Starting Ollama on port 11434..."
  ollama serve >/tmp/aria-ollama.log 2>&1 &
  sleep 2
fi

MODEL="${OLLAMA_MODEL:-qwen3:8b}"
if ! ollama list | awk '{print $1}' | grep -qx "$MODEL"; then
  echo "Pulling $MODEL..."
  ollama pull "$MODEL"
fi

echo "Ollama ready at http://localhost:11434 with model $MODEL"
