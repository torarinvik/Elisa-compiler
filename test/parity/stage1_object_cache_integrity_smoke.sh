#!/usr/bin/env bash
# Corrupt/legacy object-cache entries must miss without corrupting compiler outputs.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/platform.sh"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$BIN"
python3 "$ROOT/scripts/test_stage1_object_cache.py"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-object-cache-integrity.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
printf 'def main() -> i64:\n    return 42\n' > "$WORK/fixture.elisa"
export ELISA_STAGE1_BIN="$BIN" ELISA_STAGE1_CACHE=1 ELISA_STAGE1_CACHE_DIR="$WORK/cache"
bash "$ROOT/scripts/elisac_stage1.sh" -o "$WORK/cold.o" "$WORK/fixture.elisa"
bash "$ROOT/scripts/elisac_stage1.sh" -o "$WORK/hit.o" "$WORK/fixture.elisa"
cmp "$WORK/cold.o" "$WORK/hit.o"
entries=("$WORK/cache/"*.o)
[[ ${#entries[@]} == 1 && -s "${entries[0]}" && -s "${entries[0]}.json" ]]
printf 'corrupted cache fixture\n' > "${entries[0]}"
bash "$ROOT/scripts/elisac_stage1.sh" -o "$WORK/recovered.o" "$WORK/fixture.elisa"
cmp "$WORK/cold.o" "$WORK/recovered.o"
# Old entries had no manifest; even plausible bytes alone must not authorize a hit.
rm "${entries[0]}.json"
printf 'legacy corrupt fixture\n' > "${entries[0]}"
bash "$ROOT/scripts/elisac_stage1.sh" -o "$WORK/legacy-recovered.o" "$WORK/fixture.elisa"
cmp "$WORK/cold.o" "$WORK/legacy-recovered.o"
# Contract policy is part of object identity even when this small fixture has
# no contract sites and therefore happens to emit the same machine code.
export ELISA_STAGE1_CACHE_DIR="$WORK/contract-cache"
env -u ELISACORE_FORCE_CONTRACTS bash "$ROOT/scripts/elisac_stage1.sh" -O2 -o "$WORK/contracts-default.o" "$WORK/fixture.elisa"
ELISACORE_FORCE_CONTRACTS=1 bash "$ROOT/scripts/elisac_stage1.sh" -O2 -o "$WORK/contracts-forced.o" "$WORK/fixture.elisa"
contract_entries=("$WORK/contract-cache/"*.o)
[[ ${#contract_entries[@]} == 2 ]]
# A transitive body edit must miss while the entry source and options stay fixed.
export ELISA_STAGE1_CACHE_DIR="$WORK/dependency-cache"
printf 'def leaf() -> i64:\n    return 42\n' > "$WORK/dependency.elisa"
printf 'include "dependency.elisa"\ndef main() -> i64:\n    return leaf()\n' > "$WORK/dependent.elisa"
bash "$ROOT/scripts/elisac_stage1.sh" -o "$WORK/dependency-before.o" "$WORK/dependent.elisa"
printf 'def leaf() -> i64:\n    return 43\n' > "$WORK/dependency.elisa"
bash "$ROOT/scripts/elisac_stage1.sh" -o "$WORK/dependency-after.o" "$WORK/dependent.elisa"
if cmp -s "$WORK/dependency-before.o" "$WORK/dependency-after.o"; then
  echo 'edited dependency incorrectly reused the old object' >&2
  exit 1
fi
dependency_entries=("$WORK/dependency-cache/"*.o)
[[ ${#dependency_entries[@]} == 2 ]]
# Warnings are part of a successful compile's observable result.
export ELISA_STAGE1_CACHE_DIR="$WORK/warning-cache"
warning_fixture="$WORK/warning.elisa"
printf 'def main() -> i64:\n    tmp: i64 = 1\n    result: i64 = tmp + 1\n    later: i64 = 3\n    return result + later\n' > "$warning_fixture"
bash "$ROOT/scripts/elisac_stage1.sh" -Wnever-leak=strict -o "$WORK/warning-cold.o" "$warning_fixture" >"$WORK/cold.stdout" 2>"$WORK/cold.stderr"
bash "$ROOT/scripts/elisac_stage1.sh" -Wnever-leak=strict -o "$WORK/warning-hit.o" "$warning_fixture" >"$WORK/hit.stdout" 2>"$WORK/hit.stderr"
[[ -s "$WORK/cold.stderr" ]]
cmp "$WORK/cold.stdout" "$WORK/hit.stdout"
cmp "$WORK/cold.stderr" "$WORK/hit.stderr"
cmp "$WORK/warning-cold.o" "$WORK/warning-hit.o"
warning_entries=("$WORK/warning-cache/"*.o)
[[ ${#warning_entries[@]} == 1 ]]
printf 'damaged warning stream\n' > "${warning_entries[0]}.stderr"
bash "$ROOT/scripts/elisac_stage1.sh" -Wnever-leak=strict -o "$WORK/warning-recovered.o" "$warning_fixture" >"$WORK/recovered.stdout" 2>"$WORK/recovered.stderr"
cmp "$WORK/cold.stdout" "$WORK/recovered.stdout"
cmp "$WORK/cold.stderr" "$WORK/recovered.stderr"
cmp "$WORK/warning-cold.o" "$WORK/warning-recovered.o"
# Failed compiles must not publish a reusable entry.
export ELISA_STAGE1_CACHE_DIR="$WORK/failure-cache"
printf 'def main() -> i64:\n    return unknown_cache_fixture_name\n' > "$WORK/failure.elisa"
if bash "$ROOT/scripts/elisac_stage1.sh" -o "$WORK/failure.o" "$WORK/failure.elisa" >"$WORK/failure.stdout" 2>"$WORK/failure.stderr"; then
  echo 'invalid fixture unexpectedly compiled' >&2
  exit 1
fi
[[ ! -d "$WORK/failure-cache" ]] || [[ -z "$(find "$WORK/failure-cache" -type f -print -quit)" ]]
echo 'stage1_object_cache_integrity_smoke OK: objects and diagnostics match; damaged entries recompile; failures are not cached'
