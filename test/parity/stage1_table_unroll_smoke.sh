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
run python3 "$ROOT/test/parity/stage1_table_unroll_clean_fixture.py"
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
for name in ('trip17','small_trip','mutable','large','dynamic','counter_independent','volatile','atomic','extra_volatile','extra_atomic','side_effect','poison_bound','optnone'):
 assert '\nloop:' in body(name), f'{name} unexpectedly changed'
 assert body(name) == body(name, original), f'{name} IR was modified'
print('table unroll positive and negative IR probes passed')
PY

# Known, bounded loop and profile metadata must not block otherwise safe trials.
run python3 - <<'PYCODE'
from pathlib import Path
import re
p = Path("test/parity/stage1_table_unroll_fixture.ll")
s = Path("test/parity/stage1_table_unroll_debug_fixture.ll").read_text()
s = re.sub(r'^define i64 @debug\(\) !dbg !11 \{.*?^}\n', '', s, flags=re.M | re.S)
s = re.sub(r'^!(?:llvm\.dbg\.cu|llvm\.module\.flags|1[0-6]) = .*\n', '', s, flags=re.M)
s = s.replace('define i64 @positive()', 'define range(i64 0, 512) i64 @positive()', 1)
old = 'br i1 %done, label %exit, label %loop, !llvm.loop !0'
assert s.count(old) == 1
s = s.replace(old, old + ', !prof !2', 1)
p.write_text(s + '\n!2 = !{!"branch_weights", i32 1, i32 11}\n')
PYCODE
run "$T/probe"
run "$ELISA_LLVM_BIN_DIR/llvm-dis" "$T/test/parity/stage1_table_unroll_output.bc" -o "$T/metadata-output.ll"
run "$ELISA_LLVM_BIN_DIR/opt" -passes=verify -disable-output "$T/test/parity/stage1_table_unroll_output.bc"
run python3 - "$T/metadata-output.ll" <<'PYCODE'
from pathlib import Path
import re, sys
s = Path(sys.argv[1]).read_text()
match = re.search(r'^define\b[^\n]*@positive\([^\n]*\).*?^}', s, re.M | re.S)
assert match and '\nloop:' not in match.group(), 'metadata blocked eligible loop'
assert '!llvm.loop' in s and '!prof' in s, 'unrelated metadata was lost'
print('table unroll bounded metadata probe passed')
PYCODE

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

# Oversized module owner/constant graphs and aliases decline without cloning.
run "$STAGE1" -O0 -emit obj -o "$T/clone-budget-probe.o" "$ROOT/test/parity/stage1_table_unroll_clone_budget_probe.elisa"
run "${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}" "$T/clone-budget-probe.o" "${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}" -L"$ELISA_LLVM_LIBDIR" $ELISA_LLVM_LIBS $ELISA_LINK_EXE_FLAGS -Wl,-rpath,"$ELISA_LLVM_LIBDIR" -o "$T/clone-budget-probe"
for kind in control edges globals functions constant alias metadata instruction_metadata integer longname stringattr shuffle rangelist section_global section_function comdat comdat_function gc personality prefix prologue debug; do
    run python3 "$ROOT/test/parity/stage1_table_unroll_clone_budget_gen.py" "$kind"
    run "$T/clone-budget-probe"
    run "$ELISA_LLVM_BIN_DIR/llvm-as" "test/parity/stage1_table_unroll_clone_budget_fixture.ll" -o "$T/clone-budget-input.bc"
    run "$ELISA_LLVM_BIN_DIR/llvm-dis" "$T/clone-budget-input.bc" -o "$T/clone-budget-input.ll"
    run "$ELISA_LLVM_BIN_DIR/llvm-dis" "test/parity/stage1_table_unroll_clone_budget_output.bc" -o "$T/clone-budget-output.ll"
    run python3 - "$kind" "$T/clone-budget-input.ll" "$T/clone-budget-output.ll" <<'PYCODE'
from pathlib import Path
import re
import sys
kind, before_path, after_path = sys.argv[1:]
before = Path(before_path).read_text()
after = Path(after_path).read_text()
if kind == 'control':
    def body(text):
        match = re.search(r'^define\b[^\n]*@positive\([^\n]*\).*?^}', text, re.M | re.S)
        assert match, 'control fixture lost positive loop'
        return match.group()
    assert '\nloop:' in body(before), 'control input has no positive loop'
    assert '\nloop:' not in body(after), 'control did not run the positive loop trial'
else:
    assert before.splitlines()[1:] == after.splitlines()[1:], 'clone-budget decline modified module'
PYCODE
done
