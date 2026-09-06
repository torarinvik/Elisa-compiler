# Remote half of tools/remote_gate.sh — runs on the gate host with RDIR/RCORE/LIST prepended.
set -uo pipefail
export PATH=/usr/local/go/bin:/usr/local/bin:/usr/lib/llvm-21/bin:$PATH
ulimit -s unlimited
cd "$RDIR"
export REPO_ROOT="$RDIR" ELISA_CORE="$RCORE" ELISACORE_BIN="$RCORE/compiler/bin/elisac" ELISA_STAGE1_BIN="$RDIR/bin/elisac-stage1" ELISA_RUNTIME_OBJ="$RDIR/build/runtime/elisacore_runtime.o"
export LLVM_CONFIG="$(command -v llvm-config)" ELISA_CLANG="$(command -v clang)"
mkdir -p bin build/runtime
[ -x "$ELISACORE_BIN" ] || (cd "$RCORE/compiler" && CGO_CFLAGS="-I/usr/lib/llvm-21/include" CGO_LDFLAGS="-L/usr/lib/llvm-21/lib -Wl,-rpath,/usr/lib/llvm-21/lib" go build -o bin/elisac ./src)
[ -f "$ELISA_RUNTIME_OBJ" ] || bash scripts/build_runtime_object.sh
rm -rf build/.elisac-stage1-seed.lock
bash scripts/elisac_stage1.sh --seed 2>&1 | grep -v "warning:" | tail -2
for chk in $LIST; do
  s=$(date +%s); echo "== $chk"
  bash "test/parity/$chk.sh" 2>&1 | grep -v "warning:" | tail -8
  echo "   ($(( $(date +%s) - s ))s)"
done
