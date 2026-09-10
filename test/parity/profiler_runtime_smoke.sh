#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"
STAGE0_BIN="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$(command -v elisac-stage1 || true)}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"

# The installer puts a host-facing shell wrapper on PATH. Passing that wrapper back
# through ELISA_STAGE1_BIN makes the wrapper export its own path and recursively invoke
# itself. Resolve the snapshot's actual product binary before invoking it.
if [[ -f "$STAGE1_BIN" ]] && grep -q 'exec bash ' "$STAGE1_BIN" 2>/dev/null; then
    STAGE1_SCRIPT="$(sed -n 's/.*exec bash "\(.*\)\/scripts\/elisac_stage1\.sh".*/\1\/scripts\/elisac_stage1.sh/p' "$STAGE1_BIN" | head -n 1)"
    if [[ -n "$STAGE1_SCRIPT" && -x "$STAGE1_SCRIPT" ]]; then
        STAGE1_BIN="${STAGE1_SCRIPT%/scripts/elisac_stage1.sh}/bin/elisac-stage1"
    fi
fi

if [[ ! -x "$STAGE0_BIN" || -z "$STAGE1_BIN" || ! -x "$STAGE1_BIN" ]]; then
    echo "profiler runtime smoke SKIP: stage0/stage1 compiler unavailable"
    exit 0
fi
if [[ ! -f "$RUNTIME_OBJ" ]]; then
    echo "profiler runtime smoke SKIP: runtime object unavailable"
    exit 0
fi
command -v clang >/dev/null 2>&1 || {
    echo "profiler runtime smoke SKIP: clang unavailable"
    exit 0
}

BUILD="$ROOT/build/profiler_runtime_smoke"
mkdir -p "$BUILD"
COLLECTOR_OBJ="$BUILD/profile_collector.o"
clang -std=c11 -O2 -Wall -Wextra -Werror -c \
    -o "$COLLECTOR_OBJ" "$ROOT/test/parity/profile_collector.c"

# Stage0's archive contains its own runtime implementation. The strong collector
# resolves its optional profiler ABI directly from the archive.
"$STAGE0_BIN" -emit c-archive -O2 \
    -o "$BUILD/stage0.a" "$ROOT/test/parity/profiler_runtime_smoke.elisa" \
    >"$BUILD/stage0.log" 2>&1
clang -Wl,-dead_strip -o "$BUILD/stage0" \
    "$COLLECTOR_OBJ" "$BUILD/stage0.a"
"$BUILD/stage0"

# Stage1 emits a program object and uses the shared runtime object. Keep the same
# collector executable path so the two compilers are checked against one ABI.
"$STAGE1_BIN" -emit obj -O2 \
    -o "$BUILD/stage1.o" "$ROOT/test/parity/profiler_runtime_smoke.elisa" \
    >"$BUILD/stage1.log" 2>&1
clang -Wl,-dead_strip -o "$BUILD/stage1" \
    "$COLLECTOR_OBJ" "$BUILD/stage1.o" "$RUNTIME_OBJ"
"$BUILD/stage1"

echo "profiler runtime smoke passed under stage0 and stage1"
