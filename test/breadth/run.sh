#!/usr/bin/env bash
# Breadth triage: build the parse reporter and sweep one or more corpus roots,
# printing per-file parse-error counts (0-error files are silent). Use it to
# find real stage1 parse/semantic gaps against large external corpora.
#
#   test/breadth/run.sh <dir> [<dir> ...]
#
# Each file is piped to build/parse_report, which prints `P <n>` (parse errors)
# then `D <n>` (semantic diagnostics). Note: semantic diagnostics are computed
# per-file in ISOLATION, so cross-file name references show as UndefinedName —
# only the P (parse) count is meaningful for a single file. Files under a
# `_unused/` path segment (or named `*_unused.elisa`) are skipped (stale,
# intentionally not maintained) — see the precise glob below.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISAC="${ELISAC:-$HOME/.elisac/elisac}"
RPT="$ROOT/build/parse_report"

mkdir -p "$ROOT/build"
"$ELISAC" -emit obj -O2 -permissive -o "$ROOT/build/parse_report.o" "$ROOT/test/breadth/parse_report.elisa"
clang -O2 "$ROOT/build/parse_report.o" -o "$RPT"

total=0
files=0
witherr=0
for d in "$@"; do
    while IFS= read -r f; do
        # Skip corpus files parked as stale/unmaintained: a path SEGMENT named
        # `_unused` (…/_unused/…) or a basename ending `_unused.elisa`. Deliberately
        # NOT the bare substring `_unused` — that would also swallow legitimate
        # source like check_unused_expression.elisa / check_unused_import.elisa /
        # check_unused_decreases.elisa if this sweep is ever pointed at src/.
        case "$f" in */_unused/*|*_unused.elisa) continue;; esac
        files=$((files + 1))
        p=$("$RPT" < "$f" | head -1 | awk '{print $2}')
        if [ "${p:-0}" -gt 0 ] 2>/dev/null; then
            witherr=$((witherr + 1))
            total=$((total + p))
            printf '%4d  %s\n' "$p" "$f"
        fi
    done < <(find "$d" -name '*.elisa' 2>/dev/null)
done
echo "---"
echo "scanned=$files  files-with-parse-errors=$witherr  total-parse-errors=$total"
