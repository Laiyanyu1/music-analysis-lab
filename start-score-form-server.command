#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON="$PROJECT_DIR/.venv-score-form/bin/python"

if [ ! -x "$PYTHON" ]; then
  printf '%s\n' "首次运行：正在安装开源曲式分析依赖……"
  sh "$PROJECT_DIR/backend/setup_open_source_deps.sh"
fi

cd "$PROJECT_DIR/backend"
exec "$PYTHON" -m uvicorn app:app --host 127.0.0.1 --port 8790
