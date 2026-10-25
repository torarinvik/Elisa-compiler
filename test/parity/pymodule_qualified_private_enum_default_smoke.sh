#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

SOURCE="$REPO_ROOT/test/repro/pymodule_qualified_private_enum_default.elisa"
python3 "$REPO_ROOT/test/proofs/check_pymodule_qualified_private_enum.py"
stage0="$("$ELISACORE_BIN" -emit semantic "$SOURCE" 2>&1 >/dev/null || true)"
stage1="$("$RPT" < "$SOURCE")"
grep -q '^P 0$' <<< "$stage1"
grep -qF 'is private to module' <<< "$stage0"
grep -qF 'is private to module' <<< "$stage1"
echo "qualified private enum default smoke OK"
