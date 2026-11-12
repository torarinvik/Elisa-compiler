#!/usr/bin/env bash
# An invalid export signature must be diagnosed before code generation.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
[[ -x "$STAGE1" ]] || { echo "malformed export: missing Stage1 compiler" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
work="$(mktemp -d "${TMPDIR:-/tmp}/elisa-malformed-export.XXXXXX")"
trap 'rm -rf "$work"' EXIT INT TERM HUP
ulimit -c 0 || true
set +e
elisa_run_timeout 15 "$STAGE1" -emit llvm -o "$work/output.ll" "$ROOT/test/parity/fixtures/malformed_export_parameter.elisa" >"$work/log" 2>&1
status=$?
set -e
if [[ "$status" -ne 1 ]] || ! grep -q 'expected comma between extern parameters' "$work/log" || [[ -e "$work/output.ll" ]]; then
    echo "malformed export: expected a diagnostic and no output (status $status)" >&2
    cat "$work/log" >&2
    exit 1
fi
echo "malformed export parameter diagnosed without a compiler crash"
