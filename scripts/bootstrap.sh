#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
PYTHON_BIN="${DRONEPORT_PYTHON:-python3}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Для этого lock-файла используйте Python 3.12"'
if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -c 'import sys; from pathlib import Path; assert Path(sys.prefix).resolve() == Path(".venv").resolve(), "Ожидалось локальное окружение .venv"'
.venv/bin/python -m pip install --no-cache-dir --only-binary=:all: -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python scripts/check_environment.py
.venv/bin/python scripts/inventory.py
