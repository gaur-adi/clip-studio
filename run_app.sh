#!/bin/zsh
# Put the Ubuntu laptop's Ollama URL in ollama_host.txt (e.g. http://YOUR-LLM-HOST:11434) to use its GPU.
cd "$(dirname "$0")"
[ -z "$OLLAMA_HOST" ] && [ -f ollama_host.txt ] && export OLLAMA_HOST="$(tr -d ' \n' < ollama_host.txt)"
[ -z "$OLLAMA_MODEL" ] && [ -f ollama_model.txt ] && export OLLAMA_MODEL="$(tr -d ' \n' < ollama_model.txt)"
echo "LLM model: ${OLLAMA_MODEL:-gemma4:12b}"
echo "LLM host: ${OLLAMA_HOST:-none set (heuristic scoring only)}"
# the small music-choosing AI lives on this Mac (separate from the laptop that judges moments)
if command -v ollama >/dev/null && ! curl -s -m 1 localhost:11434/api/version >/dev/null; then (nohup ollama serve > work/ollama_mac.log 2>&1 &); sleep 2; fi
# speech recognition (Qwen3-ASR, runs on this Mac GPU): loads once in ~1-2 min, Whisper is the automatic fallback until it is ready
if [ -x .venv-asr/bin/python ] && ! curl -s -m 1 localhost:8770/health >/dev/null; then (nohup .venv-asr/bin/python scripts/asr_server.py > work/asr_server.log 2>&1 &); echo "speech recognition: starting (ready in ~1-2 min, see work/asr_server.log)"; fi
(sleep 1; open "http://127.0.0.1:${PORT:-8765}") &
mkdir -p work; .venv/bin/python -u app/server.py 2>&1 | tee -a work/server.log     # also logged to work/server.log so it can be monitored
