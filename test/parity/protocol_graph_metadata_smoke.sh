#!/usr/bin/env bash
# Parser milestone only: semantic support intentionally remains fail-closed.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-protocol-metadata.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
FIXTURE="$ROOT/test/repro/protocol_graph_codegen_probe.elisa"
elisa_run_timeout 180 env -u ELISACORE_BIN -u ELISA_CORE ELISA_STAGE1_BIN="$STAGE1" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O0 -permissive \
    -o "$WORK/metadata" "$ROOT/test/repro/protocol_graph_metadata_probe.elisa" >"$WORK/build.log" 2>&1 || {
    cat "$WORK/build.log" >&2
    exit 1
}
elisa_run_timeout 15 "$WORK/metadata" < "$FIXTURE"
# Removing the old guard before implementing ownership/authority is not success.
set +e
elisa_run_timeout 30 "$STAGE1" -emit llvm -o "$WORK/unsupported.ll" "$FIXTURE" >"$WORK/reject.log" 2>&1
status=$?
set -e
[[ "$status" -eq 1 ]] || { cat "$WORK/reject.log" >&2; echo "expected semantic rejection, got $status" >&2; exit 1; }
rg -q 'missing a derive state: block' "$WORK/reject.log"
echo 'Stage1 protocol metadata OK: states/edges, module identity, semantic-view preservation, fail-closed guard'
