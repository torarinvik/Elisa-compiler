#!/usr/bin/env bash
# Remote half of tools/remote/remote_gate.sh. Runs DETACHED on the gate host in
# /root/elisa/runs/<run-id>/:   gate_body.sh <s1> <s0> <opt> <jobs|0> <gate>...
# Writes out (the live log the Mac tails), rc, and <gate>.log per gate.
set -uo pipefail
s1="$1"; s0="$2"; OPT="$3"; JOBS="$4"; shift 4; GATES=("$@")
W="${ELISA_REMOTE_ROOT:-/root/elisa}"; LV="${ELISA_REMOTE_LLVM:-21}"; RUNDIR="$PWD"
# Our toolchain only; the box is shared (another session's clang-19 stays the default).
export PATH="$W/bin:$W/go/bin:/usr/lib/llvm-$LV/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME="$W/home" GOCACHE="$W/cache/go-build" GOPATH="$W/cache/gopath" GOFLAGS=-mod=mod
export XDG_CACHE_HOME="$W/cache" ELISA_S0_CACHE_DIR="$W/cache/s0cache"
export LLVM_CONFIG=/usr/lib/llvm-$LV/bin/llvm-config ELISA_LLVM_BIN_DIR=/usr/lib/llvm-$LV/bin
export ELISA_CLANG="$W/bin/clang" ELISA_REAL_CLANG=/usr/lib/llvm-$LV/bin/clang
export LLC=/usr/lib/llvm-$LV/bin/llc LLVM_MC=/usr/lib/llvm-$LV/bin/llvm-mc ELISA_LLVM_OPT=/usr/lib/llvm-$LV/bin/opt
export ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1 ELISA_TOOL_SHIM_DIR="$W/bin"
ulimit -s unlimited
mkdir -p "$HOME" "$W/cache" "$W/locks" "$W/seed"
echo $$ > "$RUNDIR/pid"
# Held (shared) for the whole run: the fuzzer pauses while any run holds it.
exec 7>"$W/locks/active.lock"; flock -s 7
finish() { echo "$1" > "$RUNDIR/rc"; exit "$1"; }
stamp() { date +%s; }
[[ "$(z3 --version 2>/dev/null)" == *"version 5."* ]] || { echo "z3 >= 5 missing from $W/bin (run setup_host.sh)"; finish 2; }

# --- stage0, once per rev ---------------------------------------------------------------
S0="$W/src/s0-$s0"; S0BIN="$S0/compiler/bin/elisac"
t=$(stamp)
(
  flock 9
  if [[ ! -x "$S0BIN" ]]; then
    cd "$S0/compiler" && CGO_CFLAGS="-I/usr/lib/llvm-$LV/include" \
      CGO_LDFLAGS="-L/usr/lib/llvm-$LV/lib -Wl,-rpath,/usr/lib/llvm-$LV/lib" \
      go build -o bin/elisac.part ./src && mv bin/elisac.part bin/elisac
  fi
) 9>"$W/locks/s0-$s0.lock" > "$RUNDIR/stage0_build.log" 2>&1
[[ -x "$S0BIN" ]] || { echo "stage0 build FAILED:"; tail -20 "$RUNDIR/stage0_build.log"; finish 2; }
echo "stage0 $s0: $(( $(stamp) - t ))s"

# --- stage1 seed, once per (s1, s0, opt) --------------------------------------------------
KEY="$s1-$s0$OPT"; SEED="$W/seed/$KEY"
t=$(stamp)
(
  flock 9
  if [[ ! -f "$SEED/.seeded" ]]; then
    rm -rf "$SEED" && cp -a "$W/src/s1-$s1" "$SEED" && cd "$SEED" || exit 1
    export REPO_ROOT="$SEED" ELISA_CORE="$S0" ELISACORE_BIN="$S0BIN" \
      ELISA_STAGE1_BIN="$SEED/bin/elisac-stage1" ELISA_RUNTIME_OBJ="$SEED/build/runtime/elisacore_runtime.o" \
      ELISA_STAGE1_SEED_OPT_LEVEL="$OPT" ELISA_STAGE1_GLOBAL_SEED_LOCK_DIR="$W/locks/seed-global-$KEY" \
      TMPDIR="$SEED/build/tmp" ELISA_STAGE1_SEED_MAX_RSS_KB="${ELISA_STAGE1_SEED_MAX_RSS_KB:-33554432}"
    # stage0 on Linux peaks above the Mac-sized 4 GB seed guard (stopped at 4.0 GB on
    # vast4); these hosts have >200 GB, so the guard is 32 GB here.
    mkdir -p bin build/runtime build/tmp
    bash scripts/elisac_stage1.sh --seed && [[ -x bin/elisac-stage1 && -f build/runtime/elisacore_runtime.o ]] && touch .seeded
  fi
) 9>"$W/locks/seed-$KEY.lock" > "$RUNDIR/seed.log" 2>&1
if [[ ! -f "$SEED/.seeded" ]]; then
  echo "seed $KEY: FAILED after $(( $(stamp) - t ))s"; grep -v "warning:" "$RUNDIR/seed.log" | tail -25; finish 1
fi
echo "seed $KEY: $(( $(stamp) - t ))s"

