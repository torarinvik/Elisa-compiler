# Sourced by tools/local_run.sh jobs: the Mac verification env, in a FILE so the job's argv
# stays short and neutral. Mirrors tools/remote_env.sh; both derive everything from the repo.
LDIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$LDIR"
export REPO_ROOT="$LDIR"
export ELISA_CORE="${ELISA_CORE:-$LDIR/../../Go projects/structpy-tree}"
export ELISA_STAGE1_BIN="${ELISA_STAGE1_BIN:-$LDIR/bin/elisac-stage1}"
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$LDIR/build/runtime/elisacore_runtime.o}"
export ELISA_ALLOW_STALE_STAGE1=1
export LLVM_CONFIG="${LLVM_CONFIG:-$(command -v llvm-config || echo /opt/homebrew/opt/llvm/bin/llvm-config)}"
export ELISA_LLVM_BIN_DIR="$("$LLVM_CONFIG" --bindir)"
export LLC="${LLC:-$ELISA_LLVM_BIN_DIR/llc}" LLVM_MC="${LLVM_MC:-$ELISA_LLVM_BIN_DIR/llvm-mc}"
export ELISA_LLVM_OPT="${ELISA_LLVM_OPT:-$ELISA_LLVM_BIN_DIR/opt}"
# The oracle memo (tools/s0cache); ELISA_S0_CACHE=0 disables. Set ELISA_S0_REAL first so a
# `go build -o "$ELISACORE_BIN"` inside a harness rebuilds the compiler, not the wrapper.
if [ "${ELISA_S0_CACHE:-1}" != 0 ] && [ -z "${ELISA_S0_REAL:-}" ]; then
  export ELISA_S0_REAL="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
  export ELISACORE_BIN="$LDIR/tools/s0cache"
else
  export ELISACORE_BIN="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
fi
