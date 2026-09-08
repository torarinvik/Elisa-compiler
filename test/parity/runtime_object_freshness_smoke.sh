#!/usr/bin/env bash
# Bootstrap helper regression; fake tools make rebuild decisions deterministic.
set -euo pipefail
ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-runtime-freshness.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
FIXTURE="$WORK/compiler with spaces"
mkdir -p "$FIXTURE/scripts" "$FIXTURE/elisacore_std" "$FIXTURE/tools"
cp "$ROOT/scripts/build_runtime_object.sh" "$FIXTURE/scripts/build_runtime_object.sh"
printf 'include "./arena.elisa"\n' > "$FIXTURE/elisacore_std/native_runtime_support.elisa"
printf '# original include\n' > "$FIXTURE/elisacore_std/arena.elisa"
cat > "$FIXTURE/tools/compiler" <<'TOOL'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == -emit ]]; then
  printf 'compile\n' >> "$RUNTIME_TEST_LOG"
  [[ "${RUNTIME_TEST_FAIL:-0}" != 1 ]] || exit 9
  if [[ "${RUNTIME_TEST_MUTATE:-0}" == 1 ]]; then
    printf '# concurrent edit\n' >> "$RUNTIME_TEST_INCLUDE"
  fi
fi
out=""
while (($#)); do
  if [[ "$1" == -o ]]; then out="$2"; shift; fi
  shift
done
[[ -n "$out" ]]
printf 'fake runtime object\n' > "$out"
TOOL
cp "$FIXTURE/tools/compiler" "$FIXTURE/tools/clang"
chmod +x "$FIXTURE/tools/compiler" "$FIXTURE/tools/clang"
export ELISACORE_BIN="$FIXTURE/tools/compiler"
export ELISA_S0_REAL="$ELISACORE_BIN"
export ELISA_CLANG="$FIXTURE/tools/clang"
export ELISA_RUNTIME_OBJ="$WORK/output/runtime.o"
export RUNTIME_TEST_LOG="$WORK/compiles"
export RUNTIME_TEST_INCLUDE="$FIXTURE/elisacore_std/arena.elisa"
unset ELISA_RUNTIME_FORCE RUNTIME_TEST_FAIL RUNTIME_TEST_MUTATE
build() { bash "$FIXTURE/scripts/build_runtime_object.sh" > "$WORK/build.log" 2>&1; }
expect_compiles() { [[ "$(wc -l < "$RUNTIME_TEST_LOG" | tr -d ' ')" == "$1" ]]; }

build
expect_compiles 1
build
expect_compiles 1
# Preserve mtime: content, not timestamp, must invalidate an included file.
cp -p "$RUNTIME_TEST_INCLUDE" "$WORK/old-include"
printf '# edited include\n' > "$RUNTIME_TEST_INCLUDE"
touch -r "$WORK/old-include" "$RUNTIME_TEST_INCLUDE"
build
expect_compiles 2
printf '# extra interface\n' > "$FIXTURE/elisacore_std/extra.elisai"
build
expect_compiles 3
rm "$FIXTURE/elisacore_std/extra.elisai"
build
expect_compiles 4
# A corrupt object must not be accepted solely on the input fingerprint.
printf 'corrupt\n' > "$ELISA_RUNTIME_OBJ"
build
expect_compiles 5
ELISA_RUNTIME_FORCE=1 build
expect_compiles 6
cp "$ELISA_RUNTIME_OBJ" "$WORK/last-good.o"
cp "$ELISA_RUNTIME_OBJ.inputs.sha256" "$WORK/last-good.stamp"
printf '# fail this rebuild\n' >> "$RUNTIME_TEST_INCLUDE"
if RUNTIME_TEST_FAIL=1 build; then echo 'failed compiler unexpectedly succeeded' >&2; exit 1; fi
cmp "$ELISA_RUNTIME_OBJ" "$WORK/last-good.o"
cmp "$ELISA_RUNTIME_OBJ.inputs.sha256" "$WORK/last-good.stamp"
if RUNTIME_TEST_MUTATE=1 build; then echo 'concurrent source mutation was accepted' >&2; exit 1; fi
cmp "$ELISA_RUNTIME_OBJ" "$WORK/last-good.o"
cmp "$ELISA_RUNTIME_OBJ.inputs.sha256" "$WORK/last-good.stamp"
build
expect_compiles 9
build
expect_compiles 9
for tool in "$ELISACORE_BIN" "$ELISA_CLANG" "$FIXTURE/scripts/build_runtime_object.sh"; do
  cp -p "$tool" "$WORK/old-tool"
  printf '\n# backdated tool edit\n' >> "$tool"
  touch -r "$WORK/old-tool" "$tool"
  build
done
expect_compiles 12
if find "$WORK/output" -type f ! -name runtime.o ! -name runtime.o.inputs.sha256 | read -r unused; then
  echo 'runtime build leaked temporary files' >&2
  exit 1
fi
echo 'runtime object freshness smoke OK'
