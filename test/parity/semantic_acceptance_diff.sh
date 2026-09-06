#!/usr/bin/env bash
# Replay every end-to-end stage0 semantic test source through stage1 and require
# agreement on whether analysis is clean or emits at least one error/warning.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
ORACLE_DIR="$ELISA_CORE/compiler"
if [[ "${1:-}" == "--chunk" ]]; then
    WORK="$2"
else
    WORK="$(mktemp -d)"
    trap 'rm -rf "$WORK"' EXIT INT TERM HUP
fi
ORACLE="$WORK/oracle.tsv"
MISMATCHES="$WORK/mismatches.tsv"

export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

# A currently failing stage0 test may still emit a complete oracle. Treat the
# emitted denominator as authoritative; the inventory gate checks its coverage.
if [[ "${1:-}" != "--chunk" ]]; then
(cd "$ORACLE_DIR" && ELISA_SEMANTIC_PARITY_OUT="$ORACLE" go test ./test/semantic -count=1 >/dev/null 2>&1) || true
case_count="$(wc -l < "$ORACLE" | tr -d ' ')"
[[ "$case_count" -gt 0 ]] || {
    echo "semantic acceptance diff FAILED: stage0 emitted no oracle cases" >&2
    exit 1
}
fi

# Trusted-stdlib basenames (mirrors semantic/permissions_validation.go's runtimeStdBaseNames):
# a source with one of these names, or living under an elisacore_std/ directory, is exempt
# from user-only passes (raw-atomic-surface removal). Replayed via a `# std` header.
is_runtime_std() {
    local path="$1"
    case "$(dirname -- "$path")" in
        */elisacore_std|elisacore_std) return 0 ;;
    esac
    case "$(basename -- "$path")" in
        allocator.elisa|arena.elisa|collections.elisa|debug_referee.elisa|deque.elisa|\
        elisacore_runtime.elisa|elisacore_runtime_concurrency.elisa|elisacore_runtime_prelude.elisa|\
        elisacore_runtime_strings.elisa|elisacore_runtime_system_bridge.elisa|heap.elisa|names.elisa|\
        native_runtime_support.elisa|runtime.elisa|stores.elisa|stores_core.elisa|\
        stores_packed_dense.elisa|stores_packed_encoding.elisa|stores_packed_sparse.elisa|\
        stores_rows.elisa|stores_types.elisa|test.elisa) return 0 ;;
    esac
    return 1
}

# PARALLEL (Phase T, 2026-09-06): the oracle is split into ELISA_ACCEPT_JOBS chunks (default =
# core count), each replayed by a re-entry of this script (`--chunk <work> <file>`) that
# writes `<file>.mismatches`; the parent concatenates in chunk order (deterministic report).
replay_chunk() {
    local MISMATCHES="$1.mismatches"
    : > "$MISMATCHES"
while IFS=$'\t' read -r name expected_errors expected_warnings encoded_filename encoded_source; do
    filename="$(printf '%s' "$encoded_filename" | openssl base64 -d -A 2>/dev/null)"
    header=""
    [[ "$name" == TestAnalyzeStrict* ]] && header+=$'# strict\n'
    is_runtime_std "$filename" && header+=$'# std\n'
    out="$({ printf '%s' "$header"; printf '%s' "$encoded_source" | openssl base64 -d -A; } | "$RPT")"
    parse_errors="$(printf '%s\n' "$out" | awk '$1 == "P" { print $2; exit }')"
    diagnostics="$(printf '%s\n' "$out" | awk '$1 == "D" { print $2; exit }')"
    [[ -n "$parse_errors" ]] || parse_errors=999999
    [[ -n "$diagnostics" ]] || diagnostics=999999
    expected_class=0
    actual_class=0
    [[ $((expected_errors + expected_warnings)) -gt 0 ]] && expected_class=1
    [[ $((parse_errors + diagnostics)) -gt 0 ]] && actual_class=1
    if [[ "$expected_class" != "$actual_class" ]]; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$expected_errors" "$expected_warnings" "$parse_errors" "$diagnostics" "$encoded_source" >> "$MISMATCHES"
    fi
done < "$1"
}

if [[ "${1:-}" == "--chunk" ]]; then
    WORK="$2"; replay_chunk "$3"; exit 0
fi

JOBS="${ELISA_ACCEPT_JOBS:-$( (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4) )}"
per_chunk=$(( (case_count + JOBS - 1) / JOBS )); [[ "$per_chunk" -gt 0 ]] || per_chunk=1
mkdir -p "$WORK/chunks"
split -l "$per_chunk" "$ORACLE" "$WORK/chunks/c."
find "$WORK/chunks" -name 'c.??' -print0 \
  | xargs -0 -P "$JOBS" -n 1 env RPT="$RPT" REPO_ROOT="$REPO_ROOT" ELISACORE_BIN="$ELISACORE_BIN" ELISA_CORE="$ELISA_CORE" bash "$0" --chunk "$WORK"
: > "$MISMATCHES"
for chunk in "$WORK"/chunks/c.??; do   # `c.??` only: the side files are c.??.count/.mismatches
    [[ -f "$chunk.mismatches" ]] || { echo "semantic acceptance diff FAILED: chunk $chunk produced no result (worker died)" >&2; exit 1; }
    cat "$chunk.mismatches" >> "$MISMATCHES"
done

mismatch_count=0
[[ -f "$MISMATCHES" ]] && mismatch_count="$(wc -l < "$MISMATCHES" | tr -d ' ')"
if [[ "$mismatch_count" -ne 0 ]]; then
    echo "semantic acceptance diff FAILED: $mismatch_count/$case_count stage0 cases disagree" >&2
    cut -f1-5 "$MISMATCHES" >&2
    exit 1
fi

echo "semantic acceptance diff OK: $case_count/$case_count stage0 end-to-end cases agree" >&2
