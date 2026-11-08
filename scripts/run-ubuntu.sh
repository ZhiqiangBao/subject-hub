#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export SUBJECT_HUB_ROOT="$ROOT"
export PYTHONPATH="$ROOT/backend"
cd "$ROOT"
exec "$ROOT/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8090
