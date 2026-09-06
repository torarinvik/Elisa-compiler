#!/usr/bin/env bash
# Run the stage1 verification list on a REMOTE Linux gate host (Phase T.6).
#
#   tools/remote_gate.sh "<ssh options and target>" [fast|full|gen3]     (default: fast)
#   e.g. tools/remote_gate.sh "-p 50559 root@203.0.113.7" full
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
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}"
RDIR="${ELISA_REMOTE_DIR:-/root/Elisa-compiler}"; RCORE="${ELISA_REMOTE_CORE:-/root/structpy-tree}"
addr="${SSH_TARGET##* }"; opts="${SSH_TARGET% *}"; [[ "$addr" == "$SSH_TARGET" ]] && opts=""
rsync -az --exclude .git --exclude 'build/*' --exclude bin -e "ssh $opts" "$ROOT/" "$addr:$RDIR/"
rsync -az --exclude .git -e "ssh $opts" "$ELISA_CORE/" "$addr:$RCORE/"
case "$PROFILE" in
  fast) LIST="emit_ast_parity_smoke resolve_smoke diagnostics_smoke diagnostics_diff semantic_internal_diff semantic_acceptance_diff global_permissions_smoke" ;;
  gen3) LIST="self_host_gen3_smoke" ;;
  full) LIST="emit_ast_parity_smoke resolve_smoke diagnostics_smoke diagnostics_diff semantic_internal_diff semantic_acceptance_diff global_permissions_smoke differential_corpus adversarial_differential_smoke self_host_gen3_smoke" ;;
  *) echo "unknown profile $PROFILE (fast|full|gen3)" >&2; exit 2 ;;
esac
# The remote script is passed on stdin with the three values substituted up front.
{ printf 'RDIR=%q\nRCORE=%q\nLIST=%q\n' "$RDIR" "$RCORE" "$LIST"; cat "$ROOT/tools/remote_gate_body.sh"; } | ssh $opts "$addr" "bash -s"
