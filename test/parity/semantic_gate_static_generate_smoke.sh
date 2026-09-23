#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
COMPILER="$ROOT/scripts/elisac_stage1.sh"

cat >"$WORK/generated_bad.elisa" <<'ELISA'
enum Color:
    Red

static generate:
    for variant in variants(Color):
        emit def generated_${variant.name}() -> i64:
            return missing_${variant.name}

def main() -> i64:
    return 0
ELISA

for mode in c-archive test interpret; do
    log="$WORK/$mode.log"
    if [[ "$mode" == c-archive ]]; then
        if ELISA_ALLOW_STALE_STAGE1=0 bash "$COMPILER" -emit "$mode" -o "$WORK/generated.a" \
            "$WORK/generated_bad.elisa" >"$log" 2>&1; then
            echo "-emit $mode accepted an invalid generated function" >&2
            exit 1
        fi
    else
        if ELISA_ALLOW_STALE_STAGE1=0 bash "$COMPILER" -emit "$mode" \
            "$WORK/generated_bad.elisa" >"$log" 2>&1; then
            echo "-emit $mode accepted an invalid generated function" >&2
            exit 1
        fi
    fi
    grep -Fq 'undefined identifier "missing_Red"' "$log" || {
        cat "$log" >&2
        echo "-emit $mode did not report the generated semantic error" >&2
        exit 1
    }
done
test ! -e "$WORK/generated.a"

cat >"$WORK/generated_good.elisa" <<'ELISA'
enum Color:
    Red

static generate:
    for variant in variants(Color):
        emit def generated_${variant.name}() -> i64:
            return 42

def main() -> i64:
    return generated_Red()
ELISA

ELISA_ALLOW_STALE_STAGE1=0 bash "$COMPILER" -emit interpret "$WORK/generated_good.elisa" \
    >"$WORK/generated_good.log" 2>&1
grep -Fq '[ result   ] 42' "$WORK/generated_good.log" || {
    cat "$WORK/generated_good.log" >&2
    echo "-emit interpret did not run the generated function" >&2
    exit 1
}

echo "static-generation semantic-gate smoke OK"
