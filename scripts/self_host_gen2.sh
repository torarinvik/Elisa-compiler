#!/usr/bin/env bash
# Attempt gen1 → gen2 product rebuild without stage0.
#
# Requires a seed product binary (scripts/elisac_stage1.sh --seed).
# Compiles src/driver/elisac.elisa with the stage1 product and links gen2.
set -euo pipefail
# Host predicates for products built by a compiler invoked DIRECTLY here (not through the
# wrapper, which exports the same two flags): see register_target_consts.
if [[ "$(uname -s)" == "Linux" ]]; then export ELISA_HOST_LINUX=1; fi
if [[ "$(uname -m)" == "x86_64" ]]; then export ELISA_HOST_X86_64=1; fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/build/self_host_gen2}"
mkdir -p "$OUT_DIR"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LIBDIR="$("$LLVM_CONFIG" --libdir)"

[[ -x "$BIN" ]] || { echo "missing product binary $BIN" >&2; exit 2; }
[[ -f "$RUNTIME_OBJ" ]] || { echo "missing runtime object $RUNTIME_OBJ (run scripts/build_runtime_object.sh)" >&2; exit 2; }
unset ELISACORE_BIN || true
export ELISA_STAGE1_BIN="$BIN"
export PATH="/usr/bin:/bin:/opt/homebrew/bin:/opt/homebrew/opt/llvm/bin:/usr/local/bin${ELISA_LLVM_BIN_DIR:+:$ELISA_LLVM_BIN_DIR}"

DEFAULT_SELF_HOST_GEN2_MAX_RSS_KB=8388608
DEFAULT_SELF_HOST_GEN2_POLL_SECONDS=0.05
SELF_HOST_GEN2_MAX_RSS_KB="${ELISA_SELF_HOST_GEN2_MAX_RSS_KB:-$DEFAULT_SELF_HOST_GEN2_MAX_RSS_KB}"
SELF_HOST_GEN2_POLL_SECONDS="${ELISA_SELF_HOST_GEN2_POLL_SECONDS:-$DEFAULT_SELF_HOST_GEN2_POLL_SECONDS}"

terminate_guarded_pid() {
  local pid="$1" ticks=0
  kill -TERM "$pid" 2>/dev/null || true
  while kill -0 "$pid" 2>/dev/null && [[ "$ticks" -lt 20 ]]; do
    sleep 0.1
    ticks=$((ticks + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
}

run_guarded_stage1() {
  local pid rss peak=0
  bash "$ROOT/scripts/elisac_stage1.sh" -o "$OUT_DIR/elisac_stage1_gen2.o" "$ROOT/src/driver/elisac.elisa" &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    rss="$(ps -o rss= -p "$pid" 2>/dev/null | awk '{print $1}')" || rss=""
    if [[ -n "$rss" && "$rss" -gt "$peak" ]]; then
      peak="$rss"
    fi
    if [[ -n "$rss" && "$rss" -gt "$SELF_HOST_GEN2_MAX_RSS_KB" ]]; then
      echo "self_host_gen2: memory guard stopped pid $pid at ${rss} KB (limit ${SELF_HOST_GEN2_MAX_RSS_KB} KB; peak ${peak} KB)" >&2
      terminate_guarded_pid "$pid"
      return 125
    fi
    sleep "$SELF_HOST_GEN2_POLL_SECONDS"
  done
  wait "$pid"
}

echo "gen1=$BIN"
file "$BIN"
run_guarded_stage1
# -stack_size 512MB (arm64 ld64 max) — same rationale as scripts/elisac_stage1.sh's
# seed_build: emit_expression recurses once per AST level, and this is the product binary.
clang -Wl,-dead_strip -o "$OUT_DIR/elisac-stage1-gen2" "$OUT_DIR/elisac_stage1_gen2.o" "$RUNTIME_OBJ" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" -Wl,-stack_size,0x20000000
echo "wrote $OUT_DIR/elisac-stage1-gen2"
# Fixture parity with gen2
printf 'def main() -> i64:\n    return 42\n' >"$OUT_DIR/fix.elisa"
export ELISA_STAGE1_BIN="$OUT_DIR/elisac-stage1-gen2"
bash "$ROOT/scripts/elisac_stage1.sh" -o "$OUT_DIR/fix.o" "$OUT_DIR/fix.elisa"
clang -Wl,-dead_strip -o "$OUT_DIR/fix" "$OUT_DIR/fix.o" "$RUNTIME_OBJ"
set +e
"$OUT_DIR/fix"
rc=$?
set -e
[[ "$rc" -eq 42 ]] || { echo "gen2 fixture exit $rc want 42" >&2; exit 1; }
echo "self_host_gen2 OK"
