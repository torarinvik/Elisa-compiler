#!/usr/bin/env bash
# Remote half of tools/remote/remote_gate.sh. Runs DETACHED on the gate host in
# /root/elisa/runs/<run-id>/:   gate_body.sh <s1> <s0> <opt> <jobs|0> <gate>...
# Writes out (the live log the Mac tails), rc, and <gate>.log per gate.
set -uo pipefail
s1="$1"; s0="$2"; OPT="$3"; JOBS="$4"; shift 4; GATES=("$@")
W=/root/elisa; RUNDIR="$PWD"
# Our toolchain only; the box is shared (another session's clang-19 stays the default).
export PATH="$W/bin:$W/go/bin:/usr/lib/llvm-21/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME="$W/home" GOCACHE="$W/cache/go-build" GOPATH="$W/cache/gopath" GOFLAGS=-mod=mod
export XDG_CACHE_HOME="$W/cache" ELISA_S0_CACHE_DIR="$W/cache/s0cache"
export LLVM_CONFIG=/usr/lib/llvm-21/bin/llvm-config ELISA_LLVM_BIN_DIR=/usr/lib/llvm-21/bin
export ELISA_CLANG="$W/bin/clang" ELISA_REAL_CLANG=/usr/lib/llvm-21/bin/clang
export LLC=/usr/lib/llvm-21/bin/llc LLVM_MC=/usr/lib/llvm-21/bin/llvm-mc ELISA_LLVM_OPT=/usr/lib/llvm-21/bin/opt
export ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1
ulimit -s unlimited
mkdir -p "$HOME" "$W/cache" "$W/locks" "$W/seed"
echo $$ > "$RUNDIR/pid"
finish() { echo "$1" > "$RUNDIR/rc"; exit "$1"; }
stamp() { date +%s; }
[[ "$(z3 --version 2>/dev/null)" == *"version 5."* ]] || { echo "z3 >= 5 missing from $W/bin (run setup_host.sh)"; finish 2; }

# --- stage0, once per rev ---------------------------------------------------------------
S0="$W/src/s0-$s0"; S0BIN="$S0/compiler/bin/elisac"
t=$(stamp)
(
  flock 9
  if [[ ! -x "$S0BIN" ]]; then
    cd "$S0/compiler" && CGO_CFLAGS="-I/usr/lib/llvm-21/include" \
      CGO_LDFLAGS="-L/usr/lib/llvm-21/lib -Wl,-rpath,/usr/lib/llvm-21/lib" \
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
      TMPDIR="$SEED/build/tmp"
    mkdir -p bin build/runtime build/tmp
    bash scripts/elisac_stage1.sh --seed && [[ -x bin/elisac-stage1 && -f build/runtime/elisacore_runtime.o ]] && touch .seeded
  fi
) 9>"$W/locks/seed-$KEY.lock" > "$RUNDIR/seed.log" 2>&1
if [[ ! -f "$SEED/.seeded" ]]; then
  echo "seed $KEY: FAILED after $(( $(stamp) - t ))s"; grep -v "warning:" "$RUNDIR/seed.log" | tail -25; finish 1
fi
echo "seed $KEY: $(( $(stamp) - t ))s"

# --- gates, in parallel ------------------------------------------------------------------
# Core budget from live load at dispatch (the box is shared): free cores, split per gate.
cores=$(nproc); load=$(cut -d' ' -f1 /proc/loadavg | cut -d. -f1)
budget=$JOBS; [[ "$budget" -gt 0 ]] 2>/dev/null || budget=$(( cores - load ))
(( budget < 8 )) && budget=8
per=$(( budget / ${#GATES[@]} )); (( per < 4 )) && per=4
echo "dispatch: ${#GATES[@]} gates, load=$load/$cores, $per jobs each"
run_gate() {
  local g="$1" d="$RUNDIR/$1" s; s=$(stamp)
  cp -a "$SEED" "$d" && rm -f "$d/.seeded"
  mkdir -p "$d/build/tmp" "$d/home"
  (
    cd "$d"
    export REPO_ROOT="$d" ELISA_CORE="$S0" ELISACORE_BIN="$S0BIN" ELISA_S0_REAL="$S0BIN"
    [[ -x "$d/tools/s0cache" ]] && export ELISACORE_BIN="$d/tools/s0cache"
    export ELISA_STAGE1_BIN="$d/bin/elisac-stage1" ELISA_RUNTIME_OBJ="$d/build/runtime/elisacore_runtime.o"
    export TMPDIR="$d/build/tmp" HOME="$d/home"
    export ELISA_JOBS=$per ELISA_GATE_JOBS=$per ELISA_HEAVY_JOBS=$per ELISA_INTERNAL_JOBS=$per \
      ELISA_DIAG_JOBS=$per ELISA_ACCEPT_JOBS=$per ELISA_CORPUS_JOBS=$per ELISA_LOCAL_JOBS=$per
    bash "test/parity/$g.sh"
  ) > "$RUNDIR/$g.log" 2>&1
  echo $? > "$RUNDIR/$g.rc"; echo $(( $(stamp) - s )) > "$RUNDIR/$g.secs"
  echo "  done $g rc=$(cat "$RUNDIR/$g.rc") $(cat "$RUNDIR/$g.secs")s"
}
pids=()
for g in "${GATES[@]}"; do
  if [[ ! -f "$SEED/test/parity/$g.sh" ]]; then echo "missing test/parity/$g.sh" > "$RUNDIR/$g.log"; echo 127 > "$RUNDIR/$g.rc"; echo 0 > "$RUNDIR/$g.secs"; continue; fi
  run_gate "$g" & pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done

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
    if awk -v g="$g" -v r="$row" '$1==g && $2==r {found=1} END {exit !found}' "$W/tools/host_invalid.txt"; then
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
