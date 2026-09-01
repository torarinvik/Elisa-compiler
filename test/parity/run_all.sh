#!/usr/bin/env bash
# The stage1 parity gate: run EVERY test/parity/*_smoke.sh plus the two standing
# invariants (self-hostable 0 unresolved across the frontend, and lexer token parity
# stage1 == stage0). Exists because the smoke scripts were previously ungated — no target
# ran them, so a regression could rot silently (see the "test tree never gated" lesson).
# One green run here means every stage1-owned guarantee still holds.
#
# As of 2026-07-14 the gate is FULLY GREEN — no known failures (the earlier machine_from
# nested-binding SIGBUS and the diagnostics literal_comparison_impossible FP are both fixed).
# It now also runs flow_strict_census_smoke.sh (docs/125 step 15 graduation): the strict
# block-`if` ban is a gate-enforced standard — the compiler's src + std stay at 0 block-`if`s.
#
#   Usage:  ELISA_CORE=/path/to/Elisa-core  test/parity/run_all.sh
#           (ELISA_CORE defaults to ../../Go projects/structpy-tree)
set -uo pipefail

# SELF-INVOCATION: `run_all.sh --exec-one <resultdir> <name> <cmd...>` runs ONE check and
# records its outcome. This exists because the worker pool below is xargs, which cannot call
# a bash function — so the script re-enters itself per check. Each worker writes its own
# result file, so nothing is shared and no output interleaves.
# ---------------------------------------------------------------- RESULT CACHE
# A check whose INPUTS have not changed cannot have changed its answer, and most gate
# invocations during iteration re-verify a product identical to the last green run. The
# cache key covers everything a check can read: its own script, the stage1 product, the
# stage0 oracle, the runtime object, and a stat-walk of test/ + scripts/ (so editing any
# fixture or helper invalidates every check — conservative, but never wrong).
#
# ONLY SUCCESSES ARE CACHED. A failure re-runs every time: the common painful case is
# re-running the full gate after fixing one red check, and with this cache that run
# re-executes exactly the previously-failing checks and green-stamps the rest from cache.
# A cached row is printed as "ok  (cached)" so a stamped run is never mistaken for a
# measured one. ELISA_GATE_NO_CACHE=1 bypasses; the cache lives in build/ and is ignored.
gate_cache_key() {
  # $1 = the check's script path (first word of the command). Portable md5 via python.
  #
  # The three binaries are keyed by CONTENT HASH, not mtime: several checks rebuild
  # the runtime object mid-gate with byte-identical output, and an mtime key then
  # rotates under every entry written earlier in the same run — the first full-gate
  # cache produced ZERO hits on its own immediate re-run because of exactly that.
  # The parent computes the combined hash once per gate (ELISA_GATE_BINS_HASH);
  # a standalone exec-one without it falls back to hashing the binaries itself.
  local script="$1" root="$2"
  python3 - "$script" "$root" <<'KEYEOF'
import hashlib, os, sys
h = hashlib.sha256()
script, root = sys.argv[1], sys.argv[2]
bins = os.environ.get("ELISA_GATE_BINS_HASH", "")
if bins:
    h.update(bins.encode())
else:
    for f in (os.path.join(root, "bin/elisac-stage1"),
              os.environ.get("ELISACORE_BIN", ""),
              os.path.join(root, "build/runtime/elisacore_runtime.o")):
        try:
            h.update(hashlib.sha256(open(f, "rb").read()).digest())
        except OSError:
            h.update(f.encode()); h.update(b"missing")
for f in (script,):
    try:
        st = os.stat(f)
        h.update(f.encode()); h.update(str((st.st_mtime_ns, st.st_size)).encode())
    except OSError:
        h.update(f.encode()); h.update(b"missing")
tree = os.environ.get("ELISA_GATE_TREE_HASH", "")
if tree:
    h.update(tree.encode())
else:
    for top in ("test", "scripts", "elisacore_std"):
        base = os.path.join(root, top)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                fp = os.path.join(dirpath, name)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                h.update(fp.encode()); h.update(str((st.st_mtime_ns, st.st_size)).encode())
print(h.hexdigest())
KEYEOF
}

