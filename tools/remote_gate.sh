#!/usr/bin/env bash
# Run the stage1 verification list on a REMOTE Linux gate host (Phase T.6).
#
#   tools/remote_gate.sh "<ssh options and target>" [fast|full|gen3|check1,check2,...]     (default: fast)
#   e.g. tools/remote_gate.sh "-p 50559 root@203.0.113.7" full
#   ELISA_NO_LINUX_SHIM=1 keeps tools/linux_shim off the host PATH (scripts/platform.sh
#   supplies the Linux link flags itself).
#
# Syncs this repo (src/ test/ scripts/ elisacore_std/ ...) and the stage0 checkout to the
# host, reseeds stage1 there (~90 s on 32 cores), runs the chosen list with every
# per-program harness fanned out over the host's cores, and prints the summary lines with
# per-check timings. The host is prepared once as in the memory note `linux-gate-host`
# (LLVM >= 19 with llvm-config on PATH, z3, Go 1.25, the clang shim). Native-execution
# checks on Linux are only as good as stage0's own Linux output: rows reading
# `stage0 exit=139` are the oracle's problem, not stage1's.
set -uo pipefail
SSH_TARGET="${1:?ssh options and target, e.g. \"-p 50559 root@host\"}"; PROFILE="${2:-fast}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Resolve stage0 beside the MAIN checkout: a linked worktree may live at any depth.
MAIN_ROOT="$(cd -- "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)/.." 2>/dev/null && pwd || echo "$ROOT")"
ELISA_CORE="${ELISA_CORE:-$MAIN_ROOT/../../Go projects/Elisa-core}"
[[ -f "$ELISA_CORE/compiler/go.mod" ]] || { echo "remote_gate.sh: no stage0 at '$ELISA_CORE' (set ELISA_CORE)" >&2; exit 2; }
RDIR="${ELISA_REMOTE_DIR:-/root/Elisa-compiler}"; RCORE="${ELISA_REMOTE_CORE:-/root/Elisa-core}"
addr="${SSH_TARGET##* }"; opts="${SSH_TARGET% *}"; [[ "$addr" == "$SSH_TARGET" ]] && opts=""
# The tree WITHOUT .git: in a linked worktree .git is a file naming a Mac path, useless on
# the host. The host keeps its own .git; the commits it lacks travel as a bundle and HEAD is
# moved with a mixed reset, so `git status` there shows exactly this tree's uncommitted edits.
rsync -az --exclude 'build/*' --exclude bin --exclude .git -e "ssh $opts" "$ROOT/" "$addr:$RDIR/"
head="$(git -C "$ROOT" rev-parse HEAD)"
rhead="$(ssh $opts "$addr" "git -C $RDIR rev-parse -q --verify HEAD 2>/dev/null" || true)"
if [[ "$rhead" != "$head" ]]; then
  bundle="$(mktemp "${TMPDIR:-/tmp}/remote_gate.XXXXXX")"
  if [[ -n "$rhead" ]] && git -C "$ROOT" cat-file -e "$rhead^{commit}" 2>/dev/null; then
    git -C "$ROOT" bundle create -q "$bundle" "$rhead..HEAD" 2>/dev/null || git -C "$ROOT" bundle create -q "$bundle" HEAD
  else
    git -C "$ROOT" bundle create -q "$bundle" HEAD
  fi
  rsync -az -e "ssh $opts" "$bundle" "$addr:$RDIR.bundle" && rm -f "$bundle"
  ssh $opts "$addr" "cd $RDIR || exit 1; [ -d .git ] || { rm -f .git; git init -q; }
    git config --global --get-all safe.directory | grep -qx $RDIR || git config --global --add safe.directory $RDIR
    git fetch -q $RDIR.bundle HEAD && git reset -q $head && rm -f $RDIR.bundle"
fi
# A stage0 worktree's .git is a file naming a Mac path; keep the host's own .git then.
core_git=(); [[ -d "$ELISA_CORE/.git" ]] || core_git=(--exclude .git)
rsync -az --exclude compiler/bin "${core_git[@]}" -e "ssh $opts" "$ELISA_CORE/" "$addr:$RCORE/"
case "$PROFILE" in
  fast) LIST="emit_ast_parity_smoke resolve_smoke diagnostics_smoke diagnostics_diff semantic_internal_diff semantic_acceptance_diff global_permissions_smoke" ;;
  gen3) LIST="self_host_gen3_smoke" ;;
  full) LIST="emit_ast_parity_smoke resolve_smoke diagnostics_smoke diagnostics_diff semantic_internal_diff semantic_acceptance_diff global_permissions_smoke differential_corpus adversarial_differential_smoke self_host_gen3_smoke" ;;
  # Any other value is a comma-separated list of test/parity check names, so a fix can be
  # validated on the host with only the checks it touches.
  *,*|*_smoke|*_diff|*_corpus)
    LIST="${PROFILE//,/ }"
    for chk in $LIST; do [[ -f "$ROOT/test/parity/$chk.sh" ]] || { echo "no such check: $chk" >&2; exit 2; }; done ;;
  *) echo "unknown profile $PROFILE (fast|full|gen3, or check1,check2,...)" >&2; exit 2 ;;
esac
# The remote script is passed on stdin with the three values substituted up front.
{ printf 'RDIR=%q\nRCORE=%q\nLIST=%q\nELISA_NO_LINUX_SHIM=%q\n' "$RDIR" "$RCORE" "$LIST" "${ELISA_NO_LINUX_SHIM:-}"; cat "$ROOT/tools/remote_gate_body.sh"; } | ssh $opts "$addr" "bash -s"
