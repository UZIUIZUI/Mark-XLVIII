#!/usr/bin/env bash
cd "$(dirname "$0")"
pip install -q -r requirements.txt
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
