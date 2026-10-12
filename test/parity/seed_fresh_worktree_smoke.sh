#!/usr/bin/env bash
# A clean worktree must be able to start the stage1 seed build. This uses tiny stubs for
# stage0, llvm-config, and clang so the test exercises lock/output ordering without doing a
# full self-host compile.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-seed-smoke.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

mkdir -p "$WORK/scripts" "$WORK/src/driver" "$WORK/core/compiler/bin" "$WORK/core/compiler/src" "$WORK/lib" "$WORK/tmp"
printf '%s\n' 'fake llvm library' > "$WORK/lib/libLLVM.dylib"
# The wrapper sources its seed half, so the fixture worktree needs both files --
# and the seed half shells out to write_profiler_hook_fallbacks.sh to refresh the
# runtime's optional-hook object (3c7e6552), so that has to come along too or the
# seed dies on a missing file in a worktree that is otherwise complete.
# The provenance manifest fingerprints every build helper, including the object cache.
for part in \
  platform.sh \
  elisac_stage1.sh \
  stage1_object_cache.py \
  process_rss.sh \
  assert_stage0_fresh.sh \
  assert_stage1_fresh.sh \
  elisac_stage1_seed.sh \
  write_profiler_hook_fallbacks.sh \
  build_runtime_object.sh \
  stage1_provenance.py; do
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

# Both freshness guards are part of the path under test. Give the fixture source tree a
# real revision, and build a tiny Go stage0 stub with VCS metadata instead of bypassing
# assert_stage0_fresh.sh or asking a shell script to impersonate a Go product.
git -C "$WORK" init -q
git -C "$WORK" config user.name seed-fresh-worktree-smoke
git -C "$WORK" config user.email seed-fresh-worktree-smoke@example.invalid
git -C "$WORK" add scripts src elisacore_std
git -C "$WORK" commit -qm 'seed smoke fixture source'

cat > "$WORK/core/compiler/go.mod" <<'MOD'
module seed-smoke.local/compiler

go 1.22
MOD
cat > "$WORK/core/compiler/src/main.go" <<'GO'
package main

import (
	"os"
)

func main() {
	for index := 1; index+1 < len(os.Args); index++ {
		if os.Args[index] == "-o" {
			if err := os.WriteFile(os.Args[index+1], []byte("fake object\\n"), 0o644); err != nil {
				os.Exit(1)
			}
			return
		}
	}
	os.Exit(2)
}
GO
printf '%s\n' '/bin/' > "$WORK/core/compiler/.gitignore"
git -C "$WORK/core/compiler" init -q
git -C "$WORK/core/compiler" config user.name seed-fresh-worktree-smoke
git -C "$WORK/core/compiler" config user.email seed-fresh-worktree-smoke@example.invalid
git -C "$WORK/core/compiler" add go.mod src/main.go .gitignore
git -C "$WORK/core/compiler" commit -qm 'seed smoke stage0 stub source'
go -C "$WORK/core/compiler" build -buildvcs=true -o "$WORK/core/compiler/bin/elisac" ./src

# The stubs write a BYTE, not an empty file: build_runtime_object.sh refuses to
# publish a zero-length runtime object now, and a stub that produces nothing makes
# the seed fail for a reason this gate is not about. Provenance also asks LLVM for
# its version and selected shared-library path, so model those queries explicitly.
cat > "$WORK/llvm-config" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  --version) echo "23.1.3" ;;
  --bindir) echo "$FAKE_LLVM_BINDIR" ;;
  --libdir) echo "$FAKE_LLVM_LIBDIR" ;;
  "--link-shared --libfiles") echo "$FAKE_LLVM_LIBDIR/libLLVM.dylib" ;;
  *) echo "unsupported llvm-config arguments: $*" >&2; exit 2 ;;
esac
STUB
chmod +x "$WORK/llvm-config"

# The provenance probe resolves and fingerprints the external linker selected by Clang.
# Keep that tool deterministic in this smoke fixture instead of interrogating the host linker.
cat > "$WORK/ld" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  -v|--version) echo "seed-fresh-worktree-smoke linker" ;;
esac
STUB
chmod +x "$WORK/ld"

