#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -x ".venv/bin/pip" ]]; then
  .venv/bin/pip install -e ".[dev]"
else
  pip install -e ".[dev]"
fi

pyinstaller --noconfirm --onedir --name alarm-bot main.py

dist="dist/alarm-bot"
cp -f config.yaml "$dist/config.yaml" 2>/dev/null || true
cp -f .env "$dist/.env" 2>/dev/null || true
cp -f scripts/setup.sh "$dist/setup.sh"
cp -f scripts/run.sh "$dist/run.sh"
chmod +x "$dist/alarm-bot" "$dist/setup.sh" "$dist/run.sh"
cp -f README.md "$dist/README.txt" 2>/dev/null || true

echo "Build complete: $dist"
