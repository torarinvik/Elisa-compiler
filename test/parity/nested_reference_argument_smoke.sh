#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE="$REPO_ROOT/test/repro/nested_reference_argument.elisa"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"

stage0="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
if [[ -z "${ELISACORE_BIN:-}" ]]; then
    mkdir -p "$(dirname "$stage0")"
    ( cd "$ELISA_CORE/compiler" && go build -o "$stage0" ./src )
fi
stage1="${ELISA_STAGE1_BIN:-$(command -v elisac-stage1 || true)}"
[[ -x "$stage1" ]] || { echo "nested reference smoke: missing elisac-stage1" >&2; exit 2; }
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT INT TERM HUP

check_rejected() {
    local compiler="$1" label="$2" err status
    err="$work/$label.err"
    set +e
    "$compiler" -emit obj -o "$work/$label.o" "$FIXTURE" >/dev/null 2>"$err"
    status=$?
    set -e
    if [[ "$status" -eq 0 ]] || ! grep -q 'reference' "$err"; then
        echo "nested reference smoke: $label accepted or misreported the invalid T&& argument" >&2
        sed 's/^/  /' "$err" >&2
        exit 1
    fi
    echo "nested reference smoke: $label rejects T&&"
}

check_rejected "$stage0" stage0
check_rejected "$stage1" stage1
echo "nested reference smoke OK"
