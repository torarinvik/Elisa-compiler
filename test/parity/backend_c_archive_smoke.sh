#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AR_BIN="${AR:-$(command -v ar || true)}"
if [[ -z "$AR_BIN" ]]; then
    echo "backend_c_archive_smoke SKIP: ar not found"
    exit 0
fi
runtime="$ROOT/build/runtime/elisacore_runtime.o"
object="$ROOT/build/case_generic_nested_3.o"
if [[ ! -f "$runtime" || ! -f "$object" ]]; then
    echo "backend_c_archive_smoke SKIP: stage1 object/runtime artifacts not present"
    exit 0
fi
mkdir -p "$ROOT/build/c_archive_smoke"
archive="$ROOT/build/c_archive_smoke/libelisa.a"
AR="$AR_BIN" python3 "$ROOT/scripts/emit_c_archive.py" --output "$archive" "$object" "$runtime"
[[ -s "$archive" ]] || { echo "backend_c_archive_smoke FAILED: archive is empty"; exit 1; }
members="$($AR_BIN -t "$archive")"
grep -q 'case_generic_nested_3.o' <<<"$members" || { echo "backend_c_archive_smoke FAILED: user object missing"; exit 1; }
grep -q 'elisacore_runtime.o' <<<"$members" || { echo "backend_c_archive_smoke FAILED: runtime object missing"; exit 1; }
echo "backend_c_archive_smoke OK"
