#!/usr/bin/env bash
# Guards the self-host rewrite in parser_decl_handler.elisa (parse_handler_captures): a
# container filled by a callee that allocates in its arguments' arenas must not be a
# frame-local when its elements are stored into parser-owned storage. stage0 is the
# oracle (stage1 does not yet check this shape): the .neg must be rejected with the
# region-escape sentence at the store, the .pos (containers in the parser's region) accepted.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

NEG="$REPO_ROOT/test/repro/handler_capture_local_escape.neg.elisa"
POS="$REPO_ROOT/test/repro/handler_capture_local_escape.pos.elisa"
fail() { echo "handler_capture_region_smoke: FAIL: $*" >&2; exit 1; }

neg_out="$("$ELISACORE_BIN" -emit semantic "$NEG" 2>&1 || true)"
grep -Eq "handler_capture_local_escape\.neg\.elisa:[0-9]+:[0-9-]+: value in region .* is stored into longer-lived region \"__rg_parser\"" <<< "$neg_out" \
    || fail "stage0 accepted the local-container escape"
pos_out="$("$ELISACORE_BIN" -emit semantic "$POS" 2>&1 || true)"
if grep -E "\.pos\.elisa:[0-9]+:[0-9-]+: " <<< "$pos_out" | grep -vq "warning:"; then
    fail "stage0 rejected the parser-region shape: $(grep -E '\.pos\.elisa:' <<< "$pos_out" | head -3)"
fi
echo "handler_capture_region_smoke: PASS"
