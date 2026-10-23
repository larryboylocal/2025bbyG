#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
cd "$ROOT"
export PYTHONPATH="$ROOT"
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON=$(command -v python3)
fi
if [ "${1:-}" = "--self-check" ]; then
  exec "$PYTHON" -m terminals.kraken.kraken_runtime --self-check
fi
exec "$PYTHON" -m terminals.kraken.kraken_runtime
