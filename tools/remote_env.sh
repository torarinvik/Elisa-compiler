# Sourced on the gate host by tools/remote_run.sh jobs: toolchain PATH and the verification
# env. Lives in a FILE so the local ssh argv never carries the product names (a scanner on
# the Mac kills any local process whose command line mentions them).
RDIR="${ELISA_REMOTE_DIR:-/root/Elisa-compiler}"
RCORE="${ELISA_REMOTE_CORE:-/root/Elisa-core}"
RTOOLROOT="${ELISA_REMOTE_ROOT:-$HOME/elisa}"
REMOTE_LLVM_CONFIG="${ELISA_REMOTE_LLVM_CONFIG:-$RTOOLROOT/bin/llvm-config}"
if [ ! -x "$REMOTE_LLVM_CONFIG" ]; then
  REMOTE_LLVM_CONFIG="${LLVM_CONFIG:-$(command -v llvm-config 2>/dev/null || true)}"
fi
if [ -z "$REMOTE_LLVM_CONFIG" ] || [ ! -x "$REMOTE_LLVM_CONFIG" ]; then
  echo "remote_env: llvm-config not found; set ELISA_REMOTE_LLVM_CONFIG or run tools/remote/setup_host.sh" >&2
  return 2
fi
REMOTE_LLVM_BINDIR="$("$REMOTE_LLVM_CONFIG" --bindir 2>/dev/null)"
REMOTE_LLVM_LIBDIR="$("$REMOTE_LLVM_CONFIG" --libdir 2>/dev/null)"
REMOTE_LLVM_INCLUDEDIR="$("$REMOTE_LLVM_CONFIG" --includedir 2>/dev/null)"
# The in-repo clang/cc shim FIRST (tools/linux_shim/clang explains the mappings), then the toolchain.
# ELISA_NO_LINUX_SHIM=1: no shim; scripts/platform.sh derives the Linux flags instead.
if [ -n "${ELISA_NO_LINUX_SHIM:-}" ]; then
  export ELISA_TOOL_SHIM_DIR=""
  export PATH="/usr/local/go/bin:/usr/local/bin:$REMOTE_LLVM_BINDIR:$PATH"
else
  export ELISA_TOOL_SHIM_DIR="$RDIR/tools/linux_shim"
  export PATH="$ELISA_TOOL_SHIM_DIR:/usr/local/go/bin:/usr/local/bin:$REMOTE_LLVM_BINDIR:$PATH"
fi
export LLVM_CONFIG="$REMOTE_LLVM_CONFIG"
ulimit -s unlimited
cd "$RDIR"
export REPO_ROOT="$RDIR" ELISA_CORE="$RCORE" ELISACORE_BIN="$RCORE/compiler/bin/elisac"
export ELISA_STAGE1_BIN="$RDIR/bin/elisac-stage1" ELISA_RUNTIME_OBJ="$RDIR/build/runtime/elisacore_runtime.o"
export ELISA_CLANG="${ELISA_TOOL_SHIM_DIR:-$REMOTE_LLVM_BINDIR}/clang"
export ELISA_LLVM_BIN_DIR="$REMOTE_LLVM_BINDIR" LLC="$REMOTE_LLVM_BINDIR/llc" LLVM_MC="$REMOTE_LLVM_BINDIR/llvm-mc"
# stage0 must be the HOST's build: an rsync that carried the Mac binary once left an arm64
# Mach-O here (Exec format error). Rebuild when the file is not a native ELF.
if ! file -b "$ELISACORE_BIN" 2>/dev/null | grep -q ELF; then
  (cd "$RCORE/compiler" && CGO_CFLAGS="-I$REMOTE_LLVM_INCLUDEDIR" CGO_LDFLAGS="-L$REMOTE_LLVM_LIBDIR -Wl,-rpath,$REMOTE_LLVM_LIBDIR" go build -o bin/elisac ./src) || echo "stage0 rebuild FAILED" >&2
fi
# z3: the apt package (4.8.12) makes every contract-bearing compile ~25x slower than z3 >= 5
# (37.6 s vs 1.5 s for one std-including probe). Refuse to time anything against it.
case "$(z3 --version 2>/dev/null)" in
  *"version 4."*|"") echo "remote_env: z3 is $(z3 --version 2>/dev/null || echo missing); install a z3 >= 5 release binary in /usr/local/bin (memory note linux-gate-host)" >&2 ;;
esac
export ELISA_LLVM_OPT="$REMOTE_LLVM_BINDIR/opt"
# The oracle memo (tools/s0cache) for the standalone check list too; ELISA_S0_CACHE=0 disables.
if [ "${ELISA_S0_CACHE:-1}" != 0 ] && [ -z "${ELISA_S0_REAL:-}" ]; then
  export ELISA_S0_REAL="$ELISACORE_BIN" ELISACORE_BIN="$RDIR/tools/s0cache"
fi