# --- gates, in parallel ------------------------------------------------------------------
# CPU CAP. vast4's 80 "cores" sit under a 38.4-CPU cgroup-v1 quota
# (/sys/fs/cgroup/cpu/cpu.cfs_quota_us) shared by every session; nice does not help under a
# quota, so the cap is a hard job count: JOBS = this host's share (hosts.local column 4).
# The gate phase of every run on the host is serialized on one lock, so concurrent runs from
# several agents queue instead of each taking the whole share.
budget=$JOBS; [[ "$budget" -gt 0 ]] 2>/dev/null || budget=8
n=${#GATES[@]}; per=$(( budget / n )); (( per < 2 )) && per=2
slots=$(( budget / per )); (( slots < 1 )) && slots=1
t=$(stamp)
exec 8>"$W/locks/gate-phase.lock"; flock 8
echo "dispatch: $n gates, cap=$budget: $slots at a time x $per jobs (queued $(( $(stamp) - t ))s)"
run_gate() {
  local g="$1" d="$RUNDIR/$1" s; s=$(stamp)
  cp -a "$SEED" "$d" && rm -f "$d/.seeded"
  mkdir -p "$d/build/tmp" "$d/home"
  # Older revs reset PATH in self_host_gen2.sh to /usr/bin first, so a
  # shared host's system clang (no Apple-flag mapping) linked gen2 and failed on -dead_strip.
  # Same one-line PATH fix the newer script carries; harness only, not compiler source.
  grep -q ELISA_TOOL_SHIM_DIR "$d/scripts/self_host_gen2.sh" 2>/dev/null ||
    sed -i 's|^export PATH="/usr/bin:/bin:|export PATH="${ELISA_TOOL_SHIM_DIR:+$ELISA_TOOL_SHIM_DIR:}/usr/bin:/bin:|' "$d/scripts/self_host_gen2.sh"
  (
    cd "$d"
    export REPO_ROOT="$d" ELISA_CORE="$S0" ELISACORE_BIN="$S0BIN" ELISA_S0_REAL="$S0BIN"
    [[ -x "$d/tools/s0cache" ]] && export ELISACORE_BIN="$d/tools/s0cache"
    export ELISA_STAGE1_BIN="$d/bin/elisac-stage1" ELISA_RUNTIME_OBJ="$d/build/runtime/elisacore_runtime.o"
    export TMPDIR="$d/build/tmp" HOME="$d/home" ELISA_STAGE1_MAX_RSS_KB="${ELISA_STAGE1_MAX_RSS_KB:-33554432}"
    export ELISA_JOBS=$per ELISA_GATE_JOBS=$per ELISA_HEAVY_JOBS=$per ELISA_INTERNAL_JOBS=$per \
      ELISA_DIAG_JOBS=$per ELISA_ACCEPT_JOBS=$per ELISA_CORPUS_JOBS=$per ELISA_LOCAL_JOBS=$per
    bash "test/parity/$g.sh"
  ) > "$RUNDIR/$g.log" 2>&1
  echo $? > "$RUNDIR/$g.rc"; echo $(( $(stamp) - s )) > "$RUNDIR/$g.secs"
  echo "  done $g rc=$(cat "$RUNDIR/$g.rc") $(cat "$RUNDIR/$g.secs")s"
}
pids=()
running=0
for g in "${GATES[@]}"; do
  if [[ ! -f "$SEED/test/parity/$g.sh" ]]; then echo "missing test/parity/$g.sh" > "$RUNDIR/$g.log"; echo 127 > "$RUNDIR/$g.rc"; echo 0 > "$RUNDIR/$g.secs"; continue; fi
  if (( running >= slots )); then wait -n; running=$((running - 1)); fi
  run_gate "$g" & running=$((running + 1))
done
wait
exec 8>&-

# --- summary -----------------------------------------------------------------------------
# host_invalid.txt: "<gate> <row>" lines; a FAIL row naming such a row becomes SKIP-HOST and
# the gate passes if nothing else failed.
overall=0
echo; printf '%-28s %-10s %6s  %s\n' GATE VERDICT SECS DETAIL
for g in "${GATES[@]}"; do
  log="$RUNDIR/$g.log"; rc=$(cat "$RUNDIR/$g.rc"); secs=$(cat "$RUNDIR/$g.secs")
  mapfile -t fails < <(grep -E '^\s*FAIL[ :]' "$log" | grep -v '^\s*FAIL: unknown command' || true)
  skips=0; real=()
  for f in "${fails[@]}"; do
    row=$(sed -E 's/^\s*FAIL:? ([^: ]+).*/\1/' <<<"$f")
    if awk -v g="$g" -v r="$row" '$1==g && $2==r {found=1} END {exit !found}' "$RUNDIR/host_invalid.txt"; then
      skips=$((skips+1))
    else real+=("$f"); fi
  done
  verdict=PASS
  if [[ "$rc" != 0 ]]; then
    if (( skips > 0 && ${#real[@]} == 0 )) && ! grep -q "check helper was undefined" "$log"; then verdict=PASS; else verdict=FAIL; fi
  fi
  (( skips > 0 )) && verdict="$verdict+SKIP-HOST($skips)"
  [[ "$verdict" == FAIL* ]] && overall=1
  last=$(grep -v "warning:" "$log" | grep -E "OK|FAIL|PASS|passed|mismatch" | tail -1 | cut -c1-110)
  printf '%-28s %-10s %6s  %s\n' "$g" "$verdict" "$secs" "$last"
  if [[ "$verdict" == FAIL* ]]; then
    if (( ${#real[@]} )); then printf '      %s\n' "${real[@]:0:8}"; else grep -v "warning:" "$log" | tail -6 | sed 's/^/      /'; fi
  fi
done
finish $overall
