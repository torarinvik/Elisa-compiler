#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPILER="$ROOT/scripts/elisac_stage1.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-incremental-shadow.XXXXXX")"
source "$ROOT/test/parity/control_artifacts.sh"
elisa_control_artifacts "$WORK"

cat >"$WORK/ordinary_ok.elisa" <<'ELISA'
def main() -> i64:
    return 0
ELISA

cat >"$WORK/ordinary_error.elisa" <<'ELISA'
def main() -> i64:
    return missing
ELISA

cat >"$WORK/include_leaf.elisa" <<'ELISA'
def included_value() -> i64:
    return 7
ELISA

cat >"$WORK/include_root.elisa" <<'ELISA'
include "include_leaf.elisa"

def main() -> i64:
    return included_value()
ELISA

cat >"$WORK/generated_ok.elisa" <<'ELISA'
enum Color:
    Red

static generate:
    for variant in variants(Color):
        emit def generated_${variant.name}() -> i64:
            return 42

def main() -> i64:
    return generated_Red()
ELISA

cat >"$WORK/generated_error.elisa" <<'ELISA'
enum Color:
    Red

static generate:
    for variant in variants(Color):
        emit def generated_${variant.name}() -> i64:
            return missing_${variant.name}

def main() -> i64:
    return 0
ELISA

run_check() {
    local mode="$1" source="$2" stem="$3" status
    if [[ "$mode" == cold ]]; then
        if env -u ELISA_INCREMENTAL_SHADOW -u ELISA_INCREMENTAL_SHADOW_REPORT \
            ELISA_ALLOW_STALE_STAGE1=0 "$COMPILER" -emit check "$source" \
            >"$WORK/$stem.$mode.out" 2>"$WORK/$stem.$mode.err"; then
            status=0
        else
            status=$?
        fi
    else
        if env -u ELISA_INCREMENTAL_SHADOW_REPORT ELISA_INCREMENTAL_SHADOW=1 \
            ELISA_ALLOW_STALE_STAGE1=0 "$COMPILER" -emit check "$source" \
            >"$WORK/$stem.$mode.out" 2>"$WORK/$stem.$mode.err"; then
            status=0
        else
            status=$?
        fi
    fi
    printf '%s\n' "$status" >"$WORK/$stem.$mode.status"
}

compare_cold_and_shadow() {
    local source="$1" stem="$2"
    run_check cold "$source" "$stem"
    run_check shadow "$source" "$stem"
    diff -u "$WORK/$stem.cold.status" "$WORK/$stem.shadow.status"
    diff -u "$WORK/$stem.cold.out" "$WORK/$stem.shadow.out"
    diff -u "$WORK/$stem.cold.err" "$WORK/$stem.shadow.err"
}

compare_cold_and_shadow "$WORK/ordinary_ok.elisa" ordinary-ok
compare_cold_and_shadow "$WORK/ordinary_error.elisa" ordinary-error
compare_cold_and_shadow "$WORK/include_root.elisa" include-root
compare_cold_and_shadow "$WORK/generated_ok.elisa" generated-ok
compare_cold_and_shadow "$WORK/generated_error.elisa" generated-error

cat >"$WORK/generated_pymodule.elisa" <<'ELISA'
enum Color:
    Red

static generate:
    for variant in variants(Color):
        emit def generated_${variant.name}() -> i64:
            return 42

def ping() -> i64:
    return generated_Red()

export pymodule shadowmod:
    fn ping
ELISA

run_pymodule() {
    local mode="$1" source="$2" stem="$3" status
    if [[ "$mode" == cold ]]; then
        if env -u ELISA_INCREMENTAL_SHADOW -u ELISA_INCREMENTAL_SHADOW_REPORT \
            ELISA_ALLOW_STALE_STAGE1=0 "$COMPILER" -emit pymodule \
            -o "$WORK/$stem.$mode.json" "$source" \
            >"$WORK/$stem.$mode.out" 2>"$WORK/$stem.$mode.err"; then
            status=0
        else
            status=$?
        fi
    else
        if env -u ELISA_INCREMENTAL_SHADOW_REPORT ELISA_INCREMENTAL_SHADOW=1 \
            ELISA_ALLOW_STALE_STAGE1=0 "$COMPILER" -emit pymodule \
            -o "$WORK/$stem.$mode.json" "$source" \
            >"$WORK/$stem.$mode.out" 2>"$WORK/$stem.$mode.err"; then
            status=0
        else
            status=$?
        fi
    fi
    printf '%s\n' "$status" >"$WORK/$stem.$mode.status"
}

compare_pymodule_cold_and_shadow() {
    local source="$1" stem="$2"
    run_pymodule cold "$source" "$stem"
    run_pymodule shadow "$source" "$stem"
    diff -u "$WORK/$stem.cold.status" "$WORK/$stem.shadow.status"
    diff -u "$WORK/$stem.cold.out" "$WORK/$stem.shadow.out"
    diff -u "$WORK/$stem.cold.err" "$WORK/$stem.shadow.err"
    diff -u "$WORK/$stem.cold.json" "$WORK/$stem.shadow.json"
}

compare_pymodule_cold_and_shadow "$ROOT/test/repro/pymodule_export.elisa" pymodule-ordinary
compare_pymodule_cold_and_shadow "$WORK/generated_pymodule.elisa" pymodule-generated

for input in ordinary include generated; do
    source="$WORK/ordinary_ok.elisa"
    expected_functions=1
    reported_input=ordinary
    if [[ "$input" == include ]]; then
        source="$WORK/include_root.elisa"
        expected_functions=2
    fi
    if [[ "$input" == generated ]]; then
        source="$WORK/generated_ok.elisa"
        expected_functions=2
        reported_input=generated
    fi
    ELISA_INCREMENTAL_SHADOW=1 ELISA_INCREMENTAL_SHADOW_REPORT=1 \
        ELISA_ALLOW_STALE_STAGE1=0 "$COMPILER" -emit check "$source" \
        >"$WORK/$input.report.out" 2>"$WORK/$input.report.err"
    grep -Eq "incremental-shadow: cold_gate=passed collector=shadow-only input=$reported_input .* functions=$expected_functions " \
        "$WORK/$input.report.err" || {
        cat "$WORK/$input.report.err" >&2
        echo "incremental shadow did not report the expected $input AST/source pair" >&2
        exit 1
    }
done

ELISA_INCREMENTAL_SHADOW=1 ELISA_INCREMENTAL_SHADOW_REPORT=1 \
    ELISA_ALLOW_STALE_STAGE1=0 "$COMPILER" -emit pymodule \
    -o "$WORK/generated_pymodule.report.json" "$WORK/generated_pymodule.elisa" \
    >"$WORK/generated_pymodule.report.out" 2>"$WORK/generated_pymodule.report.err"
grep -Eq 'incremental-shadow: cold_gate=passed collector=shadow-only input=generated .* functions=2 ' \
    "$WORK/generated_pymodule.report.err" || {
    cat "$WORK/generated_pymodule.report.err" >&2
    echo "incremental shadow did not report the expanded pymodule AST/source pair" >&2
    exit 1
}

echo "incremental shadow gate control OK: cold outputs unchanged across ordinary, include, generated, and early pymodule gates"
