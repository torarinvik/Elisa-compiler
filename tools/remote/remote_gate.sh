#!/usr/bin/env bash
# Run stage1 gates on a remote Linux host against COMMITTED trees.
#
#   tools/remote/remote_gate.sh --host vast4 [options] <s1-rev> <gate|alias>...
#   tools/remote/remote_gate.sh --host vast4 --attach <run-id>      # re-attach after a drop
#
# Options:
#   --s1-repo PATH   repo/worktree holding <s1-rev> (default: this repo)
#   --s0-repo PATH   stage0 repo (default: "$HOME/Documents/Coding Projects/Go projects/Elisa-core")
#   --s0-rev REV     stage0 revision (default: main of --s0-repo)
#   --opt -O0..-O3   seed opt level (default -O3, the repo default)
#   --jobs N         total core budget (default: sized from the host's live load at dispatch)
#
# Aliases: gen3=self_host_gen3_smoke diag=diagnostics_smoke internal=semantic_internal_diff
#          escape=adversarial_escape_smoke backend=backend_native_smoke; any other name is a
#          test/parity/<name>.sh script.
#
# What happens: both trees go over with `git archive` (worktrees share the object db, so any
# commit in either repo works; uncommitted edits are NOT shipped, by design). On the host
# (/root/elisa only; the box may be shared): stage0 is built once per rev, stage1 is seeded
# once per (s1 rev, s0 rev, opt), then every gate runs IN PARALLEL in its own copy of the
# seeded tree. Output: a per-gate summary; rows the host cannot honour (host_invalid.txt) are
# reported SKIP-HOST, not FAIL. Logs stay in /root/elisa/runs/<run-id>/ on the host.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/hosts.sh"
HOST=""; S1_REPO="$(cd "$HERE/../.." && pwd)"
S0_REPO="$HOME/Documents/Coding Projects/Go projects/Elisa-core"; S0_REV=main; OPT=-O3; JOBS=0; ATTACH=""
args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --s1-repo) S1_REPO="$2"; shift 2 ;;
    --s0-repo) S0_REPO="$2"; shift 2 ;;
    --s0-rev) S0_REV="$2"; shift 2 ;;
    --opt) OPT="$2"; shift 2 ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --attach) ATTACH="$2"; shift 2 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) args+=("$1"); shift ;;
  esac
done
[[ -n "$HOST" ]] || { echo "remote_gate: --host required (aliases: $(host_aliases | tr '\n' ' '))" >&2; exit 2; }
host_ssh_args "$HOST"
rssh() { ssh "${SSH_ARGS[@]}" "$@"; }
W=/root/elisa
if [[ -n "$ATTACH" ]]; then
  rssh "tail -n +1 --pid=\$(cat $W/runs/$ATTACH/pid) -f $W/runs/$ATTACH/out"
  exit "$(rssh "cat $W/runs/$ATTACH/rc 2>/dev/null || echo 3")"
fi
[[ ${#args[@]} -ge 2 ]] || { echo "usage: remote_gate.sh --host H <s1-rev> <gate>..." >&2; exit 2; }
S1_REV="$(git -C "$S1_REPO" rev-parse --verify "${args[0]}^{commit}")"
S0_REV="$(git -C "$S0_REPO" rev-parse --verify "$S0_REV^{commit}")"
GATES=()
for g in "${args[@]:1}"; do
  case "$g" in
    gen3) GATES+=(self_host_gen3_smoke) ;; diag) GATES+=(diagnostics_smoke) ;;
    internal) GATES+=(semantic_internal_diff) ;; escape) GATES+=(adversarial_escape_smoke) ;;
    backend) GATES+=(backend_native_smoke) ;; *) GATES+=("$g") ;;
  esac
done
s1=${S1_REV:0:12}; s0=${S0_REV:0:12}
RUN="$(date +%Y%m%d-%H%M%S)-$s1"
echo "remote_gate: host=$HOST s1=$s1 s0=$s0 opt=$OPT gates=${GATES[*]} run=$RUN"
t0=$(date +%s)
ship() {  # repo rev dir
  if rssh "test -f $3/.shipped"; then return 0; fi
  git -C "$1" archive --format=tar "$2" | rssh "rm -rf $3.part && mkdir -p $3.part && tar -x -C $3.part && touch $3.part/.shipped && rm -rf $3 && mv $3.part $3"
}
ship "$S0_REPO" "$S0_REV" "$W/src/s0-$s0" & p0=$!
ship "$S1_REPO" "$S1_REV" "$W/src/s1-$s1" & p1=$!
wait $p0; wait $p1
# The remote half and the host-invalid list travel from THIS checkout, so tooling fixes
# apply to old revs too.
rssh "mkdir -p $W/tools && cat > $W/tools/gate_body.sh" < "$HERE/gate_body.sh"
rssh "cat > $W/tools/host_invalid.txt" < "$HERE/host_invalid.txt"
rssh "cat > $W/tools/clang_shim && install -m755 $W/tools/clang_shim $W/bin/clang" < "$HERE/../linux_shim/clang"
echo "ship: $(( $(date +%s) - t0 ))s"
rssh "mkdir -p $W/runs/$RUN && cd $W/runs/$RUN && nohup setsid bash $W/tools/gate_body.sh $s1 $s0 $OPT $JOBS ${GATES[*]} > out 2>&1 < /dev/null & echo \$! > $W/runs/$RUN/pid"
# Block (no polling) until the detached run exits; a dropped connection loses nothing:
# re-attach with --attach $RUN.
rssh "tail -n +1 --pid=\$(cat $W/runs/$RUN/pid) -f $W/runs/$RUN/out"
rc=$(rssh "cat $W/runs/$RUN/rc 2>/dev/null || echo 3")
echo "remote_gate: total $(( $(date +%s) - t0 ))s rc=$rc (logs: $HOST:$W/runs/$RUN/)"
exit "$rc"
