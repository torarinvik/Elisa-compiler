#!/usr/bin/env bash
# Void-function ensures must run on explicit return, value-form void return, and fallthrough.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/valid.elisa" <<'CASE'
def bump(value: mutable i64&) -> void:
    value <- value + 1

def explicit(value: mutable i64&, flag: bool) -> void:
    ensure value >= 0
    if flag:
        return
    value <- value + 1
    return bump(value)

def fallthrough(value: mutable i64&) -> void:
    ensure value >= 0
    value <- value + 1

def main() -> i32:
    mutable value: i64 = 0
    explicit(&value, true)
    explicit(&value, false)
    fallthrough(&value)
    return 0
CASE

cat > "$WORK/violated.elisa" <<'CASE'
def invalidate(value: mutable i64&) -> void:
    ensure value >= 0
    value <- -1
    return

def main() -> i32:
    mutable value: i64 = 0
    invalidate(&value)
    return 0
CASE

for level in 0 2; do
    ELISACORE_FORCE_CONTRACTS=1 bash "$ROOT/scripts/elisac_stage1.sh" -O"$level" -emit exe -o "$WORK/valid-$level" "$WORK/valid.elisa" >"$WORK/valid-$level.log" 2>&1 || {
        cat "$WORK/valid-$level.log" >&2
        echo "void ensure valid build failed at -O$level" >&2
        exit 1
    }
    "$WORK/valid-$level" || { echo "void ensure valid run failed at -O$level" >&2; exit 1; }
    ELISACORE_FORCE_CONTRACTS=1 bash "$ROOT/scripts/elisac_stage1.sh" -O"$level" -emit exe -o "$WORK/violated-$level" "$WORK/violated.elisa" >"$WORK/violated-$level.log" 2>&1 || {
        cat "$WORK/violated-$level.log" >&2
        echo "void ensure violation did not compile at -O$level" >&2
        exit 1
    }
    if "$WORK/violated-$level" >"$WORK/violated-$level.out" 2>&1; then
        echo "void ensure violation was not enforced at -O$level" >&2
        exit 1
    fi
    rg -Fq 'postcondition failed' "$WORK/violated-$level.out" || {
        cat "$WORK/violated-$level.out" >&2
        echo "void ensure violation lacked its contract failure at -O$level" >&2
        exit 1
    }
done

# Optimized builds erase runtime contracts by default. Verify that policy separately
# from the forced-contract checks above, even if the caller exported the override.
env -u ELISACORE_FORCE_CONTRACTS bash "$ROOT/scripts/elisac_stage1.sh" -O2 -emit exe -o "$WORK/violated-release" "$WORK/violated.elisa" >"$WORK/violated-release.log" 2>&1 || {
    cat "$WORK/violated-release.log" >&2
    echo 'void ensure release build failed' >&2
    exit 1
}
"$WORK/violated-release" || { echo 'optimized default unexpectedly enforced the void postcondition' >&2; exit 1; }

# Stage0 treats an empty override like an unset value, not an enabled switch.
ELISACORE_FORCE_CONTRACTS='' bash "$ROOT/scripts/elisac_stage1.sh" -O2 -emit exe -o "$WORK/violated-empty" "$WORK/violated.elisa" >"$WORK/violated-empty.log" 2>&1 || {
    cat "$WORK/violated-empty.log" >&2
    echo 'void ensure empty override build failed' >&2
    exit 1
}
"$WORK/violated-empty" || { echo 'empty override unexpectedly enabled the void postcondition' >&2; exit 1; }

echo 'void return ensure smoke OK: forced checks at O0/O2 and unchecked O2 defaults'
