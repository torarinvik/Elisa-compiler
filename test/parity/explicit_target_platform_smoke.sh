#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?set ELISACORE_BIN}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/explicit-target-platform.XXXXXX")"
echo "artifacts: $WORK"
for row in x86_64-unknown-linux-gnu:linux:x86_64 aarch64-unknown-linux-gnu:linux:arm64 \
    arm64-apple-darwin:macos:arm64 x86_64-pc-windows-gnu:windows:x86_64 \
    x86_64-unknown-freebsd:freebsd:x86_64 wasm32-unknown-wasi:wasi:wasm32 \
    wasm32-unknown-unknown:wasi:wasm32 wasm64-unknown-unknown:wasi:wasm64 \
    x86_64-unknown-none:unknown:x86_64; do
    triple="${row%%:*}"
    selection="${row#*:}"
    expected="${selection%:*}"
    architecture="${row##*:}"
    for stage in stage0 stage1; do
        compiler="$STAGE0"
        [[ "$stage" != stage1 ]] || compiler="$STAGE1"
        # Conflicting inherited host flags must not win over the explicit triple.
        ELISA_HOST_LINUX=1 ELISA_HOST_WINDOWS=1 ELISA_HOST_X86_64=1 ELISA_STAGE1_WASM=1 \
            "$compiler" -emit llvm -target-triple "$triple" \
            -o "$WORK/$stage-$triple.ll" \
            "$ROOT/test/repro/explicit_target_platform.elisa"
        [[ -s "$WORK/$stage-$triple.ll" ]]
        grep -Fq "@selected_${expected}_branch" "$WORK/$stage-$triple.ll"
        grep -Fq "@selected_${architecture}_arch" "$WORK/$stage-$triple.ll"
        for other in macos linux windows freebsd wasi unknown; do
            if [[ "$other" != "$expected" ]] && grep -Fq "@selected_${other}_branch" "$WORK/$stage-$triple.ll"; then
                echo "$stage $triple incorrectly retained $other platform branch" >&2
                exit 1
            fi
        done
        for other in macos linux windows freebsd; do
            if [[ "$other" == "$expected" ]]; then
                grep -Fq "@independent_${other}_flag" "$WORK/$stage-$triple.ll"
            elif grep -Fq "@independent_${other}_flag" "$WORK/$stage-$triple.ll"; then
                echo "$stage $triple leaked the independent $other flag" >&2
                exit 1
            fi
        done
        for other in x86_64 arm64 wasm32 wasm64 unknown; do
            if [[ "$other" != "$architecture" ]] && grep -Fq "@selected_${other}_arch" "$WORK/$stage-$triple.ll"; then
                echo "$stage $triple incorrectly retained $other architecture" >&2
                exit 1
            fi
        done
        echo "$stage $triple selects $expected/$architecture PASS"
    done
done
echo 'explicit target platform: requested triple wins over host flags PASS'
