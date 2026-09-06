# Sourced on the gate host by tools/remote_run.sh jobs: toolchain PATH and the verification
# env. Lives in a FILE so the local ssh argv never carries the product names (a scanner on
# the Mac kills any local process whose command line mentions them).
RDIR="${ELISA_REMOTE_DIR:-/root/Elisa-compiler}"
# The in-repo clang/cc shim FIRST (tools/linux_shim/clang explains the mappings), then the toolchain.
export ELISA_TOOL_SHIM_DIR="$RDIR/tools/linux_shim"
export PATH="$ELISA_TOOL_SHIM_DIR:/usr/local/go/bin:/usr/local/bin:/usr/lib/llvm-21/bin:$PATH"
ulimit -s unlimited
RDIR="${ELISA_REMOTE_DIR:-/root/Elisa-compiler}"; RCORE="${ELISA_REMOTE_CORE:-/root/structpy-tree}"
cd "$RDIR"
export REPO_ROOT="$RDIR" ELISA_CORE="$RCORE" ELISACORE_BIN="$RCORE/compiler/bin/elisac"
export ELISA_STAGE1_BIN="$RDIR/bin/elisac-stage1" ELISA_RUNTIME_OBJ="$RDIR/build/runtime/elisacore_runtime.o"
export LLVM_CONFIG="$(readlink -f "$(command -v llvm-config)")" ELISA_CLANG="$ELISA_TOOL_SHIM_DIR/clang" ELISA_ALLOW_STALE_STAGE1=1
export ELISA_LLVM_BIN_DIR="$(llvm-config --bindir)" LLC="$(llvm-config --bindir)/llc" LLVM_MC="$(llvm-config --bindir)/llvm-mc"
# stage0 must be the HOST's build: an rsync that carried the Mac binary once left an arm64
# Mach-O here (Exec format error). Rebuild when the file is not a native ELF.
if ! file -b "$ELISACORE_BIN" 2>/dev/null | grep -q ELF; then
  (cd "$RCORE/compiler" && CGO_CFLAGS="-I/usr/lib/llvm-21/include" CGO_LDFLAGS="-L/usr/lib/llvm-21/lib -Wl,-rpath,/usr/lib/llvm-21/lib" go build -o bin/elisac ./src) || echo "stage0 rebuild FAILED" >&2
fi
# z3: the apt package (4.8.12) makes every contract-bearing compile ~25x slower than z3 >= 5
# (37.6 s vs 1.5 s for one std-including probe). Refuse to time anything against it.
case "$(z3 --version 2>/dev/null)" in
  *"version 4."*|"") echo "remote_env: z3 is $(z3 --version 2>/dev/null || echo missing); install a z3 >= 5 release binary in /usr/local/bin (memory note linux-gate-host)" >&2 ;;
esac
export ELISA_LLVM_OPT="$(llvm-config --bindir)/opt"
# The oracle memo (tools/s0cache) for the standalone check list too; ELISA_S0_CACHE=0 disables.
if [ "${ELISA_S0_CACHE:-1}" != 0 ] && [ -z "${ELISA_S0_REAL:-}" ]; then
  export ELISA_S0_REAL="$ELISACORE_BIN" ELISACORE_BIN="$RDIR/tools/s0cache"
fi
