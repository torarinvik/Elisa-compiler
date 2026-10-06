# shellcheck shell=bash
# Shared fast path for the corpus-wide emit-parity smokes. Source it after
# resolve_elisac.sh (it needs $REPO_ROOT and $ELISACORE_BIN).
#
# Each of these smokes runs both compilers on every file of test/repro, which grew to 800+
# files; ten smokes at ~1.2 s a file made them the bulk of a 2.5 h gate. The per-file cost
# was 0.77 s of uncached stage0, 0.36 s of the stage1 wrapper re-checking provenance and
# polling a memory guard, and 0.07 s of actual stage1 work. So:
#
#   s0 ARGS  -- stage0 through tools/s0cache, the gate's memoised oracle. run_all.sh already
#               routes $ELISACORE_BIN through it; a smoke run on its own is routed here
#               (ELISA_S0_CACHE=0 bypasses it, as in the gate).
#   s1 ARGS  -- stage1. Provenance is asserted ONCE here; a text-only `-emit` mode then calls
#               the binary directly. Every other mode (objects, interpretation, test runs)
#               still goes through scripts/elisac_stage1.sh for its environment and memory
#               guard.
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" >/dev/null || exit $?
S1_BIN="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
if [[ "${ELISA_S0_CACHE:-1}" != 0 && -z "${ELISA_S0_REAL:-}" ]]; then
    export ELISA_S0_REAL="$ELISACORE_BIN"
    export ELISACORE_BIN="$REPO_ROOT/tools/s0cache"
fi

s0() {
    "$ELISACORE_BIN" "$@"
}

s1() {
    local index=0 mode=""
    local -a args=("$@")
    while (( index < ${#args[@]} )); do
        [[ "${args[index]}" == -emit ]] && mode="${args[index + 1]:-}"
        index=$((index + 1))
    done
    case "$mode" in
        fmt|ast|tokens|deps|doc|iface|progress|lowered|annotated-list|unsafe|header|packed)
            ELISA_STAGE1_ROOT="$REPO_ROOT" ELISA_STAGE1_SELF="$S1_BIN" "$S1_BIN" "$@" </dev/null ;;
        *)
            bash "$REPO_ROOT/scripts/elisac_stage1.sh" "$@" ;;
    esac
}