if [[ "${1:-}" == "--exec-one" ]]; then
  shift
  _rd="$1"; shift
  _name="$1"; shift
  _log="$_rd/$$.log"
  _root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
  _cachedir="$_root/build/.gate-cache"
  _key=""
  if [[ "${ELISA_GATE_NO_CACHE:-0}" != 1 ]]; then
    _key="$(gate_cache_key "$1" "$_root" 2>/dev/null)" || _key=""
  fi
  _cachefile=""
  if [[ -n "$_key" ]]; then
    _cachefile="$_cachedir/$(printf '%s' "$_name" | tr -c 'A-Za-z0-9_.-' '_')"
    if [[ -f "$_cachefile" ]] && [[ "$(<"$_cachefile")" == "$_key" ]]; then
      printf 'ok\t0\t%s\n' "$_name" > "$_rd/$(printf '%s' "$_name" | tr -c 'A-Za-z0-9_.-' '_').result"
      printf '  %-4s %4ds  %s (cached)\n' "ok" 0 "$_name"
      exit 0
    fi
  fi
  _t0=$SECONDS
  if bash "$@" >"$_log" 2>&1; then _st=ok; else _st=FAIL; fi
  _el=$((SECONDS - _t0))
  if [[ "$_st" == ok && -n "$_cachefile" ]]; then
    mkdir -p "$_cachedir" && printf '%s' "$_key" > "$_cachefile"
  elif [[ -n "$_cachefile" ]]; then
    rm -f "$_cachefile"
  fi
  { printf '%s\t%s\t%s\n' "$_st" "$_el" "$_name"
    [[ "$_st" == FAIL ]] && tail -3 "$_log" | sed 's/^/       /'
  } > "$_rd/$(printf '%s' "$_name" | tr -c 'A-Za-z0-9_.-' '_').result"
  # Live progress. One short printf per check is written atomically, so concurrent workers
  # do not interleave mid-line.
  printf '  %-4s %4ds  %s\n' "$_st" "$_el" "$_name"
  rm -f "$_log"
  exit 0
fi

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$REPO_ROOT/build/runtime/elisacore_runtime.o}"
export ELISA_STAGE1_BIN="$STAGE1_BIN" ELISA_RUNTIME_OBJ="$RUNTIME_OBJ"

[[ -x "$STAGE1_BIN" ]] || {
  echo "error: stage1 product missing at $STAGE1_BIN (run scripts/elisac_stage1.sh --seed)" >&2
  exit 2
}
[[ -f "$RUNTIME_OBJ" ]] || {
  echo "error: stage1 runtime object missing at $RUNTIME_OBJ (run scripts/build_runtime_object.sh)" >&2
  exit 2
}

# Build every SHARED artifact ONCE, here, and export its path so the checks reuse it.
#
# Each of these has a fixed output path and no freshness guard, so every check that wanted
# one REBUILT it: measured on an idle machine, stage0 costs 1.4s and 81 gate checks rebuilt
# it (Go relinks even on a warm cache), and easm_project_driver costs 5.4s across 20 — about
# four minutes of the run spent recomputing identical bytes. It is also what made the suite
# unparallelisable: concurrent checks raced on the same output paths.
#
# Freshness is PRESERVED, not traded away: each is still built from current sources on every
# gate run, just once instead of once per check. (parse_report measures at 0.1s and is
# cached here only for the race, not the time — an earlier 56.7s reading for it was pure
# contention with a gate running in parallel, and re-measuring idle corrected it.)
export ELISACORE_BIN="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
if [[ -z "${ELISA_GATE_PREBUILT:-}" ]]; then
  echo "prebuilding shared artifacts (stage0, parse_report, easm driver)…" >&2
  ( cd "$ELISA_CORE/compiler" && go build -o "$ELISACORE_BIN" ./src ) || {
    echo "error: could not build stage0" >&2; exit 2; }
  # The shared reporter is a STAGE1 artifact; using stage0 here would make every semantic
  # check below test the oracle instead of the product. build_parse_report.sh owns the same
  # freshness/atomic-publish logic used by the workers, so priming it here keeps the checks
  # race-free without silently replacing stage1 with stage0.
  if ! (
    export REPO_ROOT ELISA_STAGE1_BIN="$STAGE1_BIN" ELISA_RUNTIME_OBJ="$RUNTIME_OBJ"
    source "$REPO_ROOT/test/parity/build_parse_report.sh"
  ); then
    echo "error: could not prebuild stage1 parse_report — workers would each rebuild it and race" >&2
    exit 2
  fi
  bash "$REPO_ROOT/test/parity/easm_project_driver_smoke.sh" >/dev/null 2>&1 || true
  export ELISA_GATE_PREBUILT=1
