#!/usr/bin/env bash
# `-emit tests` / `-emit benches` / `-emit fixtures` BYTE PARITY.
#
# All three are the same emitter with a different annotation name: one
# `NAME<TAB>fn() -> RET[ can[FAMILY, ...]]` row per matching function, in declaration
# order, selected by the `-filter` SUBSTRING.
#
# The corpus declares no annotated functions at all, so a corpus-only run would compare
# empty output against empty output and prove nothing — every fixture below is written
# here to exercise a specific part of the signature rendering:
#
#   * the permission clause is stage0's FAMILY set, deduplicated and SORTED (source order
#     `can[Memory.Allocate, Console.Write]` must print `can[Console, Memory]`);
#   * `@fixture` may not require permissions and `@bench` must return void, so only the
#     fixture list ever varies its return type;
#   * a tuple return type carries a depth-0-looking colon, which must not truncate it;
#   * annotations inside a `module` still list, under their bare name.
#
# stage0 REFUSES `-o` for all three, so the listing is compared on stdout and the refusal
# itself is part of the parity checked here.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
differ=0

compare() {
    local label="$1"; local src="$2"; shift 2
    local s0 s1
    s0="$("$ELISACORE_BIN" -emit "$@" "$src" </dev/null 2>/dev/null)"
    s1="$(bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit "$@" "$src" 2>/dev/null)"
    if [ "$s0" = "$s1" ]; then
        same=$((same + 1))
    else
        differ=$((differ + 1))
        echo "DIFF: $label"
        diff <(printf '%s\n' "$s0") <(printf '%s\n' "$s1") | head -8
    fi
}

cat > "$WORK/a.elisa" <<'EOF'
struct Point:
    x: i64

@test
def plain_test() -> void:
    return

@test
def effectful_test() -> void can[Console.Write, Memory.Allocate, Abort.Panic]:
    xs: mutable darray[i64] = []
    xs.push(1)
    return

@bench
def measure_one() -> void:
    return

@bench
def measure_two() -> void:
    return

@fixture
def seed_int() -> i64:
    return 7

@fixture
def seed_alias() -> int:
    return 7

@fixture
def seed_struct() -> Point:
    return Point{x: 1}

@fixture
def seed_optional() -> i64?:
    return 3

@fixture
def seed_ref() -> u8&:
    return "x".cast[u8&]

@fixture
def seed_tuple() -> (lo: i64, hi: i64):
    return (1, 2)
EOF

# A unit with NO annotated function of the requested kind: the empty-listing path.
cat > "$WORK/empty.elisa" <<'EOF'
def helper(a: i64) -> i64:
    return a
EOF

# Annotations nested inside a namespace.
cat > "$WORK/nested.elisa" <<'EOF'
module inner:
    @test
    def nested_test() -> void:
        return

@test
def outer_test() -> void:
    return
EOF

for mode in tests benches fixtures; do
    compare "$mode/all"        "$WORK/a.elisa"      "$mode"
    compare "$mode/empty"      "$WORK/empty.elisa"  "$mode"
    compare "$mode/nested"     "$WORK/nested.elisa" "$mode"
    compare "$mode/filter-hit" "$WORK/a.elisa"      "$mode" -filter e
    compare "$mode/filter-mid" "$WORK/a.elisa"      "$mode" -filter seed
    compare "$mode/filter-nil" "$WORK/a.elisa"      "$mode" -filter zzzz
done

# Every corpus fixture: none declares an annotated function, so all three listings must be
# empty under BOTH compilers. This is a regression guard, not a coverage claim — a change
# that started listing plain functions would show up here across hundreds of files.
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    grep -q '^[[:space:]]*include "' "$src" && continue
    "$ELISACORE_BIN" -emit tests "$src" </dev/null >/dev/null 2>&1 || continue
    compare "corpus/$(basename "$src" .elisa)" "$src" tests
done

# stage0 refuses -o for all three; so must stage1.
reject=0
for mode in tests benches fixtures; do
    if bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit "$mode" -o "$WORK/out" "$WORK/a.elisa" >/dev/null 2>&1; then
        echo "REJECT: -emit $mode accepted -o, stage0 refuses it"; reject=1
    fi
done

echo "emit_annotated_list parity: $same identical, $differ divergent"
if [ "$differ" -ne 0 ] || [ "$reject" -ne 0 ]; then
    echo "emit_annotated_list parity FAILED"
    exit 1
fi
echo "emit_annotated_list parity OK"
