#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?set ELISACORE_BIN to the Stage0 compiler under test}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-owner-flow.XXXXXX")"
cleanup() {
    rm -f "$WORK/probe.a" "$WORK/probe" "$WORK/build.log" \
        "$WORK/probe.elisa-abi.json" "$WORK/probe.h" "$WORK/probe.unsafe.txt"
    rmdir "$WORK"
}
trap cleanup EXIT
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}"
for optimization in O0 O2; do
    "$STAGE0" -emit c-archive "-$optimization" -o "$WORK/probe.a" \
        "$ROOT/test/repro/ownership_binding_flow_probe.elisa" >"$WORK/build.log" 2>&1 || {
        tail -80 "$WORK/build.log" >&2
        exit 1
    }
    clang -Wl,-dead_strip "$WORK/probe.a" -o "$WORK/probe"
    "$WORK/probe"
done
echo 'BindingId ownership facts pass O0/O2: branch consumption, dead paths, shadow/function isolation, serial zero, all 16 consume inputs'
