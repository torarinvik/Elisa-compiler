#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "destroyed view lifetime smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-destroyed-view.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

BAD="$ROOT/test/repro/sview_region_use_after_destroy.elisa"
GENERIC_BAD="$ROOT/test/repro/region_generic_struct_signature.elisa"
GOOD="$ROOT/test/parity/fixtures/sview_region_live_use.elisa"
LAST_USE="$ROOT/test/repro/sview_region_last_use_before_destroy.elisa"
for optimization in 0 2; do
    bad_output="$WORK/bad-O$optimization"
    bad_log="$bad_output.log"
    if "$STAGE1" -emit exe "-O$optimization" -o "$bad_output" "$BAD" >"$bad_log" 2>&1; then
        echo "destroyed view lifetime smoke: Stage1 accepted a copied view after its region was destroyed at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "scratch"' "$bad_log" || {
        echo "destroyed view lifetime smoke: missing destroyed-region diagnostic at O$optimization" >&2
        cat "$bad_log" >&2
        exit 1
    }
    [[ ! -e "$bad_output" ]] || { echo "destroyed view lifetime smoke: wrote executable for rejected stale view at O$optimization" >&2; exit 1; }

    generic_output="$WORK/generic-wrapper-O$optimization"
    generic_log="$generic_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$generic_output.ll" "$GENERIC_BAD" >"$generic_log" 2>&1; then
        echo "destroyed view lifetime smoke: Stage1 accepted a generic region-carrying wrapper after its region was destroyed at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "scratch"' "$generic_log" || {
        echo "destroyed view lifetime smoke: generic wrapper rejection lost its region dependency at O$optimization" >&2
        cat "$generic_log" >&2
        exit 1
    }

    good_output="$WORK/good-O$optimization"
    good_log="$good_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$good_output" "$GOOD" >"$good_log" 2>&1 || {
        echo "destroyed view lifetime smoke: rejected a live region-backed view at O$optimization" >&2
        cat "$good_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$good_output" >"$good_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 1 ]] || {
        echo "destroyed view lifetime smoke: live view returned $run_status at O$optimization, expected length 1" >&2
        cat "$good_log.run" >&2
        exit 1
    }

    last_use_output="$WORK/last-use-O$optimization"
    last_use_log="$last_use_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$last_use_output" "$LAST_USE" >"$last_use_log" 2>&1 || {
        echo "destroyed view lifetime smoke: rejected a view whose last use precedes destroy at O$optimization" >&2
        cat "$last_use_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$last_use_output" >"$last_use_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 0 ]] || {
        echo "destroyed view lifetime smoke: last-use-before-destroy control returned $run_status at O$optimization" >&2
        cat "$last_use_log.run" >&2
        exit 1
    }
done

echo "destroyed view lifetime smoke OK: stale copied views are rejected; live and last-use-before-destroy controls pass at O0/O2"
