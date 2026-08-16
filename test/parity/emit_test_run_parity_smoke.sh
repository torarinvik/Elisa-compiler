#!/usr/bin/env bash
# `-emit test` PARITY: compile the unit once, run each selected `@test` in its OWN
# process, and report RUN/OK/SKIPPED/PANIC/SUMMARY exactly as stage0 does.
#
# What is compared, and what is NOT:
#
#   * The PASS, SKIP, FILTER, NO-TESTS and SUMMARY paths are demanded BYTE-IDENTICAL,
#     including the exit status (1 when anything failed or nothing matched).
#   * A PANICKING test is compared only down to its status LINE. stage0 replays the
#     child's captured stdout/stderr, which on this path carries a symbolized backtrace —
#     raw addresses that differ between two builds of the same program, so no two runs
#     agree byte-for-byte, let alone two compilers. The line that classifies the failure
#     (`[ PANIC    ] name (signal abort trap)`) IS deterministic and is compared.
#
# The signal name is the part most likely to regress: system() runs the command through
# `/bin/sh -c`, which reports a signalled child as a NORMAL exit with code 128+N. Reading
# the wait status' low byte finds no signal at all and prints ` (exit 134)` where stage0
# prints ` (signal abort trap)`. The panic case below is what catches that.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
differ=0

# Compare stdout AND exit status, byte for byte.
compare() {
    local label="$1"; local src="$2"; shift 2
    local s0 s1 rc0 rc1
    s0="$("$ELISACORE_BIN" -emit test "$@" "$src" </dev/null 2>/dev/null)"; rc0=$?
    s1="$(bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit test "$@" "$src" 2>/dev/null)"; rc1=$?
    if [ "$s0" = "$s1" ] && [ "$rc0" = "$rc1" ]; then
        same=$((same + 1))
    else
        differ=$((differ + 1))
        echo "DIFF: $label (stage0 rc=$rc0, stage1 rc=$rc1)"
        diff <(printf '%s\n' "$s0") <(printf '%s\n' "$s1") | head -10
    fi
}

# Compare only the lines that cannot carry a backtrace address.
compare_status_lines() {
    local label="$1"; local src="$2"; shift 2
    local s0 s1 rc0 rc1
    s0="$("$ELISACORE_BIN" -emit test "$@" "$src" </dev/null 2>/dev/null | grep -E '^\[ (RUN|  *OK|SKIPPED|PANIC|FAILED|SUMMARY) ')"; rc0=$?
    s1="$(bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit test "$@" "$src" 2>/dev/null | grep -E '^\[ (RUN|  *OK|SKIPPED|PANIC|FAILED|SUMMARY) ')"; rc1=$?
    if [ "$s0" = "$s1" ]; then
        same=$((same + 1))
    else
        differ=$((differ + 1))
        echo "DIFF: $label"
        diff <(printf '%s\n' "$s0") <(printf '%s\n' "$s1") | head -10
    fi
}

cat > "$WORK/pass.elisa" <<'EOF'
@test
def checks_one() -> void:
    return

@test
def checks_two() -> void:
    return

def helper(a: i64) -> i64:
    return a
EOF

cat > "$WORK/skip.elisa" <<'EOF'
@test
def runs() -> void:
    return

@test
@skip
def skipped_case() -> void:
    return
EOF

cat > "$WORK/none.elisa" <<'EOF'
def helper(a: i64) -> i64:
    return a
EOF

cat > "$WORK/panic.elisa" <<'EOF'
@test
def passes() -> void:
    return

@test
def explodes() -> void can[Abort.Panic]:
    panic("boom")
EOF

compare "all pass"            "$WORK/pass.elisa"
compare "filter exact"        "$WORK/pass.elisa" -filter checks_one
compare "filter substring"    "$WORK/pass.elisa" -filter checks
compare "filter suffix"       "$WORK/pass.elisa" -filter one
compare "filter no match"     "$WORK/pass.elisa" -filter zzzz
compare "no @test at all"     "$WORK/none.elisa"
compare "skipped"             "$WORK/skip.elisa"
compare "skipped, filtered"   "$WORK/skip.elisa" -filter skipped

# The failure path: status lines only (see the header).
compare_status_lines "panic"                "$WORK/panic.elisa"
compare_status_lines "panic, filtered out"  "$WORK/panic.elisa" -filter passes

# stage0 refuses -o; so must stage1.
reject=0
if bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit test -o "$WORK/out" "$WORK/pass.elisa" >/dev/null 2>&1; then
    echo "REJECT: -emit test accepted -o, stage0 refuses it"; reject=1
fi

# A program that does not ANALYSE must not be run: stage0 gates every semantic report
# mode, exits 1 and prints no test output at all.
cat > "$WORK/broken.elisa" <<'EOF'
@test
def checks() -> void:
    return

def bad() -> i64:
    return undefined_name()
EOF
"$ELISACORE_BIN" -emit test "$WORK/broken.elisa" </dev/null >/dev/null 2>&1; rc0=$?
bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit test "$WORK/broken.elisa" >/dev/null 2>&1; rc1=$?
if [ "$rc0" != "$rc1" ]; then
    echo "DIFF: rejected program — stage0 rc=$rc0, stage1 rc=$rc1"; differ=$((differ + 1))
else
    same=$((same + 1))
fi

echo "emit_test_run parity: $same identical, $differ divergent"
if [ "$differ" -ne 0 ] || [ "$reject" -ne 0 ]; then
    echo "emit_test_run parity FAILED"
    exit 1
fi
echo "emit_test_run parity OK"
