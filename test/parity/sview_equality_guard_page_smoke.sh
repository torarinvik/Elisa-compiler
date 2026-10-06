#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BASELINE="${ELISA_SVIEW_BASELINE:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
CANDIDATE="${ELISA_SVIEW_CANDIDATE:-$ROOT/bin/elisac-stage1}"
CLANG="${ELISA_CLANG:-$(command -v clang || true)}"
FIXTURE="$ROOT/test/bench/codegen_perf/sview_guard_page.elisa"
C_SOURCE="$ROOT/test/bench/codegen_perf/sview_guard_page.c"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-guard.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$BASELINE" ]] || { echo "missing baseline compiler: $BASELINE" >&2; exit 2; }
[[ -x "$CANDIDATE" ]] || { echo "missing candidate compiler: $CANDIDATE" >&2; exit 2; }
[[ -x "$CLANG" ]] || { echo "missing clang: $CLANG" >&2; exit 2; }

# Enforce source freshness wherever these products belong to a compiler checkout.
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$BASELINE"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$CANDIDATE"

source "$ROOT/scripts/sview_guard_page_runtime_inputs.sh"
sview_guard_page_resolve_runtimes "$ROOT" "$BASELINE" "$CANDIDATE"

case "$(uname -s)" in
  Darwin) LINK_FLAGS=(-Wl,-dead_strip) ;;
  Linux) LINK_FLAGS=(-Wl,--gc-sections -no-pie) ;;
  *) echo "unsupported guard-page host: $(uname -s)" >&2; exit 2 ;;
esac

"$BASELINE" -emit obj -O2 -o "$WORK/baseline.o" "$FIXTURE"
"$CANDIDATE" -emit obj -O2 -o "$WORK/candidate.o" "$FIXTURE"
"$CLANG" "${LINK_FLAGS[@]}" -o "$WORK/baseline" "$WORK/baseline.o" "$SVIEW_BASELINE_RUNTIME" "$C_SOURCE"
"$CLANG" "${LINK_FLAGS[@]}" -o "$WORK/candidate" "$WORK/candidate.o" "$SVIEW_CANDIDATE_RUNTIME" "$C_SOURCE"
"$WORK/baseline"
"$WORK/candidate"
echo "sview guard-page baseline/candidate parity OK"
