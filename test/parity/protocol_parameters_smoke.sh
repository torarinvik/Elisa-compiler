#!/usr/bin/env bash
# Protocol value parameters specialize by receiver; execute both compiler outputs.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
for fixture in protocol_value_parameters protocol_parameter_in_module protocol_reference_parameter; do
    for stage in 0 1; do
        compiler="$STAGE0"
        [[ "$stage" == 0 ]] || compiler="$STAGE1"
        "$compiler" -emit obj -o "$WORK/values$stage.o" "$ROOT/test/differential/cases/$fixture.elisa"
        clang -Wl,-dead_strip -o "$WORK/values$stage" "$WORK/values$stage.o" "$WORK/hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
        "$WORK/values$stage" > "$WORK/output$stage"
        printf '%s: stage%s runtime PASS\n' "$fixture" "$stage"
    done
    cmp "$WORK/output0" "$WORK/output1"
done
cat > "$WORK/invalid.elisa" <<'ELISA'
protocol Painter:
    def paint(self: Self) -> i32
struct Missing:
    value: i32
def draw(painter: Painter) -> i32:
    return painter.paint()
def main() -> i32:
    return draw(painter: Missing{value: 1})
ELISA
cat > "$WORK/return.elisa" <<'ELISA'
protocol Painter:
    def paint(self: Self) -> i32
def valid(painter: Painter) -> i32:
    return painter.paint()
def invalid() -> Painter:
    return 0
ELISA
stage=0
for compiler in "$STAGE0" "$STAGE1"; do
    if "$compiler" -emit obj -o "$WORK/invalid.o" "$WORK/invalid.elisa" > "$WORK/invalid.log" 2>&1; then
        echo 'FAIL: missing protocol implementation accepted' >&2; exit 1
    fi
    grep -q 'does not satisfy required interface fact' "$WORK/invalid.log"
    if "$compiler" -emit obj -o "$WORK/return.o" "$WORK/return.elisa" > "$WORK/return.log" 2>&1; then
        echo 'FAIL: protocol return value accepted' >&2; exit 1
    fi
    grep -q 'is a constraint, not a concrete value type' "$WORK/return.log"
    cp "$WORK/invalid.log" "$WORK/invalid.$stage.log"
    cp "$WORK/return.log" "$WORK/return.$stage.log"
    stage=$((stage + 1))
done
cmp "$WORK/invalid.0.log" "$WORK/invalid.1.log"
cmp "$WORK/return.0.log" "$WORK/return.1.log"
echo 'protocol parameter diagnostics: PASS'
