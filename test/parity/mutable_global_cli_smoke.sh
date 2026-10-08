#!/usr/bin/env bash
# Default CLI enforcement and the explicit `-permissive` escape hatch for
# reads/writes of global mutable bindings. The reporter-only regression does
# not exercise driver flag propagation, so keep this at the real CLI boundary.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-mutable-global-cli.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

fail() { printf 'mutable global CLI smoke FAILED: %s\n' "$1" >&2; exit 1; }

cat >"$WORK/read.elisa" <<'EOF'
global mutable count: i64 = 0
def read_count() -> i64:
    return count
EOF

cat >"$WORK/write.elisa" <<'EOF'
global mutable count: i64 = 0
def write_count() -> void:
    count <- 1
EOF

cat >"$WORK/read_write.elisa" <<'EOF'
global mutable count: i64 = 0
def increment() -> void:
    count <- count + 1
EOF

cat >"$WORK/granted.elisa" <<'EOF'
global mutable count: i64 = 0
def read_count() -> i64:
    can Global.Read:
        return count
def write_count() -> void:
    can Global.Write:
        count <- 1
def increment() -> void:
    can Global{Read,Write}:
        count <- count + 1
EOF

check() {
    set +e
    output="$(bash "$WRAPPER" -emit check "$@" 2>&1)"
    status=$?
    set -e
}

check "$WORK/read.elisa"
[[ "$status" -eq 1 && "$output" == *"accesses a global mutable binding without Global.Read"* ]] \
    || fail "default read must require Global.Read (exit $status): $output"

check "$WORK/write.elisa"
[[ "$status" -eq 1 && "$output" == *"accesses a global mutable binding without Global.Write"* ]] \
    || fail "default write must require Global.Write (exit $status): $output"

check "$WORK/read_write.elisa"
[[ "$status" -eq 1 && "$output" == *"accesses a global mutable binding without Global.Read"* \
    && "$output" == *"accesses a global mutable binding without Global.Write"* ]] \
    || fail "read-modify-write must require both grants (exit $status): $output"

check "$WORK/granted.elisa"
[[ "$status" -eq 0 && -z "$output" ]] \
    || fail "exact read, write, and combined grants must pass (exit $status): $output"

check -permissive "$WORK/read.elisa"
[[ "$status" -eq 0 ]] || fail "-permissive must bypass a missing read grant (exit $status): $output"

check -permissive "$WORK/write.elisa"
[[ "$status" -eq 0 ]] || fail "-permissive must bypass a missing write grant (exit $status): $output"

check -permissive "$WORK/read_write.elisa"
[[ "$status" -eq 0 ]] || fail "-permissive must bypass missing read/write grants (exit $status): $output"

echo "mutable global CLI smoke OK: default read/write and read-modify-write enforcement, exact grants, and -permissive bypasses"