fi

# How many checks run at once. The box has 10 logical / 4 performance cores and every check
# spawns compilers, so oversubscribing loses more to contention than it gains — measured
# serial total was 1398s against a 23:18 wall, i.e. already ~83% busy on one core's worth of
# scheduling. Override with ELISA_GATE_JOBS=1 to get the old serial behaviour when debugging
# a check that is sensitive to load.
#
# MEMORY, not cores, is the binding constraint. A stage1 compile peaks in the GBs (the seed
# guard's ceiling is 4 GB), so six at once wants more RAM than this box has once a browser
# and two editors are resident. When it does not get it the host swaps, and the checks that
# time programs DO NOT FAIL HONESTLY: backend_native_smoke reported trivial programs as
# "runaway loop?" — including ones where the STAGE0 binary was the one that expired — and
# the adversarial oracle reported acceptance gaps for programs both compilers accept. Both
# now retry a timeout before believing it, but the cheaper fix is not to oversubscribe:
# scale the pool by FREE memory, so a busy desktop runs a narrower, honest gate instead of a
# wide, flaky one. ELISA_GATE_JOBS still overrides for a machine known to be quiet.
gate_jobs_by_memory() {
    local free_kb="" gb
    case "$(uname -s)" in
        Darwin)
            # memory_pressure's free percentage, not vm_stat: free+inactive pages
            # badly UNDERSTATE reclaimable memory on macOS (compressed memory and
            # file cache are invisible to them) — this pool once picked 3 workers
            # while the system reported 66% of 24GB free. The kernel's own pressure
            # figure already accounts for everything reclaimable.
            local free_pct total_bytes
            free_pct="$(memory_pressure -Q 2>/dev/null | awk -F': ' '/free percentage/ {gsub(/%/,"",$2); print int($2)}')"
            total_bytes="$(sysctl -n hw.memsize 2>/dev/null)"
            if [[ -n "$free_pct" && -n "$total_bytes" ]]; then
                free_kb=$(( total_bytes / 1024 * free_pct / 100 ))
            else
                free_kb="$(vm_stat 2>/dev/null | awk -v ps="$(sysctl -n hw.pagesize 2>/dev/null || echo 4096)" '
                    /Pages free/ {f=$3} /Pages inactive/ {i=$3}
                    END {gsub(/\./,"",f); gsub(/\./,"",i); if (f=="") exit 1; print int((f+i)*ps/1024)}')" || free_kb=""
            fi
            ;;
        Linux)
            free_kb="$(awk '/MemAvailable/ {print $2}' /proc/meminfo 2>/dev/null)"
            ;;
    esac
    # Unknown host: keep the historical default rather than guessing.
    [[ -z "$free_kb" ]] && { echo 6; return; }
    gb=$((free_kb / 1048576))
    # ~3 GB of headroom per concurrent check, floor of 2 so a loaded box still finishes.
    local n=$((gb / 3))
    (( n < 2 )) && n=2
    (( n > 6 )) && n=6
    echo "$n"
}
GATE_JOBS="${ELISA_GATE_JOBS:-$(gate_jobs_by_memory)}"

