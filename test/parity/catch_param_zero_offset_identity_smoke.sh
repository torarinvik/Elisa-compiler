#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"

python3 "$ROOT/test/proofs/check_catch_param_zero_offset_identity.py" --source-only
report="$("$RPT" < "$ROOT/test/repro/catch_param_zero_offset_identity.elisa")"
diagnostic_count="$(grep -c 'opaque error-set parameter component' <<< "$report" || true)"
if [[ "$diagnostic_count" != 1 ]]; then
  printf 'Catch ErrorSet parameter offset smoke failed; only the byte-zero generic function should produce this diagnostic:\n%s\n' "$report" >&2
  exit 1
fi

inference_report="$("$RPT" < "$ROOT/test/repro/errorset_param_zero_offset_identity.elisa")"
if grep -q 'cannot infer error-set parameter "R" for call to "concrete"' <<< "$inference_report"; then
  printf 'ErrorSet parameter inference offset smoke reused the byte-zero generic parameter for the later concrete function:\n%s\n' "$inference_report" >&2
  exit 1
fi

printf 'Catch ErrorSet parameter exact-offset smoke OK\n'
