#!/usr/bin/env bash
# Parse-error MESSAGE parity (§5.2): stage0's parser test helpers emit every source they
# reject (ELISA_PARSER_PARITY_OUT, the same oracle parser_acceptance_diff.sh replays for
# accept/reject). For each rejected source this runs BOTH CLIs and compares the error
# lines as `LINE|message` (columns are §5.1's business and are ignored here). A case
# AGREES when the two sets are identical. RATCHETED: the agreeing count must not drop
# below test/fixtures/parse_error_messages.baseline; raise the baseline as cases close.
# Set ELISA_PARSE_ERROR_VERBOSE=1 to print every disagreeing case with both readings.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
STAGE0="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
BASELINE="$REPO_ROOT/test/fixtures/parse_error_messages.baseline"
[[ -x "$STAGE0" ]] || { echo "parse_error_message_diff SKIP: no stage0 at $STAGE0"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "parse_error_message_diff FAILED: no stage1 at $STAGE1" >&2; exit 1; }
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT INT TERM HUP
(cd "$ELISA_CORE/compiler" && ELISA_PARSER_PARITY_OUT="$WORK/oracle.tsv" go test ./src/parser -count=1 >/dev/null)
# `path:LINE:COL-COL: msg` or `path:LINE: msg` -> `LINE|msg`; warnings and notes are not errors.
readings() { { grep -E '^[^:]*:[0-9]+(:[0-9-]+)?: ' "$1" || true; } | { grep -vE ': (warning|note): ' || true; } | sed -E 's#^[^:]*:([0-9]+)(:[0-9-]+)?: #\1|#' | sort -u; }
agree=0; total=0
while IFS=$'\t' read -r name expected_errors notices encoded; do
    [[ "$expected_errors" -gt 0 ]] || continue
    total=$((total + 1)); src="$WORK/case_$total.elisa"   # oracle names carry `/` (subtests)
    printf '%s' "$encoded" | openssl base64 -d -A > "$src"
    "$STAGE0" -emit obj -o "$WORK/s0.o" "$src" > "$WORK/s0.err" 2>&1 || true
    "$STAGE1" -emit obj -o "$WORK/s1.o" "$src" > "$WORK/s1.err" 2>&1 || true
    if [[ "$(readings "$WORK/s0.err")" == "$(readings "$WORK/s1.err")" ]]; then agree=$((agree + 1))
    elif [[ "${ELISA_PARSE_ERROR_VERBOSE:-0}" != 0 ]]; then
        echo "--- $name"; echo "stage0:"; readings "$WORK/s0.err" | sed 's/^/  /'; echo "stage1:"; readings "$WORK/s1.err" | sed 's/^/  /'
    fi
done < "$WORK/oracle.tsv"
baseline="$(tr -d '[:space:]' < "$BASELINE" 2>/dev/null || echo 0)"
echo "parse_error_message_diff: $total rejected sources, $agree agree line+message (ratchet >= $baseline)"
if [[ "$agree" -lt "$baseline" ]]; then echo "parse_error_message_diff FAILED: $agree agreeing is below the ratchet $baseline" >&2; exit 1; fi
[[ "$agree" -gt "$baseline" ]] && echo "  ratchet can be raised to $agree (edit $BASELINE)"
exit 0
