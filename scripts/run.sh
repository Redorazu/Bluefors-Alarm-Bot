#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -x "./alarm-bot" ]]; then
  exec ./alarm-bot run
elif [[ -x ".venv/bin/python" ]]; then
  exec .venv/bin/python -m alarm_bot.cli run
else
  exec python -m alarm_bot.cli run
fi
