#!/usr/bin/env bash
# T-040: те же действия симулятора из консоли, с явным отказом при HTTP-ошибке.
set -euo pipefail

base_url="${CX_BASE_URL:-http://127.0.0.1:8000}"
base_url="${base_url%/}"
action="${1:-status}"
if (( $# > 1 )); then
  echo 'Usage: scripts/run.sh [stop|resume|status|reset-baseline]' >&2
  exit 2
fi
case "$action" in
  status)
    exec curl --fail-with-body --silent --show-error --connect-timeout 5 --max-time 120 "$base_url/api/sim/state"
    ;;
  stop|resume)
    exec curl --fail-with-body --silent --show-error --connect-timeout 5 --max-time 120 \
      --request POST --header 'Content-Type: application/json' --data "{\"action\":\"$action\"}" "$base_url/api/sim/control"
    ;;
  reset-baseline)
    exec curl --fail-with-body --silent --show-error --connect-timeout 5 --max-time 120 \
      --request POST "$base_url/api/sim/baseline/restore"
    ;;
  -h|--help)
    echo 'Usage: scripts/run.sh [stop|resume|status|reset-baseline]'
    ;;
  *)
    echo 'Usage: scripts/run.sh [stop|resume|status|reset-baseline]' >&2
    exit 2
    ;;
esac
