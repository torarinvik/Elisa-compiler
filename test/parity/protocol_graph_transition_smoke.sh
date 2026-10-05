#!/usr/bin/env bash
# Stage1's first consuming classic-graph transition slice is intentionally
# straight-line. Check payload preservation and fail-closed ownership gates.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
source "$ROOT/test/parity/run_timeout.sh"
python3 "$STAGE1_ROOT/scripts/stage1_provenance.py" check "$STAGE1_ROOT" "$STAGE1"
bash "$STAGE1_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$STAGE1" ]] || { echo "protocol graph transition smoke: missing Stage1: $STAGE1" >&2; exit 2; }
[[ -f "$RUNTIME" ]] || { echo "protocol graph transition smoke: missing runtime object: $RUNTIME" >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-protocol-transition.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
CLANG="${ELISA_CLANG:-clang}"
SOURCE="$ROOT/test/repro/protocol_graph_transition_codegen_probe.elisa"

for optimization in 0 2; do
    object="$WORK/transition-O$optimization.o"
    executable="$WORK/transition-O$optimization"
    elisa_run_timeout 60 "$STAGE1" -emit obj "-O$optimization" -o "$object" "$SOURCE" >"$WORK/build.log" 2>&1 || {
        cat "$WORK/build.log" >&2
        exit 1
    }
    elisa_run_timeout 60 "$CLANG" -fno-builtin -o "$executable" "$object" "$RUNTIME"
    elisa_run_timeout 15 "$executable"

    object="$WORK/descendant-O$optimization.o"
    executable="$WORK/descendant-O$optimization"
    elisa_run_timeout 60 "$STAGE1" -emit obj "-O$optimization" -o "$object" \
        "$ROOT/test/repro/protocol_graph_descendant_codegen_probe.elisa" >"$WORK/descendant-build.log" 2>&1 || {
        cat "$WORK/descendant-build.log" >&2
        exit 1
    }
    elisa_run_timeout 60 "$CLANG" -fno-builtin -o "$executable" "$object" "$RUNTIME"
    elisa_run_timeout 15 "$executable"

    object="$WORK/zeroed-controls-O$optimization.o"
    executable="$WORK/zeroed-controls-O$optimization"
    elisa_run_timeout 60 "$STAGE1" -emit obj "-O$optimization" -o "$object" \
        "$ROOT/test/repro/protocol_graph_transition_zeroed_nullable.pos.elisa" >"$WORK/zeroed-controls-build.log" 2>&1 || {
        cat "$WORK/zeroed-controls-build.log" >&2
        exit 1
    }
    elisa_run_timeout 60 "$CLANG" -fno-builtin -o "$executable" "$object" "$RUNTIME"
    elisa_run_timeout 15 "$executable"

    object="$WORK/owners-O$optimization.o"
    executable="$WORK/owners-O$optimization"
    elisa_run_timeout 60 "$STAGE1" -emit obj "-O$optimization" -o "$object" \
        "$ROOT/test/repro/protocol_graph_transition_same_spelling_owners.pos.elisa" >"$WORK/owners-build.log" 2>&1 || {
        cat "$WORK/owners-build.log" >&2
        exit 1
    }
    elisa_run_timeout 60 "$CLANG" -fno-builtin -o "$executable" "$object" "$RUNTIME"
    elisa_run_timeout 15 "$executable"
done

for negative in forged_target missing_move old_owner_reuse alias cross_family no_authority unauthorized_construction zeroed_construction zeroed_generic; do
    source="$ROOT/test/repro/protocol_graph_transition_${negative}.neg.elisa"
    object="$WORK/rejected-$negative.o"
    log="$WORK/rejected-$negative.log"
    set +e
    elisa_run_timeout 30 "$STAGE1" -emit obj -O0 -o "$object" "$source" >"$log" 2>&1
    status=$?
    set -e
    [[ "$status" -eq 1 ]] || { cat "$log" >&2; echo "expected semantic exit 1 for $negative, got $status" >&2; exit 1; }
    [[ ! -e "$object" ]] || { echo "rejected $negative left an object artifact" >&2; exit 1; }
    if [[ "$negative" == unauthorized_construction ]]; then
        rg -Fq 'protocol type "Lease" may only be constructed in its declaring module "Owner" or a nested module' "$log" || { cat "$log" >&2; exit 1; }
    elif [[ "$negative" == zeroed_construction ]]; then
        rg -Fq 'protocol type "Lease" may only be constructed in its declaring module "Owner" or a nested module' "$log" || { cat "$log" >&2; exit 1; }
        rg -Fq 'protocol type "Marker" may only be constructed in its declaring module "Owner" or a nested module' "$log" || { cat "$log" >&2; exit 1; }
        count="$(rg -c 'protocol type .* may only be constructed in its declaring module' "$log" || true)"
        [[ "$count" == 17 ]] || { cat "$log" >&2; echo "expected seventeen typed/nested zeroed construction diagnostics, got $count" >&2; exit 1; }
    elif [[ "$negative" == zeroed_generic ]]; then
        rg -Fq 'cannot initialize aggregate "return" from zeroed: field "" requires a valid non-null value' "$log" || { cat "$log" >&2; exit 1; }
    else
        rg -Fq 'consuming protocol transition is not valid here' "$log" || { cat "$log" >&2; exit 1; }
    fi
done

echo 'protocol graph transition smoke OK: payload-preserving consume, nested module authority, and same-spelling owners at O0/O2; six transition negatives, direct and seventeen typed/nested zeroed-position rejections, generic zeroing rejected'
