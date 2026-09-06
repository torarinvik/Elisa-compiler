#!/usr/bin/env bash
# Detached job runner for a remote gate host (Phase T.6). Jobs survive the ssh session and
# are polled in the FOREGROUND, so a driver never waits on a background task that can go
# stale: every job leaves <name>.log, <name>.pid and <name>.rc under $ELISA_REMOTE_JOBS.
#
#   tools/remote_run.sh "<ssh opts+target>" sync                 rsync both repos to the host
#   tools/remote_run.sh "<ssh opts+target>" start NAME 'CMD…'    launch CMD detached (bash -lc)
#   tools/remote_run.sh "<ssh opts+target>" wait  NAME [SECS]    block up to SECS (default 540) for .rc; print tail
#   tools/remote_run.sh "<ssh opts+target>" tail  NAME [LINES]   show the log so far
#   tools/remote_run.sh "<ssh opts+target>" ps                   list running jobs
#   tools/remote_run.sh "<ssh opts+target>" kill  NAME
# CMD runs in $ELISA_REMOTE_DIR after sourcing tools/remote_env.sh (toolchain PATH and the
# verification env). Keep product names out of the LOCAL argv: a scanner on the Mac kills
# any local process whose command line mentions them (memory note: harness traps).
set -uo pipefail
SSH_TARGET="${1:?ssh options and target}"; ACTION="${2:?sync|start|wait|tail|ps|kill}"; shift 2
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}"
RDIR="${ELISA_REMOTE_DIR:-/root/Elisa-compiler}"; RCORE="${ELISA_REMOTE_CORE:-/root/structpy-tree}"
RJOBS="${ELISA_REMOTE_JOBS:-/root/jobs}"
addr="${SSH_TARGET##* }"; opts="${SSH_TARGET% *}"; [[ "$addr" == "$SSH_TARGET" ]] && opts=""
rssh() { ssh -o ConnectTimeout=15 -o ServerAliveInterval=20 $opts "$addr" "$@"; }
case "$ACTION" in
  sync)
    rsync -az --exclude .git --exclude 'build/*' --exclude bin -e "ssh $opts" "$ROOT/" "$addr:$RDIR/"
    rsync -az --exclude .git --exclude compiler/bin -e "ssh $opts" "$ELISA_CORE/" "$addr:$RCORE/" ;;
  start)
    name="${1:?job name}"; cmd="${2:?command}"
    script="source $RDIR/tools/remote_env.sh; $cmd"
    rssh "mkdir -p $RJOBS; rm -f $RJOBS/$name.rc; nohup setsid bash -c $(printf '%q' "$script; echo \$? > $RJOBS/$name.rc") > $RJOBS/$name.log 2>&1 < /dev/null & echo \$! > $RJOBS/$name.pid; echo started $name pid \$(cat $RJOBS/$name.pid)" ;;
  wait)
    name="${1:?job name}"; secs="${2:-540}"
    rssh "t=0; while [ ! -f $RJOBS/$name.rc ] && [ \$t -lt $secs ]; do sleep 5; t=\$((t+5)); done
      if [ -f $RJOBS/$name.rc ]; then echo \"== $name finished rc=\$(cat $RJOBS/$name.rc) after \$(( \$(date +%s) - \$(stat -c %Y $RJOBS/$name.pid) ))s\"; tail -n \${TAIL:-40} $RJOBS/$name.log
      else echo \"== $name still running after \$(( \$(date +%s) - \$(stat -c %Y $RJOBS/$name.pid) ))s\"; tail -n 5 $RJOBS/$name.log; exit 3; fi" ;;
  tail) name="${1:?job name}"; rssh "tail -n ${2:-40} $RJOBS/$name.log" ;;
  ps)   rssh "for p in $RJOBS/*.pid; do n=\$(basename \$p .pid); [ -f $RJOBS/\$n.rc ] && s=\"done rc=\$(cat $RJOBS/\$n.rc)\" || s=running; echo \"\$n \$s\"; done 2>/dev/null" ;;
  kill) name="${1:?job name}"; rssh "pkill -TERM -s \$(ps -o sid= -p \$(cat $RJOBS/$name.pid)) ; echo killed $name" ;;
  *) echo "unknown action $ACTION" >&2; exit 2 ;;
esac
