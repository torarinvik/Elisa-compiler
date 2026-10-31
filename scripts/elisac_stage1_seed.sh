. "$(dirname "${BASH_SOURCE[0]}")/platform.sh"  # host flags/paths: scripts/platform.sh
# The one-time SEED build: compile the stage1 product with the selected bootstrap compiler, under a per-worktree and a
# global lock so two checkouts cannot fight over the same LLVM installation, and with an RSS
# ceiling so a runaway compile is killed with a message rather than by the OS.
#
# Sourced by elisac_stage1.sh, which owns ROOT/BIN and the toolchain variables this reads.

seed_build() {
  local libdir seed_lock seed_lock_pid global_seed_lock global_seed_lock_pid seed_max_rss_kb seed_rss_poll_seconds seed_opt_level seed_output seed_object seed_object_output seed_profile_hook_source seed_runtime_obj seed_bootstrap_kind seed_runtime_sha256_expected seed_runtime_sha256_actual seed_retained_server
  local seed_hook_mode
  local -a seed_link_flags seed_link_objects
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
    if [[ -z "$seed_lock_pid" ]]; then
      echo "seed: lock owner is not yet recorded; refusing to reclaim $seed_lock" >&2
      exit 2
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
  seed_object="$ROOT/build/elisac_stage1.o.tmp.$$"
  seed_object_output="${ELISA_STAGE1_OBJECT:-$ROOT/build/elisac_stage1.o}"
  seed_profile_hook_source=""
  ELISA_SEED_OUTPUT=""
  ELISA_SEED_OUTPUT_DIR=""
  ELISA_SEED_OBJECT="$seed_object"
  ELISA_SEED_PROFILE_HOOK_SOURCE=""
  ELISA_SEED_LLVM_BRIDGE="$ROOT/build/elisac_stage1_llvm_bridge.tmp.$$.o"
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
    if [[ -n "${ELISA_SEED_OUTPUT_DIR:-}" ]]; then
      rmdir "$ELISA_SEED_OUTPUT_DIR" 2>/dev/null || true
    fi
    [[ -z "${ELISA_SEED_LLVM_BRIDGE:-}" ]] || rm -f "$ELISA_SEED_LLVM_BRIDGE"
    rm -f "$ELISA_SEED_LOCK_DIR/pid"
    rmdir "$ELISA_SEED_LOCK_DIR" 2>/dev/null || true
    if [[ -n "${ELISA_SEED_GLOBAL_LOCK_DIR:-}" ]]; then
      rm -f "$ELISA_SEED_GLOBAL_LOCK_DIR/pid"
      rmdir "$ELISA_SEED_GLOBAL_LOCK_DIR" 2>/dev/null || true
    fi
  }
  trap cleanup_seed_lock EXIT INT TERM HUP
  ELISA_SEED_OUTPUT_DIR="$(mktemp -d "${BIN}.tmp.XXXXXXXX")"
  seed_output="$ELISA_SEED_OUTPUT_DIR/$(basename "$BIN")"
  ELISA_SEED_OUTPUT="$seed_output"
  # ELF symbol tables retain the C source basename. A PID in that name makes
  # an otherwise identical executable miss the runtime's compiler digest.
  seed_profile_hook_source="$ELISA_SEED_OUTPUT_DIR/elisac_stage1_profile_hooks.c"
  ELISA_SEED_PROFILE_HOOK_SOURCE="$seed_profile_hook_source"
  libdir="$("$LLVM_CONFIG" --libdir)"
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
    seed_bootstrap_kind="$("${PYTHON_HOST:-python3}" "$ROOT/scripts/stage1_provenance.py" bootstrap-kind "$BOOTSTRAP_BIN")"
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
  echo "seed: bootstrap compiler SHA-256 $(elisa_sha256 "$BOOTSTRAP_BIN" | awk '{print $1}')" >&2
  # The compiler itself is a large input. A duplicated seed can consume the whole
  # workstation before either invocation reports an error, so bound one seed by default.
  # The 5.5 GiB freeze came from two worktrees seeding at once; the host-wide global seed lock
  # above now serializes seeds, so one seed may use more. The compiler outgrew 4 GiB: seeds of
  # main (2026-10-03) peak near it and were killed by the guard at 420 s. 6 GiB leaves a single
  # serialized seed headroom; raise ELISA_STAGE1_SEED_MAX_RSS_KB further on large hosts.
  seed_max_rss_kb="${ELISA_STAGE1_SEED_MAX_RSS_KB:-6291456}"
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
  seed_peak_rss_kb=0
  while kill -0 "$seed_pid" 2>/dev/null; do
    # `kill -0` also succeeds for a zombie on macOS. A completed bootstrap child
    # can therefore leave this loop spinning forever instead of reaching the
    # explicit `wait` below. Treat an absent or zombie process as terminal;
    # `wait` still collects the authoritative exit status.
    # The child may exit between kill(0) and the observation. With `set -euo pipefail`, a
    # failing ps(1) used to abort the seed shell before `wait` could collect the child's
    # successful status, making a completed seed look failed; process_observe (fork-free
    # on Linux, see scripts/process_rss.sh) reports a vanished child as empty instead.
    process_observe "$seed_pid"
    seed_process_stat="$PROCESS_STATE"
    if [[ -z "$seed_process_stat" || "$seed_process_stat" == Z* ]]; then
      break
    fi
    seed_rss_kb="$PROCESS_RSS_KB"
    if [[ -n "$seed_rss_kb" && "$seed_rss_kb" -gt "$seed_peak_rss_kb" ]]; then
      seed_peak_rss_kb="$seed_rss_kb"
    fi
    if [[ -n "$seed_rss_kb" && "$seed_rss_kb" -gt "$seed_max_rss_kb" ]]; then
      echo "seed: memory guard stopped pid $seed_pid at ${seed_rss_kb} KB (limit ${seed_max_rss_kb} KB; peak ${seed_peak_rss_kb} KB)" >&2
      terminate_guarded_pid "$seed_pid"
      exit 125
    fi
    process_sleep "$seed_rss_poll_seconds"
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
      echo "seed: $seed_bootstrap_kind bootstrap compiler $BOOTSTRAP_BIN terminated with status $seed_status (signal $((seed_status - 128)))" >&2
    else
      echo "seed: $seed_bootstrap_kind bootstrap compiler $BOOTSTRAP_BIN failed with status $seed_status" >&2
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
  bash "$ROOT/scripts/build_stage1_llvm_bridge.sh" "$seed_llvm_bridge"
  seed_link_objects+=("$seed_llvm_bridge")
  local seed_cxx_lib=-lc++
  [[ "$(uname -s)" == Linux ]] && seed_cxx_lib=-lstdc++
  "$ELISA_CLANG_TOOL" -fno-builtin "${seed_link_flags[@]}" -o "$seed_output" "${seed_link_objects[@]}" "$seed_profile_hook_source" -L"$libdir" $ELISA_LLVM_LIBS "$seed_cxx_lib" $ELISA_LINK_EXE_FLAGS -Wl,-rpath,"$libdir"
  rm -f "$seed_llvm_bridge"
  if [[ -n "$seed_runtime_obj" ]]; then
    seed_runtime_sha256_actual="$(elisa_sha256 "$seed_runtime_obj" | awk '{print $1}')"
    [[ "$seed_runtime_sha256_actual" == "$seed_runtime_sha256_expected" ]] || {
      echo "seed: bootstrap runtime changed during link; refusing to publish $seed_output" >&2
      exit 2
    }
  fi
  if [[ -n "${ELISA_STAGE1_SEED_INPUTS:-}" ]]; then
    "${PYTHON_HOST:-python3}" "$ROOT/scripts/stage1_provenance.py" check-inputs "$ROOT" "$ELISA_STAGE1_SEED_INPUTS" || {
      echo "seed: refusing to publish a product built while its source inputs were changing" >&2
      exit 2
    }
  fi
  mv -f "$seed_output" "$BIN"
  mv -f "$seed_object" "$seed_object_output"
  ELISA_SEED_OUTPUT=""
  rm -f "$seed_profile_hook_source"
  ELISA_SEED_PROFILE_HOOK_SOURCE=""
  echo "seed: wrote $BIN" >&2
  # The runtime object is built BY the product just written, from the same std it
  # embeds: one compiler for the program and its runtime. A seed that left the object
  # behind handed every consumer a pair from two different sources -- it went unrefreshed
  # for a week that way and nothing noticed until a link failed. Digest-guarded (the
  # product is one of the inputs), so this is a no-op when the object already matches.
  ELISA_STAGE1_BIN="$BIN" bash "$ROOT/scripts/build_runtime_object.sh"
}