# The stage1 PRODUCT this stub "links" is executed by the seed to build the runtime
# object, so it has to be a working script rather than a touched file -- and it has to
# write a non-empty object, because build_runtime_object.sh refuses to publish a
# zero-length one now. Written as a heredoc: the nested quoting of the printf-args form
# was unreadable and got the escaping wrong twice.
cat > "$WORK/clang" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--version" ]]; then
  echo "clang version seed-fresh-worktree-smoke"
  exit 0
fi
if [[ "${1:-}" == "-###" ]]; then
  printf '"%s" -v\n' "$FAKE_LINKER" >&2
  exit 0
fi
if [[ ! -e "$FAKE_CLANG_ARGS" ]]; then
  printf '%s\n' "$@" > "$FAKE_CLANG_ARGS"
fi
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

# EVERY output path the seed honours must be pinned INSIDE the fixture. run_all exports
# ELISA_RUNTIME_OBJ pointing at the REAL tree, and build_runtime_object.sh honours it over
# its own $ROOT -- so under run_all this fixture's stub clang wrote its "fake object" script
# straight over build/runtime/elisacore_runtime.o, and the ~27 gates that link against the
# runtime failed with `ld: unknown file type` for the rest of the run (2026-09-16).
# Keep this stub seed's lock private; a real Stage1 seed on the host stays serialized.
FAKE_LLVM_LIBDIR="$WORK/lib" \
FAKE_LLVM_BINDIR="$WORK" \
TMPDIR="$WORK/tmp" \
ELISA_STAGE1_GLOBAL_SEED_LOCK_DIR="$WORK/tmp/elisac-stage1-global-seed.lock" \
ELISA_RUNTIME_OBJ="$WORK/build/runtime/elisacore_runtime.o" \
ELISA_PARSE_REPORT="$WORK/build/parse_report" \
FAKE_CLANG_ARGS="$WORK/clang.args" \
FAKE_LINKER="$WORK/ld" \
ELISA_CORE="$WORK/core" \
ELISACORE_BIN="$WORK/core/compiler/bin/elisac" \
ELISA_STAGE1_BIN="$WORK/bin/elisac-stage1" \
LLVM_CONFIG="$WORK/llvm-config" \
ELISA_CLANG="$WORK/clang" \
  bash "$WORK/scripts/elisac_stage1.sh" --seed >"$WORK/seed.log" 2>&1 || {
    cat "$WORK/seed.log" >&2
    exit 1
  }

grep -F "seed: building Stage1 product with stage0 bootstrap compiler $WORK/core/compiler/bin/elisac" "$WORK/seed.log" >/dev/null

[[ -x "$WORK/bin/elisac-stage1" ]]
[[ -f "$WORK/build/elisac_stage1.o" ]]
[[ ! -e "$WORK/build/.elisac-stage1-seed.lock" ]]
[[ ! -e "$WORK/tmp/elisac-stage1-global-seed.lock" ]]
LLVM_CONFIG="$WORK/llvm-config" \
ELISA_CLANG="$WORK/clang" \
ELISA_LLVM_BIN_DIR="$WORK" \
ELISA_LLVM_LIBDIR="$WORK/lib" \
ELISA_LLVM_LIBS="-lLLVM" \
  bash "$WORK/scripts/assert_stage1_fresh.sh" "$WORK/bin/elisac-stage1"
grep -Fx -- '-fno-builtin' "$WORK/clang.args" >/dev/null
case "$(uname -s)" in
  Linux)
    grep -Fx -- '-no-pie' "$WORK/clang.args" >/dev/null
    grep -Fx -- '-Wl,--gc-sections' "$WORK/clang.args" >/dev/null
    ! grep -Fx -- '-Wl,-dead_strip' "$WORK/clang.args" >/dev/null
    ! grep -Fx -- '-Wl,-stack_size,0x20000000' "$WORK/clang.args" >/dev/null
    ;;
  Darwin)
    grep -Fx -- '-Wl,-dead_strip' "$WORK/clang.args" >/dev/null
    grep -Fx -- '-Wl,-stack_size,0x20000000' "$WORK/clang.args" >/dev/null
    ! grep -Fx -- '-no-pie' "$WORK/clang.args" >/dev/null
    ! grep -Fx -- '-Wl,--gc-sections' "$WORK/clang.args" >/dev/null
    ;;
  *)
    echo "seed_fresh_worktree_smoke: unsupported host $(uname -s)" >&2
    exit 2
    ;;
esac
echo "seed_fresh_worktree_smoke OK"