# The tree hash is taken ONCE here, pre-dispatch, on a quiesced tree — checks that
# create and delete scratch files inside test/ mid-run otherwise make every
# per-check walk observe a different transient state, and no key ever matches
# across runs (v6: 0 cache hits on a byte-identical tree).
export ELISA_GATE_TREE_HASH="$(python3 - "$REPO_ROOT" <<'TREEEOF'
import hashlib, os, sys
h = hashlib.sha256()
root = sys.argv[1]
for top in ("test", "scripts", "elisacore_std"):
    base = os.path.join(root, top)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            fp = os.path.join(dirpath, name)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            h.update(fp.encode()); h.update(str((st.st_mtime_ns, st.st_size)).encode())
print(h.hexdigest())
TREEEOF
)"

# One content hash of the three product binaries for the whole run — see gate_cache_key.
export ELISA_GATE_BINS_HASH="$(python3 - "$REPO_ROOT" <<'BINSEOF'
import hashlib, os, sys
h = hashlib.sha256()
root = sys.argv[1]
for f in (os.path.join(root, "bin/elisac-stage1"),
          os.environ.get("ELISACORE_BIN", ""),
          os.path.join(root, "build/runtime/elisacore_runtime.o")):
    try:
        h.update(hashlib.sha256(open(f, "rb").read()).digest())
    except OSError:
        h.update(f.encode()); h.update(b"missing")
print(h.hexdigest())
BINSEOF
)"

# ---------------------------------------------------------------- PROFILES
# The full gate is ~11 minutes. That is the right cost before a COMMIT and the wrong cost
# for a one-line iteration, so `--profile NAME` runs a targeted subset. Every profile prints
# what it does NOT cover: a partial gate that reads like a full one is how a regression gets
# waved through, and the whole point of this suite is that it must not cry wolf OR go quiet.
#
# Timings are MEASURED (see the slowest-checks table each run prints), not estimated.
#
# All timings below are MEASURED on this machine, not estimated. `fast` was 4m on its first
# definition because resolve_smoke (130s) and scope_binding_smoke (66s) had been swept into
# it — a profile called "fast" that is not fast will simply be avoided, so it was retrimmed.
#
#   emit       19s / 5 checks   the byte-parity emit oracles (tokens, ast, iface, fmt, deps)
#   parser     24s / 8 checks   lexer + parser acceptance, and the token/ast oracles
#   fast       44s / 16 checks  the emit oracles plus the genuinely cheap smokes
#   semantic  257s / 11 checks  analyzer diffs, diagnostics corpus, breadth baseline
#   backend     -  / codegen smokes + the gen3 fixpoint
#   answers     -  / the differential corpus + driver acceptance
#   easm        -  / the easm group (its own serial lane)
#   full      ~11m / 141 checks  everything. The ONLY profile a commit may rely on.
#
# `answers` deserves its name: those two checks are the only ones in the entire suite that
# compare what the compiler COMPUTES rather than what it accepts. Every other profile can be
# fully green while stage1 silently returns a different number — which is exactly how the
# overload and const-enum wrong answers survived a 141-check gate and a byte-identical
# fixpoint. Treat a green partial profile as "I have not broken the obvious things", never
# as "this is correct".
GATE_PROFILE="${ELISA_GATE_PROFILE:-full}"
if [[ "${1:-}" == "--profile" ]]; then GATE_PROFILE="$2"; shift 2; fi

# name-glob patterns per profile; a check runs when its NAME matches any pattern
profile_patterns() {
  case "$1" in
    fast)     echo 'emit_*_parity_smoke.sh unreachable_smoke.sh when_smoke.sh
                    match_*_smoke.sh struct_*_smoke.sh namespace_*_smoke.sh
                    slice_*_smoke.sh assign_target_smoke.sh' ;;
    answers)  echo 'behavioural* driver_acceptance_smoke.sh differential*' ;;
    backend)  echo 'backend_*_smoke.sh self_host_gen3_smoke.sh opt_pipeline_smoke.sh
                    array_*_smoke.sh slice_*_smoke.sh struct_*_smoke.sh' ;;
    parser)   echo 'lexer* parser* emit_tokens_parity_smoke.sh emit_ast_parity_smoke.sh' ;;
    semantic) echo 'semantic* diagnostics* sema_smoke.sh resolve_smoke.sh internal-suite*
                    diagnostic* unreachable_smoke.sh flow_strict_census_smoke.sh' ;;
    emit)     echo 'emit_*_parity_smoke.sh' ;;
    easm)     echo 'easm_*' ;;
    *)        echo '*' ;;
  esac
}

