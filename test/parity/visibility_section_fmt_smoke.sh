#!/usr/bin/env bash
# A module's `public:` / `private:` sections must survive `-emit fmt` in BOTH compilers,
# byte-identically. Both used to drop them, which turned every private member public: a
# formatter that changes what a program means is worse than one that refuses to format.
# Also pins the two other module-path shapes that were unformattable: a qualified struct
# pattern in a match arm, and a `let T{...}` destructure (stage1 printed <fmt-block-todo>).
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
fail() { echo "visibility_section_fmt FAILED: $*"; exit 1; }

cat > "$WORK/sections.elisa" <<'EOF'
module Pack:
    public:
        struct Item:
            v: i64

        def make(v: i64) -> Item:
            return Item{v: v}

    private:
        def hidden() -> i64:
            return 1

def pick(it: Pack::Item) -> i64:
    let Pack::Item{v} = it
    return v

def choose(it: Pack::Item) -> i64:
    match it:
        Pack::Item{v}:
            return v

def main() -> i64:
    return pick(Pack::make(3)) + choose(Pack::make(4))
EOF

"$ELISACORE_BIN" -emit fmt "$WORK/sections.elisa" </dev/null > "$WORK/s0.txt" 2>"$WORK/s0.err" \
    || fail "stage0 could not format the fixture: $(cat "$WORK/s0.err")"
bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit fmt -o "$WORK/s1.txt" "$WORK/sections.elisa" >/dev/null 2>&1 \
    || fail "stage1 could not format the fixture"

cmp -s "$WORK/s0.txt" "$WORK/s1.txt" || fail "formatted output differs:$(printf '\n')$(diff "$WORK/s0.txt" "$WORK/s1.txt")"
grep -q '^    public:$' "$WORK/s0.txt" || fail "the public section was dropped: $(cat "$WORK/s0.txt")"
grep -q '^    private:$' "$WORK/s0.txt" || fail "the private section was dropped: $(cat "$WORK/s0.txt")"
grep -q 'fmt-block-todo' "$WORK/s1.txt" && fail "stage1 left an unformatted block: $(cat "$WORK/s1.txt")"
grep -q '<pattern>' "$WORK/s1.txt" && fail "stage1 left an unprinted pattern: $(cat "$WORK/s1.txt")"

# Formatting is idempotent, and the reformatted source keeps `hidden` private.
"$ELISACORE_BIN" -emit fmt "$WORK/s0.txt" </dev/null > "$WORK/s0.again" 2>/dev/null \
    || fail "stage0 could not reformat its own output"
cmp -s "$WORK/s0.txt" "$WORK/s0.again" || fail "stage0 formatting is not idempotent"

printf 'def probe() -> i64:\n    return Pack::hidden()\n' >> "$WORK/s0.txt"
out="$("$ELISACORE_BIN" -emit obj -o "$WORK/probe.o" "$WORK/s0.txt" 2>&1)"
grep -q 'is private to module' <<< "$out" || fail "the reformatted module no longer hides its private member: $out"

echo "visibility_section_fmt OK: sections, qualified patterns and let-destructures round-trip byte-identically"
