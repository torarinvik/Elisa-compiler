#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

REAL_PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
if [[ -z "$REAL_PYTHON_BIN" || ! -x "$REAL_PYTHON_BIN" ]]; then
    echo "pymodule PYTHON_BIN smoke SKIP (python3 unavailable)"
    exit 0
fi

LOG="$WORK/python-wrapper.log"
WRAPPER="$WORK/python-wrapper"
{
    printf '%s\n' '#!/usr/bin/env bash'
    printf 'printf "flatten-wrapper-used\\n" >> %q\n' "$LOG"
    printf 'exec %q "$@"\n' "$REAL_PYTHON_BIN"
} > "$WRAPPER"
chmod +x "$WRAPPER"

# The fixture CONTAINS an include on purpose. This check used to prove that PYTHON_BIN
# selection reached the wrapper's python FLATTEN step; that step is gone (§4.1: the driver
# expands includes itself), so the wrapper spawns no interpreter for a manifest build any
# more. What still has to hold: an including source produces its manifest through the
# driver's expansion, and both spellings of the python selection (PYTHON_BIN and --python)
# are accepted without reaching for a real interpreter. The log may therefore be EMPTY.
INCLUDING_SOURCE="$WORK/fastmath.elisa"
{
    printf 'include "%s"\n' "$ROOT/test/repro/pymodule_export.elisa"
} > "$INCLUDING_SOURCE"

PYTHON_BIN="$WRAPPER" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/manifest.json" \
    "$INCLUDING_SOURCE" >/dev/null

test "$(cat "$LOG" 2>/dev/null | wc -l | tr -d ' ')" -le 1
grep -Fq '"module": "fastmath"' "$WORK/manifest.json"

: > "$LOG"
PYTHON_BIN="$REAL_PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" \
    --python "$WRAPPER" -emit pymodule \
    -o "$WORK/manifest-cli.json" \
    "$INCLUDING_SOURCE" >/dev/null
test "$(cat "$LOG" 2>/dev/null | wc -l | tr -d ' ')" -le 1
grep -Fq '"module": "fastmath"' "$WORK/manifest-cli.json"

echo "pymodule PYTHON_BIN smoke OK"
