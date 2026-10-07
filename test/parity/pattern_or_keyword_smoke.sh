#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# `or` is accepted as the readable spelling of a pattern alternative. This must execute,
# because the historical bug parsed the file and silently matched only the first alternative.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/pattern_or_keyword.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$WRAPPER" -emit obj -O0 -o "$WORK/program.o" "$SOURCE"
clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/program" "$WORK/program.o" "$REPO_ROOT/build/runtime/elisacore_runtime.o"
"$WORK/program"

echo "pattern-or-keyword smoke OK: every packed variant alternative matched"
