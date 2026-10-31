#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON:-python3}"
if [ ! -d backend/.venv ]; then
  "$PYTHON_BIN" -m venv backend/.venv
fi
backend/.venv/bin/python -m pip install --quiet --upgrade pip
backend/.venv/bin/python -m pip install --quiet -r backend/requirements.txt

if [ ! -f frontend/dist/index.html ]; then
  (cd frontend && npm ci && npm run build)
fi

if [ -z "${JWT_SECRET:-}" ]; then
  echo "WARN: JWT_SECRET 未设置，将使用内置开发密钥；生产环境请先 export JWT_SECRET。"
fi

exec backend/.venv/bin/python -m uvicorn app.main:app \
  --app-dir backend --host 0.0.0.0 --port "${LISA_PORT:-8000}" --workers 1 --proxy-headers
