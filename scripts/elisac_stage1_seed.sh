. "$(dirname "${BASH_SOURCE[0]}")/platform.sh"  # host flags/paths: scripts/platform.sh
# The one-time SEED build: compile the stage1 product with the selected bootstrap compiler, under a per-worktree and a
# global lock so two checkouts cannot fight over the same LLVM installation, and with an RSS
# ceiling so a runaway compile is killed with a message rather than by the OS.
#
# Sourced by elisac_stage1.sh, which owns ROOT/BIN and the toolchain variables this reads.

watch_seed_memory() {
  local pid="$1" limit="$2" interval="$3" marker="$4"
  local peak=0 sleeper=""
  trap 'if [[ -n "$sleeper" ]]; then kill "$sleeper" 2>/dev/null || true; wait "$sleeper" 2>/dev/null || true; fi; exit 0' TERM
  while kill -0 "$pid" 2>/dev/null; do
    process_observe "$pid"
    # macOS kill -0 also succeeds for a zombie.
    if [[ -z "$PROCESS_STATE" || "$PROCESS_STATE" == Z* ]]; then
      return
    fi
    if [[ -n "$PROCESS_RSS_KB" && "$PROCESS_RSS_KB" -gt "$peak" ]]; then
      peak="$PROCESS_RSS_KB"
    fi
    if [[ -n "$PROCESS_RSS_KB" && "$PROCESS_RSS_KB" -gt "$limit" ]]; then
      : >"$marker"
      echo "seed: memory guard stopped pid $pid at ${PROCESS_RSS_KB} KB (limit ${limit} KB; peak ${peak} KB)" >&2
      terminate_guarded_pid "$pid"
      return
    fi
    if (( elisa_rss_have_proc && BASH_VERSINFO[0] >= 4 )); then
      process_sleep "$interval"
    else
      sleep "$interval" &
      sleeper=$!
      wait "$sleeper" || return
      sleeper=""
    fi
  done
}

stop_seed_memory_watch() {
  if [[ -n "${ELISA_SEED_RSS_PID:-}" ]]; then
    kill "$ELISA_SEED_RSS_PID" 2>/dev/null || true
    wait "$ELISA_SEED_RSS_PID" 2>/dev/null || true
    ELISA_SEED_RSS_PID=""
  fi
}

