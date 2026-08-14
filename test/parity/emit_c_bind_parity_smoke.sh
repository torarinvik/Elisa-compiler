#!/usr/bin/env bash
# `-emit c-bind-check` / `-emit c-bind-check-json` BYTE PARITY.
#
# The mode verifies that a `@c_bind` struct's Elisa layout matches the REAL C layout, by
# generating a probe, compiling it with `cc` and running it. So this gate exercises a
# subprocess round-trip, and it checks EXIT STATUS as well as bytes: the whole point of the
# mode is to FAIL on an ABI disagreement, and a checker that reports mismatches while
# exiting 0 would be worse than none.
#
# Both compilers write these reports to STDOUT only (stage0 rejects -o for c-bind-check), so
# stage0 is captured from stdout and stage1 via -o, falling back to its stderr for the
# failure paths.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
export CPATH="$WORK"

cat > "$WORK/good.h" <<'EOF'
#include <stdint.h>
typedef struct { int32_t a; int64_t b; } MyPair;
typedef struct { uint8_t x; } MySmall;
EOF
cat > "$WORK/bad.h" <<'EOF'
#include <stdint.h>
typedef struct { int32_t a; int32_t b; } BadPair;
EOF

cat > "$WORK/match.elisa" <<'EOF'
@c_bind("good.h", "MyPair")
struct Pair layout(c):
    a: i32
    b: i64

def main() -> i64:
    return 0
EOF
cat > "$WORK/two.elisa" <<'EOF'
@c_bind("good.h", "MyPair")
struct Pair layout(c):
    a: i32
    b: i64

@c_bind("good.h", "MySmall")
struct Small layout(c):
    x: u8

def main() -> i64:
    return 0
EOF
cat > "$WORK/mismatch.elisa" <<'EOF'
@c_bind("bad.h", "BadPair")
struct Pair layout(c):
    a: i32
    b: i64

def main() -> i64:
    return 0
EOF
cat > "$WORK/none.elisa" <<'EOF'
def main() -> i64:
    return 0
EOF
cat > "$WORK/missing.elisa" <<'EOF'
@c_bind("nosuch.h", "Absent")
struct Pair layout(c):
    a: i32

def main() -> i64:
    return 0
EOF

same=0
differ=0
for case in match two mismatch none missing; do
    for mode in c-bind-check c-bind-check-json; do
        "$ELISACORE_BIN" -emit "$mode" "$WORK/$case.elisa" </dev/null > "$WORK/s0.out" 2>&1; rc0=$?
        bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit "$mode" -o "$WORK/s1.out" "$WORK/$case.elisa" > "$WORK/s1.err" 2>&1; rc1=$?
        # Failure paths write to stderr and leave no output file.
        [ -s "$WORK/s1.out" ] || cp "$WORK/s1.err" "$WORK/s1.out"
        if [ "$rc0" != "$rc1" ]; then
            differ=$((differ + 1)); echo "DIFF $case/$mode: exit $rc0 (stage0) vs $rc1 (stage1)"; continue
        fi
        # A probe COMPILE failure quotes cc's own diagnostics, which embed a temp path that
        # differs per run — compare only the leading `error:` line there.
        if [ "$case" = "missing" ]; then
            if [ "$(head -1 "$WORK/s0.out" | cut -c1-40)" = "$(head -1 "$WORK/s1.out" | cut -c1-40)" ]; then
                same=$((same + 1))
            else
                differ=$((differ + 1)); echo "DIFF $case/$mode (first line):"; head -1 "$WORK/s0.out"; head -1 "$WORK/s1.out"
            fi
            continue
        fi
        if cmp -s "$WORK/s0.out" "$WORK/s1.out"; then
            same=$((same + 1))
        else
            differ=$((differ + 1)); echo "DIFF $case/$mode:"; diff "$WORK/s0.out" "$WORK/s1.out" | head -8
        fi
    done
done

echo "emit_c_bind parity: $same identical, $differ divergent"
[ "$differ" -eq 0 ] || { echo "emit_c_bind parity FAILED"; exit 1; }
echo "emit_c_bind parity OK"
