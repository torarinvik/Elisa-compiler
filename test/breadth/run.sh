#!/usr/bin/env bash
# Breadth triage: build the parse reporter and sweep one or more corpus roots,
# printing per-file parse-error counts (0-error files are silent). Use it to
# find real stage1 parse/semantic gaps against large external corpora.
#
#   test/breadth/run.sh [--write-baseline FILE|--baseline FILE] <dir> [<dir> ...]
#
# Each file is piped to build/parse_report, which prints `P <n>` (parse errors)
# then `D <n>` (semantic diagnostics). Note: semantic diagnostics are computed
# per-file in ISOLATION, so cross-file name references show as UndefinedName —
# only the P (parse) count is meaningful for a single file. Files under a
# `_unused/` path segment (or named `*_unused.elisa`) are skipped (stale,
# intentionally not maintained) — see the precise glob below.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
RPT="${ELISA_PARSE_REPORT:-$ROOT/build/parse_report}"

# The breadth sweep is a stage1 product gate. Keep its reporter construction in the
# shared helper so a standalone invocation and run_all use the same stage1 binary,
# runtime object, freshness guard, and atomic publication path.
export REPO_ROOT="$ROOT" ELISA_STAGE1_BIN="$STAGE1_BIN" ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" ELISA_PARSE_REPORT="$RPT"
source "$ROOT/test/parity/build_parse_report.sh"

total=0
files=0
witherr=0
mode=report
baseline_file=
if [ "${1:-}" = "--write-baseline" ] || [ "${1:-}" = "--baseline" ]; then
    mode="${1#--}"
    baseline_file="${2:?missing baseline file}"
    shift 2
fi
[ "$#" -gt 0 ] || { echo "usage: $0 [--write-baseline FILE|--baseline FILE] <dir> [<dir> ...]" >&2; exit 2; }

observed_file="$(mktemp)"
trap 'rm -f "$observed_file"' EXIT INT TERM HUP
if [ "$mode" = baseline ]; then
    [ -f "$baseline_file" ] || { echo "baseline not found: $baseline_file" >&2; exit 2; }
fi

# PARALLEL (Phase T, 2026-09-06): one `parse_report` per file, files independent, so the scan
# fans out under `xargs -P` (ELISA_BREADTH_JOBS, default = core count) via `--one <out> <file>`;
# each worker appends one observation line to its own file and the parent merges them in
# path order (the baseline is sorted anyway).
one_file() {
    local f="$1" report p diag relative_f
    report=$("$RPT" < "$f")
    p=$(printf '%s\n' "$report" | head -1 | awk '{print $2}')
    diag=$(printf '%s\n' "$report" | sed -n '2p' | awk '{print $2}')
    relative_f="${f#"$ROOT"/}"
    printf '%s\t%s\t%s\n' "$relative_f" "${diag:-0}" "${p:-0}"
}
if [ "${1:-}" = "--one" ]; then
    exec </dev/null
    one_file "$3" > "$2/$(printf '%s' "$3" | tr '/ ' '__').obs"
    exit 0
fi
obs_dir="$(mktemp -d)"
JOBS="${ELISA_BREADTH_JOBS:-$( (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4) )}"
for d in "$@"; do
    # Skip corpus files parked as stale/unmaintained: a path SEGMENT named `_unused`
    # (…/_unused/…) or a basename ending `_unused.elisa`. Deliberately NOT the bare
    # substring `_unused` — that would also swallow legitimate source like
    # check_unused_expression.elisa if this sweep is ever pointed at src/.
    find "$d" -name '*.elisa' 2>/dev/null | grep -v '/_unused/' | grep -v '_unused\.elisa$' | tr '\n' '\0' \
      | xargs -0 -P "$JOBS" -n 1 env RPT="$RPT" ROOT="$ROOT" bash "$0" --one "$obs_dir"
done
cat "$obs_dir"/*.obs 2>/dev/null | sort > "$obs_dir/all.tsv"
rm -f "$obs_dir"/*.obs
while IFS=$'\t' read -r relative_f diag p; do
    files=$((files + 1))
    printf '%s\t%s\n' "$relative_f" "$diag" >> "$observed_file"
    if [ "${p:-0}" -gt 0 ] 2>/dev/null; then
        witherr=$((witherr + 1))
        total=$((total + p))
        printf '%4d  %s\n' "$p" "$relative_f"
    fi
done < "$obs_dir/all.tsv"
rm -rf "$obs_dir"

if [ "$mode" = write-baseline ]; then
    {
        printf '# path relative to the repository root\tdiagnostic count\n'
        while IFS=$'\t' read -r f d; do
            printf '%s\t%s\n' "${f#"$ROOT"/}" "$d"
        done < "$observed_file" | sort
    } > "$baseline_file"
    echo "wrote breadth diagnostic baseline: $baseline_file ($(wc -l < "$observed_file" | tr -d ' ') files)"
elif [ "$mode" = baseline ]; then
    changed=0
    checked=0
    while IFS=$'\t' read -r f d; do
        key="${f#"$ROOT"/}"
        expected=$(awk -F '\t' -v key="$key" '$1 == key { print $2; exit }' "$baseline_file")
        if [ "${expected:-MISSING}" != "$d" ]; then
            printf 'diagnostic-count changed: %s (%s -> %s)\n' "$key" "${expected:-MISSING}" "$d"
            changed=$((changed + 1))
        fi
        checked=$((checked + 1))
    done < "$observed_file"
    while IFS=$'\t' read -r key expected; do
        case "$key" in ''|'#'*) continue;; esac
        if ! awk -F '\t' -v key="$key" '$1 == key { found = 1; exit } END { exit !found }' "$observed_file"; then
            printf 'baseline file missing from scan: %s (expected %s diagnostics)\n' "$key" "$expected"
            changed=$((changed + 1))
        fi
    done < "$baseline_file"
    [ "$changed" -eq 0 ] || { echo "breadth baseline FAILED: $changed file(s) changed" >&2; exit 1; }
    echo "breadth baseline OK: $checked files unchanged"
fi
echo "---"
echo "scanned=$files  files-with-parse-errors=$witherr  total-parse-errors=$total"
