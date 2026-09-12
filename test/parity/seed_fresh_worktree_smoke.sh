#!/usr/bin/env bash
# A clean worktree must be able to start the stage1 seed build. This uses tiny stubs for
# stage0, llvm-config, and clang so the test exercises lock/output ordering without doing a
# full self-host compile.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-seed-smoke.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

mkdir -p "$WORK/scripts" "$WORK/src/driver" "$WORK/core/compiler/bin" "$WORK/lib" "$WORK/tmp"
# The wrapper sources its seed half, so the fixture worktree needs both files --
# and the seed half shells out to write_profiler_hook_fallbacks.sh to refresh the
# runtime's optional-hook object (3c7e6552), so that has to come along too or the
# seed dies on a missing file in a worktree that is otherwise complete.
for part in elisac_stage1.sh elisac_stage1_seed.sh write_profiler_hook_fallbacks.sh build_runtime_object.sh; do
  cp "$ROOT/scripts/$part" "$WORK/scripts/$part"
done
printf '%s\n' '# seed fixture source' > "$WORK/src/driver/elisac.elisa"
# The seed builds the runtime object after the product (70589584), and that helper
# reads elisacore_std/native_runtime_support.elisa and fingerprints the whole
# directory. A clean worktree has one; this fixture stubs it, in keeping with the
# stub stage0/clang above -- the gate is about lock and output ordering, not about
# compiling a real runtime.
mkdir -p "$WORK/elisacore_std"
printf '%s\n' '# seed fixture runtime source' > "$WORK/elisacore_std/native_runtime_support.elisa"

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
