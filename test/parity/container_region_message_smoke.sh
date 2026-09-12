#!/usr/bin/env bash
# The container-region diagnostic family ("darray/dict/set literal has no region to allocate in").
#
# Two regressions are pinned here:
#
#  1. POSITION. dict and set literals were checked in the ANALYZER (positioned, with a column
#     span); darray literals were not, so the only thing that caught them was the backend's
#     emitListLitExpr -- a bare fmt.Errorf with NO file, line or column. The most common
#     container in the language had the worst diagnostic in the family.
#  2. WORDING. The shared text was "requires an active in <arena>: scope", naming a largely
#     deprecated construct and saying nothing about the fix. A container's region is inferred
#     from its DESTINATION, so the message now says so.
#
# Also asserts the four destinations that DO supply a region still compile, so the new analyzer
# check cannot start rejecting valid code.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
fail() { echo "container-region-message smoke FAIL: $1" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

printf 'def take(xs: darray[i64]) -> i64:\n    return xs.count.i64()\n\ndef main() -> i64 can[Memory.Allocate, Abort.Panic]:\n    return take([1, 2, 3])\n' > "$work/lit_darray.elisa"
printf 'def take(d: dict[cstr, i64]) -> i64:\n    return 0\n\ndef main() -> i64 can[Memory.Allocate, Abort.Panic]:\n    return take({"a": 1})\n' > "$work/lit_dict.elisa"
printf 'def take(s: set[i64]) -> i64:\n    return 0\n\ndef main() -> i64 can[Memory.Allocate, Abort.Panic]:\n    return take({1, 2})\n' > "$work/lit_set.elisa"

for kind in darray dict set; do
  out=$( cd "$work" && "$ELISACORE_BIN" -emit llvm -o /dev/null "lit_$kind.elisa" 2>&1 )
  # 1. POSITIONED: FILE:LINE:COLSTART-COLEND, not a bare "error:".
  # stage0 prints the path it RESOLVED, which is absolute here; assert the FILE:LINE:COL-COL
  # shape rather than anchoring at the start of the line.
  grep -qE "lit_$kind\.elisa:[0-9]+:[0-9]+-[0-9]+: $kind literal has no region" <<< "$out" \
    || fail "$kind literal diagnostic is not positioned: $out"
  # 2. WORDED with the fix, and free of the deprecated construct.
  grep -Fq "it takes one from its destination" <<< "$out" || fail "$kind literal message lost its guidance: $out"
  grep -Fq "in <arena>" <<< "$out" && fail "$kind literal message still names the deprecated in <arena>: scope: $out"
done

# 3. Every destination that DOES supply a region must still compile.
printf 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:\n    xs: darray[i64] = [1, 2, 3]\n    return xs.count.i64()\n' > "$work/ok_local.elisa"
printf 'def mk() -> darray[i64]:\n    can Memory.Allocate, Abort.Panic:\n        return [1, 2, 3]\n\ndef main() -> i64 can[Memory.Allocate, Abort.Panic]:\n    return mk().count.i64()\n' > "$work/ok_return.elisa"
printf 'struct S:\n    xs: darray[i64]\n\ndef main() -> i64 can[Memory.Allocate, Abort.Panic]:\n    s: S = S{xs: [1, 2, 3]}\n    return s.xs.count.i64()\n' > "$work/ok_field.elisa"
for ok in ok_local ok_return ok_field; do
  ( cd "$work" && "$ELISACORE_BIN" -emit llvm -o /dev/null "$ok.elisa" >/dev/null 2>&1 ) \
    || fail "$ok no longer compiles; the region check is rejecting a valid destination"
done

# 4. No user-facing "in <arena>: scope" text survives anywhere in stage0's sources, and stage1's
#    one mirrored message is byte-identical to stage0's helper output.
# Count only CODE lines: diagnostic_messages.go documents the wording it replaced, in a
# comment, and that reference should survive.
core_hits=$(grep -rn 'requires an active in <arena>: scope' --include='*.go' "$ELISA_CORE/compiler/src" 2>/dev/null \
  | grep -v '_test.go' \
  | sed 's/^[^:]*:[0-9]*://' \
  | grep -vc '^[[:space:]]*//' || true)
[ "$core_hits" -eq 0 ] || fail "$core_hits stage0 sites still emit the deprecated in <arena>: scope wording"
grep -Fq 'darray push has no region to grow into; a region is inferred from where the receiver is declared (a typed local, a parameter, or a struct field)' \
  "$REPO_ROOT/src/semantic/semantic_api_message_3.elisa" \
  || fail "stage1's DarrayPushArenaRequired text has drifted from stage0's NoGrowthRegionMessage"

echo "container-region-message smoke OK: darray/dict/set literals positioned + actionable, 3 valid destinations compile, 0 deprecated-wording sites, stage1 text in sync"
