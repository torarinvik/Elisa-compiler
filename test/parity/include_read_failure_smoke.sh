#!/usr/bin/env bash
# Native include expansion must fail closed: a missing root or included file is a compiler
# error with a diagnostic, never an empty request or a fallback to the unexpanded source.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
[[ -x "$BIN" ]] || { echo "include-read-failure SKIP: no stage1 binary"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

expect_failure_with_diagnostic() {
    local label="$1" source="$2" output="$3" rc
    local stdout="$WORK/$label.stdout" stderr="$WORK/$label.stderr"
    set +e
    "$BIN" -o "$output" "$source" >"$stdout" 2>"$stderr"
    rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
        echo "include-read-failure FAILED: $label was accepted" >&2
        return 1
    fi
    if ! grep -q 'could not read source or included file' "$stderr"; then
        echo "include-read-failure FAILED: $label had no read diagnostic" >&2
        sed -n '1,20p' "$stderr" >&2
        return 1
    fi
    if [[ -e "$output" ]]; then
        echo "include-read-failure FAILED: $label wrote an output object" >&2
        return 1
    fi
}

expect_failure_with_diagnostic root "$WORK/missing.elisa" "$WORK/root.o" || exit 1

cat >"$WORK/with-missing-include.elisa" <<EOF
include "$WORK/missing-include.elisa"

def main() -> int:
    return 0
EOF
expect_failure_with_diagnostic include "$WORK/with-missing-include.elisa" "$WORK/include.o" || exit 1

echo "include-read-failure OK: missing roots and includes are diagnosed and produce no object"
