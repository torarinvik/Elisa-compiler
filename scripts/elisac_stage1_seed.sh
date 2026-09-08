# The one-time SEED build: compile the stage1 product with stage0, under a per-worktree and a
# global lock so two checkouts cannot fight over the same LLVM installation, and with an RSS
# ceiling so a runaway compile is killed with a message rather than by the OS.
#
# Sourced by elisac_stage1.sh, which owns ROOT/BIN and the toolchain variables this reads.

seed_build() {
  local libdir seed_lock seed_lock_pid global_seed_lock global_seed_lock_pid seed_max_rss_kb seed_rss_poll_seconds seed_opt_level seed_output seed_object seed_profile_hook_source
  # A newly-created Git worktree has no ignored build directory yet. Create the
  # local output roots before taking the per-worktree lock; otherwise `mkdir`
  # cannot create the nested lock path and every first seed fails as if a stale
  # lock were present.
  mkdir -p "$ROOT/bin" "$ROOT/build"
  # The EXIT trap runs after this function's locals have gone out of scope under
  # `set -u`; retain the private lock path in a function-external variable so a
  # successful high-memory seed always releases its lock without an unbound-var exit.
  # Create the lock's parent before taking the lock. A fresh checkout has no build/
  # directory yet; treating a failed mkdir as a stale lock there makes the very first
  # seed fail before it can create its own build outputs.
  mkdir -p "$ROOT/bin" "$ROOT/build"
  ELISA_SEED_LOCK_DIR="$ROOT/build/.elisac-stage1-seed.lock"
  seed_lock="$ELISA_SEED_LOCK_DIR"
  if ! mkdir "$seed_lock" 2>/dev/null; then
    seed_lock_pid=""
    if [[ -f "$seed_lock/pid" ]]; then
      seed_lock_pid="$(<"$seed_lock/pid")"
    fi
    if [[ -n "$seed_lock_pid" ]] && kill -0 "$seed_lock_pid" 2>/dev/null; then
      echo "seed: another stage1 seed is already running (pid $seed_lock_pid); refusing a concurrent high-memory build" >&2
      exit 2
    fi
    # A killed shell may leave only its lock directory behind. Reclaim it only when
    # the recorded owner is no longer alive; the target is this private lock directory.
    rm -f "$seed_lock/pid"
    rmdir "$seed_lock" 2>/dev/null || {
      echo "seed: could not acquire stale lock $seed_lock" >&2
      exit 2
    }
    mkdir "$seed_lock" || {
      echo "seed: could not acquire lock $seed_lock" >&2
      exit 2
    }
  fi
  # Worktrees have distinct local locks, but a stage0 seed is a host-wide high-memory
  # operation. Serialize all Elisa self-host seeds on this machine so independent Codex
  # worktrees cannot reproduce the multi-gigabyte contention that previously froze the host.
  ELISA_SEED_GLOBAL_LOCK_DIR="${ELISA_STAGE1_GLOBAL_SEED_LOCK_DIR:-${TMPDIR:-/tmp}/elisac-stage1-global-seed.lock}"
  global_seed_lock="$ELISA_SEED_GLOBAL_LOCK_DIR"
  if ! mkdir "$global_seed_lock" 2>/dev/null; then
    global_seed_lock_pid=""
    if [[ -f "$global_seed_lock/pid" ]]; then
      global_seed_lock_pid="$(<"$global_seed_lock/pid")"
    fi
    if [[ -n "$global_seed_lock_pid" ]] && kill -0 "$global_seed_lock_pid" 2>/dev/null; then
      rm -f "$seed_lock/pid"
      rmdir "$seed_lock" 2>/dev/null || true
      echo "seed: another Elisa self-host seed is already running on this host (pid $global_seed_lock_pid); refusing concurrent high-memory build" >&2
      exit 2
    fi
    rm -f "$global_seed_lock/pid"
    rmdir "$global_seed_lock" 2>/dev/null || {
      rm -f "$seed_lock/pid"
      rmdir "$seed_lock" 2>/dev/null || true
      echo "seed: could not acquire stale global lock $global_seed_lock" >&2
      exit 2
    }
    mkdir "$global_seed_lock" || {
      rm -f "$seed_lock/pid"
      rmdir "$seed_lock" 2>/dev/null || true
      echo "seed: could not acquire global lock $global_seed_lock" >&2
      exit 2
    }
  fi
  printf '%s\n' "$$" >"$seed_lock/pid"
  printf '%s\n' "$$" >"$global_seed_lock/pid"
  # Never link directly over the product binary. Readers may be compiling through the wrapper
  # while another session refreshes the seed; an in-place clang output can expose a truncated
  # executable or make two adjacent parity probes use different compiler generations. Link next
  # to the final path and publish it with one same-filesystem rename after the complete image is
  # ready.
  seed_output="${BIN}.tmp.$$"
  # The stage0 compiler also writes a large object. Publish that object atomically too:
  # a concurrent stage1 invocation must never observe a truncated object while the guarded
  # seed is still running. Keeping the temporary name private also makes an RSS-guarded
  # termination recoverable without leaving a misleading apparently-valid artifact.
  seed_object="$ROOT/build/elisac_stage1.o.tmp.$$"
  seed_profile_hook_source="$ROOT/build/elisac_stage1_profile_hooks.tmp.$$.c"
  ELISA_SEED_OUTPUT="$seed_output"
  ELISA_SEED_OBJECT="$seed_object"
  ELISA_SEED_PROFILE_HOOK_SOURCE="$seed_profile_hook_source"
  cleanup_seed_lock() {
    if [[ -n "${ELISA_SEED_OUTPUT:-}" ]]; then
      rm -f "$ELISA_SEED_OUTPUT"
    fi
    if [[ -n "${ELISA_SEED_OBJECT:-}" ]]; then
      rm -f "$ELISA_SEED_OBJECT"
    fi
    if [[ -n "${ELISA_SEED_PROFILE_HOOK_SOURCE:-}" ]]; then
      rm -f "$ELISA_SEED_PROFILE_HOOK_SOURCE"
    fi
    rm -f "$ELISA_SEED_LOCK_DIR/pid"
    rmdir "$ELISA_SEED_LOCK_DIR" 2>/dev/null || true
    if [[ -n "${ELISA_SEED_GLOBAL_LOCK_DIR:-}" ]]; then
      rm -f "$ELISA_SEED_GLOBAL_LOCK_DIR/pid"
      rmdir "$ELISA_SEED_GLOBAL_LOCK_DIR" 2>/dev/null || true
    fi
  }
  trap cleanup_seed_lock EXIT INT TERM HUP
  libdir="$("$LLVM_CONFIG" --libdir)"
  if [[ ! -x "$STAGE0_BIN" ]]; then
    echo "seed requires stage0 elisac at ELISACORE_BIN=$STAGE0_BIN" >&2
    exit 2
  fi
  echo "seed: building product with stage0 $STAGE0_BIN" >&2
  # The compiler itself is a large input. A duplicated seed can consume the whole
  # workstation before either invocation reports an error, so bound one seed by default.
  # Keep one-shot seed builds below the same 4 GiB operational ceiling used by ordinary
  # stage1 invocations. The compiler is large, but allowing the default seed to claim 5.5 GiB
  # made two independent worktrees capable of freezing a developer machine at the same time;
  # raise ELISA_STAGE1_SEED_MAX_RSS_KB deliberately on a host sized for a larger build.
  seed_max_rss_kb="${ELISA_STAGE1_SEED_MAX_RSS_KB:-4194304}"
  seed_rss_poll_seconds="${ELISA_STAGE1_RSS_POLL_SECONDS:-0.05}"
  seed_opt_level="${ELISA_STAGE1_SEED_OPT_LEVEL:--O2}"
  case "$seed_opt_level" in
    -O0|-O1|-O2|-O3) ;;
    *)
      echo "seed: ELISA_STAGE1_SEED_OPT_LEVEL must be -O0, -O1, -O2 or -O3 (got $seed_opt_level)" >&2
      exit 2
      ;;
  esac
  "$STAGE0_BIN" -emit obj "$seed_opt_level" -o "$seed_object" "$ROOT/src/driver/elisac.elisa" &
  seed_pid=$!
  seed_peak_rss_kb=0
  while kill -0 "$seed_pid" 2>/dev/null; do
    # The child may exit between kill(0) and ps(1). With `set -euo pipefail`, the
    # resulting non-zero ps status used to abort the seed shell before `wait` could
    # collect the child's successful status, making a completed seed look failed.
    seed_rss_kb="$(ps -o rss= -p "$seed_pid" 2>/dev/null | awk '{print $1}')" || seed_rss_kb=""
    if [[ -n "$seed_rss_kb" && "$seed_rss_kb" -gt "$seed_peak_rss_kb" ]]; then
      seed_peak_rss_kb="$seed_rss_kb"
    fi
    if [[ -n "$seed_rss_kb" && "$seed_rss_kb" -gt "$seed_max_rss_kb" ]]; then
      echo "seed: memory guard stopped pid $seed_pid at ${seed_rss_kb} KB (limit ${seed_max_rss_kb} KB; peak ${seed_peak_rss_kb} KB)" >&2
      terminate_guarded_pid "$seed_pid"
      exit 125
    fi
    sleep "$seed_rss_poll_seconds"
  done
  # Collect the child status explicitly instead of letting `set -e` terminate the
  # wrapper before it can explain why the seed failed. A host kill (for example,
  # SIGKILL from memory pressure or an external process supervisor) otherwise
  # leaves only a silent status-1 wrapper failure and no actionable evidence in
  # the seed log.
  set +e
  wait "$seed_pid"
  seed_status=$?
  set -e
  if [[ "$seed_status" -ne 0 ]]; then
    if [[ "$seed_status" -gt 128 ]]; then
      echo "seed: stage0 compiler terminated with status $seed_status (signal $((seed_status - 128)))" >&2
    else
      echo "seed: stage0 compiler failed with status $seed_status" >&2
    fi
    exit "$seed_status"
  fi
  # -stack_size: a deeply left-nested expression (adversarial input, see
  # malformed_input_fuzz.py / the depth guard in codegen_scope.elisa's expression_type)
  # recurses once per AST level through emit_expression. 0x20000000 (512MB) is the max
  # ld64 allows on arm64 and gives the compiler's own main thread far more headroom than
  # the default ~8MB before a pathological input can overflow the native stack.
  [[ -x "$ELISA_CLANG_TOOL" ]] || {
    echo "seed requires clang compatible with LLVM_CONFIG=$LLVM_CONFIG (set ELISA_CLANG)" >&2
    exit 2
  }
  # The compiler source includes the complete standard runtime.  Its optional
  # native-callback and varargs entry points are deliberately unreachable from
  # the compiler itself and are provided only when linking an executable/runtime
  # consumer.  Dead-strip those sections here, matching the other self-host
  # product links, instead of requiring unrelated host runtime symbols.
  printf '%s\n' \
    '#include <stddef.h>' \
    '#include <stdint.h>' \
    '#if defined(__GNUC__) || defined(__clang__)' \
    '#define ELISA_WEAK __attribute__((weak))' \
    '#else' \
    '#define ELISA_WEAK' \
    '#endif' \
    'ELISA_WEAK uint32_t elisa_profile_allocation_negotiate(uint32_t version) { (void)version; return 0; }' \
    'ELISA_WEAK uint32_t elisa_profile_region_layout_negotiate(uint32_t version) { (void)version; return 0; }' \
    'ELISA_WEAK void elisa_profile_region_layout_v1(uintptr_t arena, size_t region, uintptr_t header, uintptr_t data, size_t capacity) { (void)arena; (void)region; (void)header; (void)data; (void)capacity; }' \
    'ELISA_WEAK void elisa_profile_allocation_event_v1(uint32_t kind, uintptr_t address, size_t size, uintptr_t old_address, size_t old_size, uintptr_t arena, size_t region) {' \
    '  (void)kind; (void)address; (void)size; (void)old_address; (void)old_size; (void)arena; (void)region;' \
    '}' >"$seed_profile_hook_source"
  "$ELISA_CLANG_TOOL" -Wl,-dead_strip -o "$seed_output" "$seed_object" "$seed_profile_hook_source" -L"$libdir" -lLLVM -Wl,-rpath,"$libdir" -Wl,-stack_size,0x20000000
  mv -f "$seed_output" "$BIN"
  mv -f "$seed_object" "$ROOT/build/elisac_stage1.o"
  ELISA_SEED_OUTPUT=""
  ELISA_SEED_PROFILE_HOOK_SOURCE=""
  echo "seed: wrote $BIN" >&2
}
