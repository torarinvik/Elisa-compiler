#!/usr/bin/env bash
# Start the bootstrap compiler's retained-analysis server for fast seed iterations.
#
#   scripts/elisac_retained_server.sh            # foreground; Ctrl-C stops it
#
# While it runs, scripts/elisac_stage1_seed.sh forwards its bootstrap compile to it
# (via ELISACORE_RETAINED_SERVER). An edit that only changes function bodies is
# re-checked in seconds; when the result has no errors, or the edit touches a
# signature or declaration, the server runs a full analysis exactly as a local
# compile would. The server only answers the exact compiler binary that started it,
# so reinstalling the bootstrap compiler makes seeds compile locally until it is
# restarted.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOCKET="${ELISACORE_RETAINED_SERVER:-$HOME/.elisac/retained.sock}"
if [[ -n "${ELISACORE_BIN:-}" ]]; then
  BIN="$ELISACORE_BIN"
else
  main_checkout="$(cd "$ROOT" && git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  main_checkout="${main_checkout%/.git}"
  BIN="${main_checkout:-$ROOT}/../../Go projects/Elisa-core/compiler/bin/elisac"
fi
mkdir -p "$(dirname "$SOCKET")"
echo "retained server: $BIN on $SOCKET" >&2
exec "$BIN" -emit retained-serve -addr "$SOCKET"
