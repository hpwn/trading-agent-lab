#!/usr/bin/env bash
set -euo pipefail

missing=()
for var in ALPACA_API_KEY_ID ALPACA_API_SECRET_KEY; do
  if [[ -z "${!var:-}" ]]; then
    missing+=("$var")
  fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  printf 'Missing required environment variables: %s\n' "${missing[*]}" >&2
  exit 1
fi

symbol="SPY"
if [[ ${1:-} == "--symbol" && -n ${2:-} ]]; then
  symbol=$2
fi

tal doctor alpaca --symbol "$symbol"
tal live --config config/live/alpaca_paper.yaml
tal eval --since 7d --format table
sqlite3 lab.db 'select count(*) from orders;'
printf '%s\n' "$(pwd)/artifacts/live/trades.csv"
