#!/usr/bin/env bash
# Exploratory safety probe. Each compiler/build/test is bounded independently.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
source "$ROOT/scripts/platform.sh"
TIMEOUT=$(command -v gtimeout || command -v timeout)
run() { "$TIMEOUT" -k 1s 29s "$@"; }
major=$("$LLVM_CONFIG" --version | cut -d. -f1)
[[ "$major" == 23 && "$ELISA_HOST_OS" == Darwin ]] || { echo 'table unroll probes require qualified Darwin and LLVM 23'; exit 0; }
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
run bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
run bash "$ROOT/scripts/build_runtime_object.sh"
T=$(mktemp -d "${TMPDIR:-/tmp}/stage1-table-unroll.XXXXXX")
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/test/parity"
cp "$ROOT/test/parity/stage1_table_unroll_fixture.ll" "$ROOT/test/parity/stage1_table_unroll_noop_fixture.ll" "$ROOT/test/parity/stage1_table_unroll_attempts_fixture.ll" "$ROOT/test/parity/stage1_table_unroll_graph_budget_fixture.ll" "$T/test/parity/"
cd "$T"
run "$STAGE1" -O0 -emit obj -o "$T/probe.o" "$ROOT/test/parity/stage1_table_unroll_probe.elisa"
run "${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}" "$T/probe.o" "${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}" -L"$ELISA_LLVM_LIBDIR" $ELISA_LLVM_LIBS $ELISA_LINK_EXE_FLAGS -Wl,-rpath,"$ELISA_LLVM_LIBDIR" -o "$T/probe"
run "$T/probe"
run "$ELISA_LLVM_BIN_DIR/llvm-dis" "$T/test/parity/stage1_table_unroll_output.bc" -o "$T/output.ll"
run "$ELISA_LLVM_BIN_DIR/llvm-as" "$T/test/parity/stage1_table_unroll_fixture.ll" -o "$T/input.bc"
run "$ELISA_LLVM_BIN_DIR/llvm-dis" "$T/input.bc" -o "$T/input.ll"
run python3 - "$T/output.ll" "$T/input.ll" <<'PY'
from pathlib import Path
import re,sys
text=Path(sys.argv[1]).read_text()
original=Path(sys.argv[2]).read_text()
def body(name, source=text):
 m=re.search(r'^define\b[^\n]*@'+name+r'\([^\n]*\).*?^}',source,re.M|re.S)
 assert m, name
 return m.group()
for name in ('positive','trip2','trip16'):
 assert '\nloop:' not in body(name), f'{name} eligible loop did not unroll'
assert body('multiple_loops') == body('multiple_loops', original), 'multiple-loop function was modified'
for name in ('trip17','small_trip','mutable','loop_metadata','large','debug','dynamic','counter_independent','volatile','atomic','extra_volatile','extra_atomic','side_effect','poison_bound','optnone'):
 assert '\nloop:' in body(name), f'{name} unexpectedly changed'
 assert body(name) == body(name, original), f'{name} IR was modified'
print('table unroll positive and negative IR probes passed')
PY

# A no-op trial must return status 0 and leave the entire module unchanged.
run "$STAGE1" -O0 -emit obj -o "$T/noop-probe.o" "$ROOT/test/parity/stage1_table_unroll_noop_probe.elisa"
run "${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}" "$T/noop-probe.o" "${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}" -L"$ELISA_LLVM_LIBDIR" $ELISA_LLVM_LIBS $ELISA_LINK_EXE_FLAGS -Wl,-rpath,"$ELISA_LLVM_LIBDIR" -o "$T/noop-probe"
run "$T/noop-probe"
run "$ELISA_LLVM_BIN_DIR/llvm-as" "test/parity/stage1_table_unroll_noop_fixture.ll" -o "$T/noop-input.bc"
run "$ELISA_LLVM_BIN_DIR/llvm-dis" "$T/noop-input.bc" -o "$T/noop-input.ll"
run "$ELISA_LLVM_BIN_DIR/llvm-dis" "$T/test/parity/stage1_table_unroll_noop_output.bc" -o "$T/noop-output.ll"
run python3 - "$T/noop-input.ll" "$T/noop-output.ll" <<'PY'
from pathlib import Path
import sys
before=Path(sys.argv[1]).read_text().splitlines()[1:]
after=Path(sys.argv[2]).read_text().splitlines()[1:]
assert before == after, 'no-op trial modified the module'
print('table unroll no-op probe passed')
PY

# Rejected trials are also bounded: eight optnone loops must consume only four
# attempts and must leave the complete module unchanged.
run "$STAGE1" -O0 -emit obj -o "$T/attempts-probe.o" "$ROOT/test/parity/stage1_table_unroll_attempts_probe.elisa"
run "${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}" "$T/attempts-probe.o" "${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}" -L"$ELISA_LLVM_LIBDIR" $ELISA_LLVM_LIBS $ELISA_LINK_EXE_FLAGS -Wl,-rpath,"$ELISA_LLVM_LIBDIR" -o "$T/attempts-probe"
run "$T/attempts-probe"
run "$ELISA_LLVM_BIN_DIR/llvm-as" "test/parity/stage1_table_unroll_attempts_fixture.ll" -o "$T/attempts-input.bc"
run "$ELISA_LLVM_BIN_DIR/llvm-dis" "$T/attempts-input.bc" -o "$T/attempts-input.ll"
run "$ELISA_LLVM_BIN_DIR/llvm-dis" "$T/test/parity/stage1_table_unroll_attempts_output.bc" -o "$T/attempts-output.ll"
run python3 - "$T/attempts-input.ll" "$T/attempts-output.ll" <<'PY'
from pathlib import Path
import sys
before=Path(sys.argv[1]).read_text().splitlines()[1:]
after=Path(sys.argv[2]).read_text().splitlines()[1:]
assert before == after, 'rejected trials modified the module'
print('table unroll trial budget probe passed')
PY

# Adversarial many-loop function exhausts its small shared graph budget without
# cloning or altering the module. The probe checks work and attempt counters.
run "$STAGE1" -O0 -emit obj -o "$T/graph-probe.o" "$ROOT/test/parity/stage1_table_unroll_graph_budget_probe.elisa"
run "${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}" "$T/graph-probe.o" "${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}" -L"$ELISA_LLVM_LIBDIR" $ELISA_LLVM_LIBS $ELISA_LINK_EXE_FLAGS -Wl,-rpath,"$ELISA_LLVM_LIBDIR" -o "$T/graph-probe"
run "$T/graph-probe"
run "$ELISA_LLVM_BIN_DIR/llvm-as" "test/parity/stage1_table_unroll_graph_budget_fixture.ll" -o "$T/graph-input.bc"
run "$ELISA_LLVM_BIN_DIR/llvm-dis" "$T/graph-input.bc" -o "$T/graph-input.ll"
run "$ELISA_LLVM_BIN_DIR/llvm-dis" "$T/test/parity/stage1_table_unroll_graph_budget_output.bc" -o "$T/graph-output.ll"
run python3 - "$T/graph-input.ll" "$T/graph-output.ll" <<'PY'
from pathlib import Path
import sys
before=Path(sys.argv[1]).read_text().splitlines()[1:]
after=Path(sys.argv[2]).read_text().splitlines()[1:]
assert before == after, 'graph budget decline modified the module'
print('table unroll graph budget probe passed')
PY
