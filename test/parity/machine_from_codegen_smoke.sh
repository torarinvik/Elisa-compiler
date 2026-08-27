#!/usr/bin/env bash
# Canonical typed-state arrows must survive the self-hosted frontend, LLVM emission,
# native linking, and execution. Expected: choose(true)=21, choose(false)=22, total=43.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-machine-from.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

bash "$ROOT/scripts/build_runtime_object.sh" >/dev/null
for fixture in typed_state_arrows explicit_state_arrows; do
  bash "$ROOT/scripts/elisac_stage1.sh" -O2 -o "$WORK/$fixture.o" "$ROOT/test/fixtures/machine_from/$fixture.elisa"
  clang -Wl,-dead_strip -o "$WORK/$fixture" "$WORK/$fixture.o" "$ROOT/build/runtime/elisacore_runtime.o"
  set +e
  "$WORK/$fixture"
  status=$?
  set -e
  if [[ "$status" -ne 43 ]]; then
    echo "machine from codegen FAIL ($fixture): exit $status, expected 43" >&2
    exit 1
  fi
done
echo "machine from codegen OK: explicit + local typed states, -> transitions, and => results execute as 43"
