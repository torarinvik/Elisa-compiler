# Remote half of tools/remote_gate.sh — runs on the gate host with RDIR/RCORE/LIST prepended.
set -uo pipefail
# rsync keeps the Mac uid; git refuses such repos unless they are marked safe.
git config --global --get-all safe.directory | grep -qx "$RDIR" || git config --global --add safe.directory "$RDIR"
git config --global --get-all safe.directory | grep -qx "$RCORE" || git config --global --add safe.directory "$RCORE"
# Always rebuild stage0 first: Go's cache makes it seconds, and the seed needs VCS build info
# matching the synced tree. remote_env.sh only rebuilds a non-ELF binary.
(cd "$RCORE/compiler" && PATH=/usr/local/go/bin:$PATH CGO_CFLAGS="-I/usr/lib/llvm-21/include" CGO_LDFLAGS="-L/usr/lib/llvm-21/lib -Wl,-rpath,/usr/lib/llvm-21/lib" go build -o bin/elisac ./src)
# The shared gate-host environment: tools/linux_shim first on PATH (translates the suite's
# Apple-ld link flags), LLVM/clang paths, stack limit and the stage0 oracle cache.
ELISA_REMOTE_DIR="$RDIR" ELISA_REMOTE_CORE="$RCORE" source "$RDIR/tools/remote_env.sh"
mkdir -p bin build/runtime
[ -f "$ELISA_RUNTIME_OBJ" ] || bash scripts/build_runtime_object.sh
# The seed guard defaults to 6 GB; Linux stage0 peaks above it, and the gate host has far more.
export ELISA_STAGE1_SEED_MAX_RSS_KB="${ELISA_STAGE1_SEED_MAX_RSS_KB:-60000000}"
rm -rf build/.elisac-stage1-seed.lock
if ! bash scripts/elisac_stage1.sh --seed >build/remote-seed.log 2>&1; then
  grep -v "warning:" build/remote-seed.log | tail -20; echo "remote gate: seed failed; no checks run"; exit 1
fi
for chk in $LIST; do
  s=$(date +%s); echo "== $chk"
  bash "test/parity/$chk.sh" 2>&1 | grep -v "warning:" | tail -8
  echo "   ($(( $(date +%s) - s ))s)"
done
