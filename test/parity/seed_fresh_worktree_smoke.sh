#!/usr/bin/env bash
# A clean worktree must be able to start the stage1 seed build. This uses tiny stubs for
# stage0, llvm-config, and clang so the test exercises lock/output ordering without doing a
# full self-host compile.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-seed-smoke.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

mkdir -p "$WORK/scripts" "$WORK/src/driver" "$WORK/core/compiler/bin" "$WORK/lib" "$WORK/tmp"
cp "$ROOT/scripts/elisac_stage1.sh" "$WORK/scripts/elisac_stage1.sh"
printf '%s\n' '# seed fixture source' > "$WORK/src/driver/elisac.elisa"

printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'out=""' \
  'need_out=0' \
  'for arg in "$@"; do' \
  '  if [[ "$need_out" == 1 ]]; then out="$arg"; need_out=0; continue; fi' \
  '  [[ "$arg" == "-o" ]] && need_out=1' \
  'done' \
  '[[ -n "$out" ]]' \
  ': > "$out"' \
  > "$WORK/core/compiler/bin/elisac"
chmod +x "$WORK/core/compiler/bin/elisac"

printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'printf "%s\\n" "$FAKE_LLVM_LIBDIR"' \
  > "$WORK/llvm-config"
chmod +x "$WORK/llvm-config"

printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'out=""' \
  'need_out=0' \
  'for arg in "$@"; do' \
  '  if [[ "$need_out" == 1 ]]; then out="$arg"; need_out=0; continue; fi' \
  '  [[ "$arg" == "-o" ]] && need_out=1' \
  'done' \
  '[[ -n "$out" ]]' \
  ': > "$out"' \
  'chmod +x "$out"' \
  > "$WORK/clang"
chmod +x "$WORK/clang"

FAKE_LLVM_LIBDIR="$WORK/lib" \
TMPDIR="$WORK/tmp" \
ELISA_CORE="$WORK/core" \
ELISACORE_BIN="$WORK/core/compiler/bin/elisac" \
ELISA_STAGE1_BIN="$WORK/bin/elisac-stage1" \
LLVM_CONFIG="$WORK/llvm-config" \
ELISA_CLANG="$WORK/clang" \
  bash "$WORK/scripts/elisac_stage1.sh" --seed >/dev/null

[[ -x "$WORK/bin/elisac-stage1" ]]
[[ -f "$WORK/build/elisac_stage1.o" ]]
[[ ! -e "$WORK/build/.elisac-stage1-seed.lock" ]]
[[ ! -e "$WORK/tmp/elisac-stage1-global-seed.lock" ]]
echo "seed_fresh_worktree_smoke OK"
