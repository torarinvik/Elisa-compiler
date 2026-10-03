#!/usr/bin/env bash
# Launch the differential fuzzer DETACHED on a gate host, at nice 15 (gates have priority).
#
#   tools/fuzz/launch.sh --host vast4 [--s1 REV] [--s0 REV] [--opt -O3] [--jobs 30]
#                        [--extra-seeds REV:PATH]...   # e.g. FETCH_HEAD:test/fuzz_findings
#   tools/fuzz/launch.sh --host vast4 --status NAME    # triage summary
#   tools/fuzz/launch.sh --host vast4 --stop NAME
#
# Uses the stage0 build and stage1 seed that tools/remote/remote_gate.sh caches for the same
# (s1, s0, opt); run a gate for that rev first. Seeds: the .neg/.pos fixtures of the s1 tree
# plus any --extra-seeds tree path (shipped with git archive). Output: /root/elisa/fuzz/NAME.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../remote/hosts.sh"
HOST=""; S1=HEAD; S0_REPO="$HOME/Documents/Coding Projects/Go projects/Elisa-core"; S0=main; OPT=-O3; JOBS=30
EXTRA=(); STATUS=""; STOP=""; S1_REPO="$(cd "$HERE/../.." && pwd)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;; --s1) S1="$2"; shift 2 ;; --s0) S0="$2"; shift 2 ;;
    --s0-repo) S0_REPO="$2"; shift 2 ;; --opt) OPT="$2"; shift 2 ;; --jobs) JOBS="$2"; shift 2 ;;
    --extra-seeds) EXTRA+=("$2"); shift 2 ;; --status) STATUS="$2"; shift 2 ;; --stop) STOP="$2"; shift 2 ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done
host_ssh_args "${HOST:?--host required}"; rssh() { ssh "${SSH_ARGS[@]}" "$@"; }
W=/root/elisa
if [[ -n "$STATUS" ]]; then exec ssh "${SSH_ARGS[@]}" "python3 $W/fuzz/tools/triage.py $W/fuzz/$STATUS"; fi
if [[ -n "$STOP" ]]; then exec ssh "${SSH_ARGS[@]}" "kill -- -\$(cat $W/fuzz/$STOP/pid) && echo stopped $STOP"; fi
s1=$(git -C "$S1_REPO" rev-parse --verify "$S1^{commit}" | cut -c1-12)
s0=$(git -C "$S0_REPO" rev-parse --verify "$S0^{commit}" | cut -c1-12)
SEED="$W/seed/$s1-$s0$OPT"
rssh "test -f $SEED/.seeded" || { echo "no seeded tree $SEED: run tools/remote/remote_gate.sh for $s1 first" >&2; exit 2; }
NAME="$(date +%Y%m%d-%H%M)-$s1"; OUT="$W/fuzz/$NAME"
rssh "mkdir -p $W/fuzz/tools $OUT/seeds"
for f in fuzz.py minimize.py triage.py guard.c; do rssh "cat > $W/fuzz/tools/$f" < "$HERE/$f"; done
for e in ${EXTRA[@]+"${EXTRA[@]}"}; do
  rev="${e%%:*}"; path="${e#*:}"
  git -C "$S1_REPO" archive "$rev" "$path" | rssh "mkdir -p $OUT/seeds/extra && tar -x -C $OUT/seeds/extra"
done
rssh "cc -O2 -shared -fPIC -o $W/fuzz/tools/guard.so $W/fuzz/tools/guard.c"
rssh "cd $OUT && cat > run.sh" <<EOF
export PATH=$W/bin:/usr/lib/llvm-21/bin:/usr/bin:/bin HOME=$W/home
export ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1 ELISA_CLANG=$W/bin/clang ELISA_REAL_CLANG=/usr/lib/llvm-21/bin/clang
export LLVM_CONFIG=/usr/lib/llvm-21/bin/llvm-config ELISA_RUNTIME_OBJ=$SEED/build/runtime/elisacore_runtime.o
export TMPDIR=$OUT/tmp; mkdir -p \$TMPDIR
ulimit -s unlimited
exec nice -n 15 python3 $W/fuzz/tools/fuzz.py --s0 $W/src/s0-$s0/compiler/bin/elisac \\
  --s1 $SEED/bin/elisac-stage1 --guard $W/fuzz/tools/guard.so --out $OUT --jobs $JOBS \\
  $SEED/test/fixtures $SEED/test/repro $OUT/seeds
EOF
rssh "cd $OUT && nohup setsid bash run.sh > fuzz.log 2>&1 < /dev/null & echo \$! > $OUT/pid; sleep 3; cat $OUT/fuzz.log"
echo "fuzz: $HOST:$OUT  (status: $0 --host $HOST --status $NAME)"
