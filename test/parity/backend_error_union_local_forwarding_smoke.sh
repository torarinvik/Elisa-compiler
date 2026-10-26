#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/scripts/platform.sh"
source "$ROOT/test/parity/run_timeout.sh"

STAGE0="${ELISACORE_BIN:-${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
OPT="${ELISA_OPT:-$ELISA_LLVM_BIN_DIR/opt}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
FIXTURE_DIR="$ROOT/test/fixtures/backend"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-return-forwarding.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "return forwarding smoke: missing Stage0: $STAGE0" >&2; exit 2; }
[[ -x "$STAGE1" ]] || { echo "return forwarding smoke: missing Stage1: $STAGE1" >&2; exit 2; }
[[ -x "$OPT" ]] || { echo "return forwarding smoke: missing opt: $OPT" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

check_failure_payload_order() {
    local ir="$1"
    local symbol="$2"
    python3 - "$ir" "$symbol" <<'PY'
from pathlib import Path
import re
import sys

lines = Path(sys.argv[1]).read_text().splitlines()
symbol = sys.argv[2]
start = next((i for i, line in enumerate(lines) if line.startswith('define ') and f'@{symbol}(' in line), None)
if start is None:
    raise SystemExit(f'missing function @{symbol} in {sys.argv[1]}')
end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == '}'), None)
if end is None:
    raise SystemExit(f'unterminated function @{symbol}')
body = lines[start:end + 1]
label_re = re.compile(r'^([A-Za-z0-9_.$-]+):')
labels = [(i, m.group(1)) for i, line in enumerate(body) if (m := label_re.match(line.strip()))]
blocks = {}
for n, (label_index, label) in enumerate(labels):
    block_end = labels[n + 1][0] if n + 1 < len(labels) else len(body) - 1
    blocks[label] = body[label_index + 1:block_end]
failure_label = next((label for label in blocks if 'try.union.failure' in label), None)
success_label = next((label for label in blocks if 'try.union.success' in label), None)
done_label = next((label for label in blocks if 'try.union.done' in label), None)
if failure_label is None or success_label is None or done_label is None:
    raise SystemExit(f'@{symbol} lacks try.union failure/success blocks')

successor_re = re.compile(r'\blabel\s+%([A-Za-z0-9_.$-]+)')
outgoing = {}
terminators = {}
for label, block in blocks.items():
    instructions = [line.split(';', 1)[0].strip() for line in block if line.strip() and not line.strip().startswith(';')]
    terminator = next((line for line in reversed(instructions) if re.match(r'(ret|br|switch|indirectbr|invoke|unreachable)\b', line)), '')
    terminators[label] = terminator
    outgoing[label] = successor_re.findall(terminator)

reachable = set()
pending = [failure_label]
while pending:
    label = pending.pop()
    if label in reachable:
        continue
    if label not in blocks:
        raise SystemExit(f'@{symbol} failure CFG branches to unknown block %{label}')
    reachable.add(label)
    pending.extend(outgoing[label])
if success_label in reachable or done_label in reachable:
    raise SystemExit(f'@{symbol} failure CFG reaches its success/done block')
for label in reachable:
    text = '\n'.join(blocks[label])
    if re.search(r'\bload\b[^\n]*%try\.union\.payload\.ptr', text) or 'try.union.success.payload' in text:
        raise SystemExit(f'@{symbol} failure CFG loads the success payload in %{label}')
terminals = [label for label in reachable if not outgoing[label]]
if not terminals or not any(terminators[label].startswith('ret ') for label in terminals):
    raise SystemExit(f'@{symbol} failure CFG has no return terminal')
if any(not (terminators[label].startswith('ret ') or terminators[label].startswith('unreachable')) for label in terminals):
    raise SystemExit(f'@{symbol} failure CFG has a non-exiting terminal')
success = '\n'.join(blocks[success_label])
if not re.search(r'try\.union\.success\.payload\s*=\s*load\b', success):
    raise SystemExit(f'@{symbol} success block does not load the payload')
PY
}

compile_and_run() {
    local stage="$1"
    local compiler="$2"
    local fixture="$3"
    local expected="$4"
    local level="$5"
    local name="${stage}-${fixture##*/}-O${level}"
    local exe="$WORK/$name"
    local log="$WORK/$name.compile.log"

    local compiled=0
    if [[ "$stage" == 0 ]]; then
        if "$compiler" -emit llvm "-O$level" -o "$WORK/$name.ll" "$fixture" >"$log" 2>&1 &&
            "$OPT" -passes=verify -disable-output "$WORK/$name.ll" >>"$log" 2>&1 &&
            "$CLANG" "-O$level" -Wno-override-module -o "$exe" "$WORK/$name.ll" >>"$log" 2>&1; then
            compiled=1
        fi
    elif "$compiler" -emit exe "-O$level" -o "$exe" "$fixture" >"$log" 2>&1; then
        compiled=1
    fi
    if [[ "$compiled" != 1 ]]; then
        cat "$log" >&2
        echo "return forwarding smoke: Stage$stage failed to compile $fixture at -O$level" >&2
        return 1
    fi
    local actual
    set +e
    elisa_run_timeout 10 "$exe" >"$WORK/$name.run.log" 2>&1
    actual=$?
    set -e
    if [[ "$actual" -ne "$expected" ]]; then
        cat "$WORK/$name.run.log" >&2
        echo "return forwarding smoke FAILED: Stage$stage $fixture -O$level exit=$actual expected=$expected" >&2
        return 1
    fi
}

# Exercise fieldless, full-family, widened-subset and parameter forwarding.
for level in 0 2; do
    for stage in 0 1; do
        compiler="$STAGE0"
        [[ "$stage" -eq 0 ]] || compiler="$STAGE1"
        compile_and_run "$stage" "$compiler" "$FIXTURE_DIR/return_error_union_local_forwarding_minimal.elisa" 42 "$level"
        compile_and_run "$stage" "$compiler" "$FIXTURE_DIR/return_error_union_local_source_full_family.elisa" 0 "$level"
        compile_and_run "$stage" "$compiler" "$FIXTURE_DIR/return_error_union_local_source_forwarding.elisa" 0 "$level"
        compile_and_run "$stage" "$compiler" "$FIXTURE_DIR/return_error_union_local_forwarding.elisa" 0 "$level"
    done
done

ir="$WORK/full-family-stage1-O0.ll"
log="$WORK/full-family-stage1-O0.log"
if ! "$STAGE1" -emit llvm -O0 -o "$ir" "$FIXTURE_DIR/return_error_union_local_source_full_family.elisa" >"$log" 2>&1; then
    cat "$log" >&2
    echo "return forwarding smoke: failed to emit Stage1 O0 IR" >&2
    exit 1
fi
if rg -q '!elisa\.declined' "$ir"; then
    echo "return forwarding smoke: Stage1 declined the full-family fixture" >&2
    rg -n '!elisa\.declined' "$ir" >&2 || true
    exit 1
fi
"$OPT" -passes=verify -disable-output "$ir"
check_failure_payload_order "$ir" forward_local

echo "return forwarding smoke OK: fieldless, full-family, subset and parameter cases run at O0/O2; failure CFG skips the success payload load"
