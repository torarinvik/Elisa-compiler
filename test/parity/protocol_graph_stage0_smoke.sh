#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Stage0-only milestone. Do not present this as Stage1 parity.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?set ELISACORE_BIN to the protocol-graph Stage0 compiler}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-protocol-graph.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
FIXTURE="$ROOT/test/repro/protocol_graph_codegen_probe.elisa"
elisa_run_timeout 30 "$STAGE0" -emit llvm -o "$WORK/protocol.ll" "$FIXTURE"
! rg -q '!elisa\.declined' "$WORK/protocol.ll"
rg -q '^%ProtocolHandle__Closed = type \{ i64 \}$' "$WORK/protocol.ll"
rg -q '^%ProtocolHandle__Open = type \{ i64 \}$' "$WORK/protocol.ll"
for optimization in 0 2; do
    elisa_run_timeout 30 "$STAGE0" -emit c-archive "-O$optimization" -o "$WORK/protocol.a" "$FIXTURE"
    elisa_run_timeout 30 "${ELISA_CLANG:-clang}" $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/protocol" "$WORK/protocol.a"
    elisa_run_timeout 10 "$WORK/protocol"
done
FIXTURE="$ROOT/test/repro/protocol_graph_descendant_codegen_probe.elisa"
for optimization in 0 2; do
    elisa_run_timeout 30 "$STAGE0" -emit c-archive "-O$optimization" -o "$WORK/descendant.a" "$FIXTURE"
    elisa_run_timeout 30 "${ELISA_CLANG:-clang}" $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/descendant" "$WORK/descendant.a"
    elisa_run_timeout 10 "$WORK/descendant"
done
echo 'Stage0 protocol graph OK: independent operations, payload round trip, tag-free layout at O0/O2'