# Does NAME belong to the active profile?
in_profile() {
  [[ "$GATE_PROFILE" == full ]] && return 0
  local pat
  for pat in $(profile_patterns "$GATE_PROFILE"); do
    # shellcheck disable=SC2053
    [[ "$1" == $pat ]] && return 0
  done
  return 1
}

pass=0
fail=0
failed_names=()
# Per-check wall time, so the next person optimising this has a PROFILE instead of a guess.
# Printed as a sorted table at the end; set ELISA_GATE_QUIET=1 to suppress.
timings_file="$(mktemp)"

run_one() {
  local name="$1"; shift
  local started=$SECONDS
  if bash "$@" >/tmp/stage1_gate.$$.log 2>&1; then
    printf '  ok   %s\n' "$name"
    pass=$((pass + 1))
  else
    printf '  FAIL %s\n' "$name"
    tail -3 /tmp/stage1_gate.$$.log | sed 's/^/       /'
    fail=$((fail + 1))
    failed_names+=("$name")
  fi
  printf '%s\t%s\n' "$((SECONDS - started))" "$name" >> "$timings_file"
}

# Every check, as NUL-delimited (name, command…) records. The repo path contains spaces, so
# these are built and consumed with -0 throughout; word-splitting a joined string here is
# what silently yielded an EMPTY corpus elsewhere in this suite.
#
# ORDERED LONGEST-FIRST from the measured profile. With a fixed pool, starting the long poles
# last leaves workers idle at the tail: the three heaviest checks alone were 881s of a 1398s
# serial total (differential corpus 355s, driver acceptance 310s, backend_native 216s), so
# they must be in flight from the first moment. Anything unlisted sorts after these.
resultdir="$(mktemp -d)"

HEAVY_FIRST=(
  "$REPO_ROOT/test/parity/differential_corpus.sh"
  "$REPO_ROOT/test/parity/driver_acceptance_smoke.sh"
  "$REPO_ROOT/test/parity/backend_native_smoke.sh"
  "$REPO_ROOT/test/parity/extern_view_abi_smoke.sh"
  "$REPO_ROOT/test/parity/self_host_gen3_smoke.sh"
  "$REPO_ROOT/test/parity/scope_binding_smoke.sh"
  "$REPO_ROOT/test/parity/resolve_smoke.sh"
  "$REPO_ROOT/test/parity/check_self_hostable.sh"
  "$REPO_ROOT/test/parity/semantic_internal_diff.sh"
)

# The named checks keep their descriptive labels; the glob keeps basenames, exactly as before.
declare -a JOB_NAMES JOB_CMDS
push() { in_profile "$1" || return 0; JOB_NAMES+=("$1"); shift; JOB_CMDS+=("$(printf '%s\037' "$@")"); }

push "behavioural differential corpus (ratchet)" "$REPO_ROOT/test/parity/differential_corpus.sh"
push "self-hostable (0 unresolved / 132 files)" "$REPO_ROOT/test/parity/check_self_hostable.sh"
push "runtime drift guard (elisacore_std in sync)" "$REPO_ROOT/scripts/check_runtime_drift.sh"
push "lexer parity (stage1 == stage0)" "$REPO_ROOT/test/parity/run_parity.sh"
oracle_lane=(
  "$REPO_ROOT/test/parity/parser_acceptance_diff.sh"
  "$REPO_ROOT/test/parity/semantic_acceptance_diff.sh"
  "$REPO_ROOT/test/parity/diagnostics_diff.sh"
  "$REPO_ROOT/test/parity/semantic_internal_diff.sh"
)
oracle_names=(
  "parser acceptance parity (stage1 == stage0)"
  "semantic acceptance parity (stage1 == stage0)"
  "diagnostics message parity (stage1 covers stage0)"
  "internal-suite differential (ratchet)"
)
push "diagnostic breadth baseline" "$REPO_ROOT/test/breadth/run.sh" --baseline "$REPO_ROOT/test/fixtures/diagnostics.baseline.tsv" "$REPO_ROOT/test/fixtures/diagnostics"

