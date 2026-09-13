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

# The stubs write a BYTE, not an empty file: build_runtime_object.sh refuses to
# publish a zero-length runtime object now, and a stub that produces nothing makes
# the seed fail for a reason this gate is not about.
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
  'printf "fake product\\n" > "$out"' \
  > "$WORK/core/compiler/bin/elisac"
chmod +x "$WORK/core/compiler/bin/elisac"

printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'printf "%s\\n" "$FAKE_LLVM_LIBDIR"' \
  > "$WORK/llvm-config"
chmod +x "$WORK/llvm-config"

# The stage1 PRODUCT this stub "links" is executed by the seed to build the runtime
# object, so it has to be a working script rather than a touched file -- and it has to
# write a non-empty object, because build_runtime_object.sh refuses to publish a
# zero-length one now. Written as a heredoc: the nested quoting of the printf-args form
# was unreadable and got the escaping wrong twice.
cat > "$WORK/clang" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
out=""
need_out=0
for arg in "$@"; do
  if [[ "$need_out" == 1 ]]; then out="$arg"; need_out=0; continue; fi
  [[ "$arg" == "-o" ]] && need_out=1
done
[[ -n "$out" ]]
cat > "$out" <<'PRODUCT'
#!/usr/bin/env bash
set -uo pipefail
o=""
n=0
for a in "$@"; do
  if [[ "$n" == 1 ]]; then o="$a"; n=0; continue; fi
  [[ "$a" == "-o" ]] && n=1
done
[[ -n "$o" ]] && printf 'fake object\n' > "$o"
exit 0
PRODUCT
chmod +x "$out"
STUB
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