seed_build() {
  local libdir seed_lock seed_lock_pid global_seed_lock global_seed_lock_pid seed_max_rss_kb seed_rss_poll_seconds seed_opt_level seed_output seed_object seed_object_output seed_profile_hook_source seed_runtime_obj seed_bootstrap_kind seed_runtime_sha256_expected seed_runtime_sha256_actual seed_retained_server
  local seed_hook_mode
  local -a seed_link_flags seed_link_objects
  # The EXIT trap runs outside this function's local scope. Keep the lock
  # path available to it and create its parent in a fresh checkout.
  mkdir -p "$ROOT/bin" "$ROOT/build"
  ELISA_SEED_LOCK_DIR="$ROOT/build/.elisac-stage1-seed.lock"
  seed_lock="$ELISA_SEED_LOCK_DIR"
  if ! mkdir "$seed_lock" 2>/dev/null; then
    seed_lock_pid=""
    if [[ -f "$seed_lock/pid" ]]; then
      seed_lock_pid="$(<"$seed_lock/pid")"
    fi
    if [[ ! "$seed_lock_pid" =~ ^[1-9][0-9]*$ ]]; then
      echo "seed: lock owner is not yet recorded; refusing to reclaim $seed_lock" >&2
      exit 2
    fi
    if [[ -n "$seed_lock_pid" ]] && kill -0 "$seed_lock_pid" 2>/dev/null; then
      echo "seed: another stage1 seed is already running (pid $seed_lock_pid); refusing a concurrent high-memory build" >&2
      exit 2
    fi
    # Reclaim only the dead owner's private staging directory.
    rm -rf -- "$seed_lock/staging.$seed_lock_pid"
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
  # Worktrees have distinct local locks, but a seed build is a host-wide high-memory
  # operation. Serialize all Elisa self-host seeds on this machine so independent Codex
  # worktrees cannot reproduce the multi-gigabyte contention that previously froze the host.
  # GUI tasks can receive distinct TMPDIR values, which defeats a purportedly
  # host-wide lock and lets independent worktrees start memory-heavy seeds together.
  # Keep the default under the shared system temp root; retain an explicit override
  # for hosts that need a different shared filesystem.
  ELISA_SEED_GLOBAL_LOCK_DIR="${ELISA_STAGE1_GLOBAL_SEED_LOCK_DIR:-/tmp/elisac-stage1-global-seed.lock}"
  global_seed_lock="$ELISA_SEED_GLOBAL_LOCK_DIR"
  if ! mkdir "$global_seed_lock" 2>/dev/null; then
    global_seed_lock_pid=""
    if [[ -f "$global_seed_lock/pid" ]]; then
      global_seed_lock_pid="$(<"$global_seed_lock/pid")"
    fi
    if [[ -z "$global_seed_lock_pid" ]]; then
      rmdir "$seed_lock" 2>/dev/null || true
      echo "seed: global lock owner is not yet recorded; refusing to reclaim $global_seed_lock" >&2
      exit 2
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
  # Keep the output basename stable: on macOS it is embedded in the code
  # signature, so a PID in the basename changes the product on every link.
  # A private directory still permits atomic publication beside the product.
  seed_output=""
  # The bootstrap compiler also writes a large object. Publish that object atomically too:
  # a concurrent stage1 invocation must never observe a truncated object while the guarded
  # seed is still running. Keeping the temporary name private also makes an RSS-guarded
  # termination recoverable without leaving a misleading apparently-valid artifact.
  ELISA_SEED_STAGE_DIR="$seed_lock/staging.$$"
  seed_object="$ELISA_SEED_STAGE_DIR/elisac_stage1.o"
  seed_object_output="${ELISA_STAGE1_OBJECT:-$ROOT/build/elisac_stage1.o}"
  seed_profile_hook_source=""
  ELISA_SEED_OUTPUT=""
  ELISA_SEED_OUTPUT_DIR=""
  ELISA_SEED_RUNTIME_DIR=""
  ELISA_SEED_RECEIPT_PID=""
  ELISA_SEED_PROFILE_HOOK_SOURCE=""
  ELISA_SEED_LLVM_BRIDGE="$ELISA_SEED_STAGE_DIR/llvm_bridge.o"
  finish_seed_freshness_check() {
    local status=0
    if [[ -n "${ELISA_SEED_STAGE0_FRESH_PID:-}" ]]; then
      wait "$ELISA_SEED_STAGE0_FRESH_PID" || status=$?
      ELISA_SEED_STAGE0_FRESH_PID=""
      if [[ -s "$ELISA_SEED_FRESH_OUT" ]]; then cat "$ELISA_SEED_FRESH_OUT"; fi
      if [[ -s "$ELISA_SEED_FRESH_ERR" ]]; then cat "$ELISA_SEED_FRESH_ERR" >&2; fi
    fi
    return "$status"
  }
  cleanup_seed_lock() {
    stop_seed_memory_watch
    finish_seed_freshness_check || true
    if [[ -n "${ELISA_SEED_BRIDGE_PID:-}" ]]; then
      kill "$ELISA_SEED_BRIDGE_PID" 2>/dev/null || true
      wait "$ELISA_SEED_BRIDGE_PID" 2>/dev/null || true
      ELISA_SEED_BRIDGE_PID=""
    fi
    if [[ -n "$ELISA_SEED_RECEIPT_PID" ]]; then
      kill "$ELISA_SEED_RECEIPT_PID" 2>/dev/null || true
      wait "$ELISA_SEED_RECEIPT_PID" 2>/dev/null || true
      ELISA_SEED_RECEIPT_PID=""
    fi
    if [[ -n "${ELISA_SEED_INPUTS_PID:-}" ]]; then
      kill "$ELISA_SEED_INPUTS_PID" 2>/dev/null || true
      wait "$ELISA_SEED_INPUTS_PID" 2>/dev/null || true
      ELISA_SEED_INPUTS_PID=""
    fi
    local file
    local -a files=("$ELISA_SEED_LOCK_DIR/pid") directories=("$ELISA_SEED_LOCK_DIR")
    for file in "${ELISA_SEED_OUTPUT:-}" "${ELISA_SEED_PROFILE_HOOK_SOURCE:-}"; do
      if [[ -n "$file" ]]; then files+=("$file"); fi
    done
    if [[ -n "$ELISA_SEED_RUNTIME_DIR" ]]; then
      files+=("$ELISA_SEED_RUNTIME_DIR"/runtime.o*)
      directories+=("$ELISA_SEED_RUNTIME_DIR")
    fi
    if [[ -n "${ELISA_SEED_OUTPUT_DIR:-}" ]]; then
      files+=("$ELISA_SEED_OUTPUT_DIR"/*.provenance.json*)
      directories+=("$ELISA_SEED_OUTPUT_DIR")
    fi
    if [[ -n "${ELISA_SEED_GLOBAL_LOCK_DIR:-}" ]]; then
      files+=("$ELISA_SEED_GLOBAL_LOCK_DIR/pid")
      directories+=("$ELISA_SEED_GLOBAL_LOCK_DIR")
    fi
    rm -rf -- "$ELISA_SEED_STAGE_DIR"
    rm -f -- "${files[@]}"
    rmdir -- "${directories[@]}" 2>/dev/null || true
  }
  trap cleanup_seed_lock EXIT INT TERM HUP
  mkdir "$ELISA_SEED_STAGE_DIR"
  ELISA_SEED_INPUTS_FILE="$ELISA_SEED_STAGE_DIR/inputs.json"
  elisa_stage1_provenance inputs "$ROOT" > "$ELISA_SEED_INPUTS_FILE" &
  ELISA_SEED_INPUTS_PID=$!
  ELISA_SEED_FRESH_OUT="$ELISA_SEED_STAGE_DIR/fresh.stdout"
  ELISA_SEED_FRESH_ERR="$ELISA_SEED_STAGE_DIR/fresh.stderr"
  bash "$ROOT/scripts/assert_stage0_fresh.sh" "$BOOTSTRAP_BIN" >"$ELISA_SEED_FRESH_OUT" 2>"$ELISA_SEED_FRESH_ERR" &
  ELISA_SEED_STAGE0_FRESH_PID=$!
  if [[ ! -x "$BOOTSTRAP_BIN" ]]; then
    echo "seed requires an executable bootstrap compiler at ELISACORE_BIN=$BOOTSTRAP_BIN" >&2
    exit 2
  fi
  # The bootstrap compiler discharges the compiler's own contracts with an external z3. Without one on PATH
  # it does not say so: it reports the std's min/max/clamp ensures as unprovable and fails
  # minutes into the seed. Refuse up front with the actual cause.
  if ! command -v z3 >/dev/null 2>&1; then
    echo "seed: no z3 on PATH; bootstrap compiler $BOOTSTRAP_BIN needs an SMT solver to prove the compiler's contracts (install z3 >= 5, e.g. \`pip install z3-solver\`)" >&2
    exit 2
  fi
  seed_bootstrap_kind="${ELISA_STAGE1_SEED_BOOTSTRAP_KIND:-}"
  if [[ -z "$seed_bootstrap_kind" ]]; then
    seed_bootstrap_kind="$(elisa_stage1_provenance bootstrap-kind "$BOOTSTRAP_BIN")"
  fi
  case "$seed_bootstrap_kind" in
    stage0|stage1) ;;
    *) echo "seed: invalid bootstrap compiler kind: $seed_bootstrap_kind" >&2; exit 2 ;;
  esac
  # A Stage1 bootstrap may be built from compiler sources that import helpers from
  # native_runtime_support. The caller supplies a matching, SHA-256-pinned runtime
  # for this one link; the new product still rebuilds its runtime below.
  seed_link_objects=("$seed_object")
  seed_runtime_obj="${ELISA_STAGE1_SEED_RUNTIME_OBJ:-}"
  seed_runtime_sha256_expected="${ELISA_STAGE1_SEED_RUNTIME_SHA256:-}"
  if [[ -n "$seed_runtime_obj" ]]; then
    [[ "$seed_bootstrap_kind" == stage1 ]] || {
      echo "seed: a bootstrap runtime object is only valid with an elisac-stage1 bootstrap" >&2
      exit 2
    }
    [[ -s "$seed_runtime_obj" ]] || {
      echo "seed: requested bootstrap runtime object is missing or empty: $seed_runtime_obj" >&2
      exit 2
    }
    [[ -s "$seed_runtime_obj.inputs.sha256" ]] || {
      echo "seed: requested bootstrap runtime has no freshness stamp: $seed_runtime_obj" >&2
      exit 2
    }
    [[ "${#seed_runtime_sha256_expected}" -eq 64 ]] || {
      echo "seed: ELISA_STAGE1_SEED_RUNTIME_SHA256 must pin the bootstrap runtime object's SHA-256" >&2
      exit 2
    }
    case "$seed_runtime_sha256_expected" in
      *[!0-9a-f]*)
        echo "seed: bootstrap runtime SHA-256 must be lowercase hexadecimal" >&2
        exit 2
        ;;
    esac
    seed_runtime_sha256_actual="$(elisa_sha256 "$seed_runtime_obj" | awk '{print $1}')"
    [[ "$seed_runtime_sha256_actual" == "$seed_runtime_sha256_expected" ]] || {
      echo "seed: bootstrap runtime SHA-256 mismatch for $seed_runtime_obj" >&2
      exit 2
    }
    echo "seed: linking bootstrap runtime $seed_runtime_obj" >&2
    seed_link_objects+=("$seed_runtime_obj")
  elif [[ -n "$seed_runtime_sha256_expected" ]]; then
    echo "seed: bootstrap runtime SHA-256 supplied without an object path" >&2
    exit 2
  fi
  # A filename is not compiler provenance: copied products may be renamed.
  # Identify the exact executable without guessing its implementation stage.
  echo "seed: building Stage1 product with $seed_bootstrap_kind bootstrap compiler $BOOTSTRAP_BIN" >&2
  # The compiler itself is a large input. A duplicated seed can consume the whole
  # workstation before either invocation reports an error, so bound one seed by default.
  # The 5.5 GiB freeze came from two worktrees seeding at once; the host-wide global seed lock
  # above now serializes seeds, so one seed may use more. The compiler outgrew 4 GiB: seeds of
  # main (2026-10-03) peak near it and were killed by the guard at 420 s. It then outgrew 6 GiB:
  # seeds of main (2026-11-01) were stopped at 6.07 GiB and, in a resumed analysis pass, at
  # 8.0 GiB, and complete under 10 GiB. 12 GiB leaves a single serialized seed headroom; raise
  # ELISA_STAGE1_SEED_MAX_RSS_KB further on large hosts.
  seed_max_rss_kb="${ELISA_STAGE1_SEED_MAX_RSS_KB:-12582912}"
  seed_rss_poll_seconds="${ELISA_STAGE1_RSS_POLL_SECONDS:-0.05}"
  seed_opt_level="${ELISA_STAGE1_SEED_OPT_LEVEL:--O3}"
  case "$seed_opt_level" in
    -O0|-O1|-O2|-O3) ;;
    *)
      echo "seed: ELISA_STAGE1_SEED_OPT_LEVEL must be -O0, -O1, -O2 or -O3 (got $seed_opt_level)" >&2
      exit 2
      ;;
  esac
  # Reuse proven (unsat) SMT verdicts across seeds. The cache is keyed by the exact query text,
  # the bootstrap compiler and solver binaries, and the solver options, so it only skips
  # re-proving identical obligations. Set ELISACORE_SMT_CACHE_DIR= (empty) to disable.
  # Declined verdicts (sat/unknown) are reused too: they never prove anything, and identical
  # queries already flip between declined verdicts run to run. ELISACORE_SMT_CACHE_DECLINED=0
  # re-runs them.
  seed_smt_cache_dir="${ELISACORE_SMT_CACHE_DIR-${XDG_CACHE_HOME:-$HOME/.cache}/elisac-smt-proofs}"
  seed_smt_cache_declined="${ELISACORE_SMT_CACHE_DECLINED-1}"
  # A running scripts/elisac_retained_server.sh re-checks body-only edits in seconds;
  # set ELISACORE_RETAINED_SERVER= (empty) to always compile locally.
  # Only this compile uses it, so other bootstrap invocations never replace the
  # analysis the server keeps.
  seed_retained_server="${ELISACORE_RETAINED_SERVER-}"
  if [[ -z "${ELISACORE_RETAINED_SERVER+x}" && -S "$HOME/.elisac/retained.sock" ]]; then
    seed_retained_server="$HOME/.elisac/retained.sock"
  fi
  # With the server, code generation uses the incrementally updated analysis
  # instead of re-analyzing a clean edit from scratch (its IR matched a fresh
  # analysis byte for byte on this tree); ELISACORE_RETAINED_SPLICED_CODEGEN=0
  # restores the fresh analysis.
  seed_spliced_codegen="${ELISACORE_RETAINED_SPLICED_CODEGEN-1}"
  # Optimize each object partition separately and cache it by its exact unoptimized
  # bitcode, so a code edit re-optimizes only the partitions it touches (70 s -> 18 s
  # for a one-line body edit). Each partition imports available_externally copies of
  # foreign functions of at most ELISACORE_PARALLEL_OPT_IMPORT instructions, so
  # inlining still crosses partitions: the compiler runs as fast as with whole-module
  # O3 (without imports it was ~36% slower). ELISACORE_PARALLEL_OPT=0 restores
  # whole-module O3.
  seed_parallel_opt="${ELISACORE_PARALLEL_OPT-1}"
  # Generate the IR partitions concurrently, one generator per partition, instead of
  # lowering the whole module serially and splitting it (IR 5.5 s -> 2.5 s wall for a
  # one-line body edit; same check output and runtime speed). Each generator imports
  # small foreign callees itself; a declined partition falls back to the module split
  # above. ELISACORE_PARALLEL_IR=0 restores serial whole-module lowering.
  seed_parallel_ir="${ELISACORE_PARALLEL_IR-1}"
  seed_parallel_opt_import="${ELISACORE_PARALLEL_OPT_IMPORT-100}"
  # Prepare the independently keyed LLVM bridge while the bootstrap compiler runs.
  # The result is joined before linking, and cleanup kills it on every early exit.
  bash "$ROOT/scripts/build_stage1_llvm_bridge.sh" "$ELISA_SEED_LLVM_BRIDGE" &
  ELISA_SEED_BRIDGE_PID=$!
  # Stage1 includes its own standard-library copy; authorize only that exact file. The
  # bootstrap loader still requires it to appear in the expanded include set.
  ELISACORE_RETAINED_SPLICED_CODEGEN="$seed_spliced_codegen" \
  ELISACORE_PARALLEL_OPT="$seed_parallel_opt" \
  ELISACORE_PARALLEL_IR="$seed_parallel_ir" \
  ELISACORE_PARALLEL_OPT_IMPORT="$seed_parallel_opt_import" \
  ELISACORE_SMT_CACHE_DIR="$seed_smt_cache_dir" \
  ELISACORE_SMT_CACHE_DECLINED="$seed_smt_cache_declined" \
  ELISACORE_RETAINED_SERVER="$seed_retained_server" \
  ELISACORE_TRUSTED_RUNTIME_SOURCE="$ROOT/elisacore_std/elisacore_runtime_concurrency.elisa" \
    "$BOOTSTRAP_BIN" -emit obj "$seed_opt_level" -o "$seed_object" "$ROOT/src/driver/elisac.elisa" &
  seed_pid=$!
  echo "seed: bootstrap compiler SHA-256 $(elisa_sha256 "$BOOTSTRAP_BIN" | awk '{print $1}')" >&2
  local seed_rss_limit_marker="$ELISA_SEED_STAGE_DIR/rss-limit"
  watch_seed_memory "$seed_pid" "$seed_max_rss_kb" "$seed_rss_poll_seconds" "$seed_rss_limit_marker" &
  ELISA_SEED_RSS_PID=$!
  # Wait for the bootstrap directly. In particular, do not charge the last
  # RSS polling interval to a child that has already saved its checkpoint.
  seed_status=0
  wait "$seed_pid" || seed_status=$?
  stop_seed_memory_watch
  if [[ -e "$seed_rss_limit_marker" ]]; then
    exit 125
  fi
  if [[ "$seed_status" -ne 0 ]]; then
    if [[ "$seed_status" -gt 128 ]]; then
      echo "seed: $seed_bootstrap_kind bootstrap compiler $BOOTSTRAP_BIN terminated with status $seed_status (signal $((seed_status - 128)))" >&2
    else
      echo "seed: $seed_bootstrap_kind bootstrap compiler $BOOTSTRAP_BIN failed with status $seed_status" >&2
    fi
    exit "$seed_status"
  fi
  if [[ -n "${ELISA_SEED_STAGE0_FRESH_PID:-}" ]]; then
    if ! finish_seed_freshness_check; then
      echo "seed: refusing to link a product built by a stale or unverifiable Stage0" >&2
      exit 2
    fi
  fi
  # Sources were read by the bootstrap compiler above; verify they did not change
  # meanwhile while the product links, and join before publishing it.
  if [[ -n "${ELISA_SEED_INPUTS_PID:-}" ]]; then
    if ! wait "$ELISA_SEED_INPUTS_PID"; then
      echo "seed: could not fingerprint the Stage1 inputs" >&2
      exit 2
    fi
    ELISA_SEED_INPUTS_PID=""
    ELISA_STAGE1_SEED_INPUTS="$(cat "$ELISA_SEED_INPUTS_FILE")"
  fi
  local seed_inputs_check_pid=""
  if [[ -n "${ELISA_STAGE1_SEED_INPUTS:-}" ]]; then
    elisa_stage1_provenance check-inputs "$ROOT" "$ELISA_STAGE1_SEED_INPUTS" ${ELISA_STAGE1_SEED_WRITES:+"$ELISA_STAGE1_SEED_WRITES"} &
    seed_inputs_check_pid=$!
  fi
  ELISA_SEED_OUTPUT_DIR="$(mktemp -d "${BIN}.tmp.XXXXXXXX")"
  seed_output="$ELISA_SEED_OUTPUT_DIR/$(basename "$BIN")"
  ELISA_SEED_OUTPUT="$seed_output"
  # ELF symbol tables retain the C source basename. A PID in that name makes
  # an otherwise identical executable miss the runtime's compiler digest.
  seed_profile_hook_source="$ELISA_SEED_OUTPUT_DIR/elisac_stage1_profile_hooks.c"
  ELISA_SEED_PROFILE_HOOK_SOURCE="$seed_profile_hook_source"
  # -stack_size: a deeply left-nested expression (adversarial input, see
  # malformed_input_fuzz.py / the depth guard in codegen_scope.elisa's expression_type)
  # recurses once per AST level through emit_expression. 0x20000000 (512MB) is the max
  # ld64 allows on arm64 and gives the compiler's own main thread far more headroom than
  # the default ~8MB before a pathological input can overflow the native stack.
  [[ -x "$ELISA_CLANG_TOOL" ]] || {
    echo "seed requires clang compatible with LLVM_CONFIG=$LLVM_CONFIG (set ELISA_CLANG)" >&2
    exit 2
  }
  # The compiler source includes the complete standard runtime. Optional native
  # callback and varargs entry points are unreachable from the compiler itself.
  # Darwin removes them with dead_strip; Linux uses weak host-callback fallbacks
  # because GNU --gc-sections does not discard every reference from this object.
  case "$(uname -s)" in
    Linux)
      seed_link_flags=(-no-pie -Wl,--gc-sections)
      seed_hook_mode=--host-callbacks
      ;;
    Darwin)
      seed_link_flags=(-Wl,-dead_strip -Wl,-stack_size,0x20000000 -Wl,-search_paths_first)
      seed_hook_mode=""
      ;;
    *)
      echo "seed: unsupported host for native product linking: $(uname -s) (supported: Linux, Darwin)" >&2
      exit 2
  esac
  if [[ -n "${ELISA_STAGE1_SEED_LINKER:-}" ]]; then
    [[ -x "$ELISA_STAGE1_SEED_LINKER" ]] || {
      echo "seed: selected linker is not executable: $ELISA_STAGE1_SEED_LINKER" >&2
      exit 2
    }
    seed_link_flags+=("--ld-path=$ELISA_STAGE1_SEED_LINKER")
  fi
  # Use the shared weak fallback source so seed, runtime, and test products keep
  # one definition of the optional profiler/native callback ABI.
  if [[ -n "$seed_hook_mode" ]]; then
    bash "$ROOT/scripts/write_profiler_hook_fallbacks.sh" "$seed_hook_mode" >"$seed_profile_hook_source"
  else
    bash "$ROOT/scripts/write_profiler_hook_fallbacks.sh" >"$seed_profile_hook_source"
  fi
  local seed_llvm_bridge="$ELISA_SEED_LLVM_BRIDGE"
  if ! wait "$ELISA_SEED_BRIDGE_PID"; then
    ELISA_SEED_BRIDGE_PID=""
    echo "seed: LLVM bridge build failed" >&2
    exit 2
  fi
  ELISA_SEED_BRIDGE_PID=""
  seed_link_objects+=("$seed_llvm_bridge")
  local seed_cxx_lib=-lc++
  [[ "$(uname -s)" == Linux ]] && seed_cxx_lib=-lstdc++
  libdir="$("$LLVM_CONFIG" --libdir)"
  "$ELISA_CLANG_TOOL" -fno-builtin "${seed_link_flags[@]}" -o "$seed_output" "${seed_link_objects[@]}" "$seed_profile_hook_source" -L"$libdir" $ELISA_LLVM_LIBS "$seed_cxx_lib" $ELISA_LINK_EXE_FLAGS -Wl,-rpath,"$libdir"
  rm -f "$seed_llvm_bridge"
  if [[ -n "$seed_runtime_obj" ]]; then
    seed_runtime_sha256_actual="$(elisa_sha256 "$seed_runtime_obj" | awk '{print $1}')"
    [[ "$seed_runtime_sha256_actual" == "$seed_runtime_sha256_expected" ]] || {
      echo "seed: bootstrap runtime changed during link; refusing to publish $seed_output" >&2
      exit 2
    }
  fi
  if [[ -n "$seed_inputs_check_pid" ]] && ! wait "$seed_inputs_check_pid"; then
    echo "seed: refusing to publish a product built while its source inputs were changing" >&2
    exit 2
  fi
  # Prepare the receipt and the matching runtime before making the new compiler
  # visible. A failed or timed-out runtime build leaves the installed set usable.
  elisa_stage1_provenance record-verified "$ROOT" "$seed_output" "$ELISA_STAGE1_SEED_INPUTS" &
  ELISA_SEED_RECEIPT_PID=$!
  local runtime_out="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
  mkdir -p "$(dirname "$runtime_out")"
  ELISA_SEED_RUNTIME_DIR="$(mktemp -d "$runtime_out.seed.XXXXXXXX")"
  local runtime_stage="$ELISA_SEED_RUNTIME_DIR/runtime.o"
  if [[ -s "$runtime_out" && -f "$runtime_out.inputs.sha256" ]]; then
    cp -p "$runtime_out" "$runtime_stage"
    cp -p "$runtime_out.inputs.sha256" "$runtime_stage.inputs.sha256"
  fi
  ELISA_STAGE1_BIN="$seed_output" ELISA_RUNTIME_PRODUCT_IDENTITY_PATH="$BIN" \
    ELISA_RUNTIME_OBJ="$runtime_stage" bash "$ROOT/scripts/build_runtime_object.sh"
  wait "$ELISA_SEED_RECEIPT_PID"
  ELISA_SEED_RECEIPT_PID=""

  mv -f "$seed_object" "$seed_object_output"
  mv -f "$runtime_stage" "$runtime_out"
  mv -f "$runtime_stage.inputs.sha256" "$runtime_out.inputs.sha256"
  mv -f "$seed_output.provenance.json" "$BIN.provenance.json"
  mv -f "$seed_output" "$BIN"
  ELISA_SEED_OUTPUT=""
  rm -f "$seed_profile_hook_source"
  ELISA_SEED_PROFILE_HOOK_SOURCE=""
  echo "seed: wrote $BIN and $runtime_out" >&2
}