# The behavioural smokes, heavy ones first so they are never left to the tail.
for h in "${HEAVY_FIRST[@]}"; do
  [[ "$h" == *_smoke.sh && -f "$h" ]] && push "$(basename "$h")" "$h"
done
serial_lane=()
for smoke in "$REPO_ROOT"/test/parity/*_smoke.sh; do
  skip=""
  for h in "${HEAVY_FIRST[@]}"; do [[ "$smoke" == "$h" ]] && skip=1; done
  [[ -n "$skip" ]] && continue
  # See the SERIAL LANE note: everything touching the shared easm project driver goes into
  # one sequential job rather than competing for the same output paths.
  case "$(basename "$smoke")" in
    # Shared easm project driver (fixed output paths).
    easm_*) in_profile "$(basename "$smoke")" && serial_lane+=("$smoke"); continue ;;
    # These run stage0's `go test` oracle: concurrent runs share Go's build cache and the
    # fixed ELISA_*_PARITY_OUT paths, which is a race whatever this suite does.
    parser_reference_inventory_smoke.sh|semantic_reference_inventory_smoke.sh)
        in_profile "$(basename "$smoke")" && serial_lane+=("$smoke"); continue ;;
  esac
  push "$(basename "$smoke")" "$smoke"
done

# The serial lane, as one job: each member still gets its own result file and timing, so the
# report is identical to running them individually — only the CONCURRENCY differs.
# The go-test ORACLE lane: these four each invoke stage0's Go test suite to produce their
# oracle, sharing its build cache and fixed *_PARITY_OUT files. They run in sequence with
# each other, but concurrently with everything else.
if [[ ${#oracle_lane[@]} -gt 0 ]]; then
  oracle_script="$resultdir/oracle_lane.sh"
  {
    printf '#!/usr/bin/env bash\n'
    for i in "${!oracle_lane[@]}"; do
      in_profile "${oracle_names[$i]}" || continue
      printf 'bash %q --exec-one %q %q %q\n' "$REPO_ROOT/test/parity/run_all.sh" "$resultdir" "${oracle_names[$i]}" "${oracle_lane[$i]}"
    done
    printf 'exit 0\n'
  } > "$oracle_script"
  chmod +x "$oracle_script"
fi

if [[ ${#serial_lane[@]} -gt 0 ]]; then
  lane_script="$resultdir/serial_lane.sh"
  {
    printf '#!/usr/bin/env bash\n'
    for m in "${serial_lane[@]}"; do
      printf 'bash %q --exec-one %q %q %q\n' "$REPO_ROOT/test/parity/run_all.sh" "$resultdir" "$(basename "$m")" "$m"
    done
    printf 'exit 0\n'
  } > "$lane_script"
  chmod +x "$lane_script"
fi

# Count CHECKS, not pool jobs: the two serial lanes are one job each but many checks.
total_checks=$(( ${#JOB_NAMES[@]} + ${#serial_lane[@]} + ${#oracle_lane[@]} ))
TOTAL_AVAILABLE=$(( $(ls "$REPO_ROOT"/test/parity/*_smoke.sh | wc -l) + 9 ))
if [[ "$GATE_PROFILE" == full ]]; then
  echo "stage1 parity gate — ${total_checks} checks, ${GATE_JOBS} at a time (2 serial lanes):"
else
  echo "stage1 parity gate [PROFILE: $GATE_PROFILE] — ${total_checks} of ${TOTAL_AVAILABLE} checks, ${GATE_JOBS} at a time:"
fi

# One NUL-delimited record per check: resultdir, name, then the command words. Records are
# separated by a DOUBLE NUL. Built with -0 throughout because the repo path contains spaces.
: > "$resultdir/cmdlist"
for i in "${!JOB_NAMES[@]}"; do
  {
    printf '%s\0%s\0' "$resultdir" "${JOB_NAMES[$i]}"
    printf '%s' "${JOB_CMDS[$i]}" | tr '\037' '\0'
    printf '\0'
  } >> "$resultdir/cmdlist"
done

# Dispatch. Each worker re-enters this script in --exec-one mode and writes its own result
# file, so no two workers share state or interleave output.
python3 - "$resultdir" "$REPO_ROOT" "$GATE_JOBS" <<'PYEOF'
import os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
rd, root, jobs = sys.argv[1], sys.argv[2], int(sys.argv[3])
blob = open(os.path.join(rd, "cmdlist"), "rb").read()
records = [r for r in blob.split(b"\0\0") if r.strip(b"\0")]
def run(rec):
    args = [a.decode() for a in rec.split(b"\0") if a != b""]
    if len(args) < 3:
        return
    subprocess.run(["bash", os.path.join(root, "test/parity/run_all.sh"), "--exec-one"] + args,
                   stderr=subprocess.DEVNULL)
with ThreadPoolExecutor(max_workers=jobs) as ex:
    futures = [ex.submit(run, r) for r in records]
    for extra in ("serial_lane.sh", "oracle_lane.sh"):
        pth = os.path.join(rd, extra)
        if os.path.exists(pth):
            futures.append(ex.submit(
                lambda p=pth: subprocess.run(["bash", p], stderr=subprocess.DEVNULL)))
    for f in futures:
        f.result()
PYEOF

# Aggregate. Results are per-file, so nothing raced to produce this.
for f in "$resultdir"/*.result; do
  [[ -f "$f" ]] || continue
  st="$(head -1 "$f" | cut -f1)"
  el="$(head -1 "$f" | cut -f2)"
  nm="$(head -1 "$f" | cut -f3-)"
  [[ "$st" == FAIL ]] && { printf '  FAIL %s\n' "$nm"; tail -n +2 "$f"; }
  printf '%s\t%s\n' "$el" "$nm" >> "$timings_file"
  if [[ "$st" == ok ]]; then pass=$((pass + 1)); else fail=$((fail + 1)); failed_names+=("$nm"); fi
done
rm -rf "$resultdir"

rm -f /tmp/stage1_gate.$$.log
if [[ -z "${ELISA_GATE_QUIET:-}" ]]; then
  echo "----------------------------------------"
  echo "slowest checks (seconds):"
  sort -rn "$timings_file" | head -12 | awk -F'\t' '{printf "  %5ds  %s\n", $1, $2}'
  printf '  %5ds  TOTAL\n' "$(awk -F'\t' '{t+=$1} END{print t}' "$timings_file")"
fi
rm -f "$timings_file"
echo "----------------------------------------"
if [[ $fail -eq 0 ]]; then
  if [[ "$GATE_PROFILE" == full ]]; then
    echo "stage1 parity gate OK: $pass checks passed"
  else
    echo "stage1 parity gate [$GATE_PROFILE] OK: $pass checks passed — PARTIAL, not a commit gate"
    case "$GATE_PROFILE" in
      fast|parser|semantic|emit|easm)
        echo "  NOT covered by this profile: the differential corpus and driver acceptance" >&2
        echo "  (the only checks that compare COMPUTED ANSWERS) and the gen3 fixpoint." >&2
        echo "  Run --profile full before committing." >&2 ;;
      backend)
        echo "  NOT covered: the differential corpus, driver acceptance, semantic diffs." >&2
        echo "  Run --profile full before committing." >&2 ;;
      answers)
        echo "  NOT covered: every acceptance and byte-parity oracle." >&2
        echo "  Run --profile full before committing." >&2 ;;
    esac
  fi
  exit 0
fi
echo "stage1 parity gate FAILED: $fail of $((pass + fail)) checks failed:"
printf '  - %s\n' "${failed_names[@]}"
exit 1
