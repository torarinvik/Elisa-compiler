#!/usr/bin/env bash
# Compare Stage0 and Stage1 inferred Global rows while keeping accesses and calls under
# explicit local grants. Focused authority tests cover default diagnostic enforcement.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE
STAGE1_BIN="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$REPO_ROOT/build/runtime/elisacore_runtime.o}"
export STAGE1_BIN RUNTIME_OBJ
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
ROW_REPORT_OBJ="$WORK/mutable_global_authority_report.o"
ROW_REPORT="$WORK/mutable_global_authority_report"
ROW_REPORT_LD_FLAGS=()
case "$(uname -s)" in
    Linux) ROW_REPORT_LD_FLAGS=(-no-pie) ;;
    Darwin) ROW_REPORT_LD_FLAGS=(-Wl,-undefined,dynamic_lookup) ;;
esac
bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit obj -O2 -permissive \
    -o "$ROW_REPORT_OBJ" "$REPO_ROOT/test/parity/mutable_global_authority_report.elisa"
clang -O2 "${ROW_REPORT_LD_FLAGS[@]}" "$ROW_REPORT_OBJ" "$RUNTIME_OBJ" "$REPO_ROOT/test/parity/profile_hooks.c" -o "$ROW_REPORT"

stage0_globals() {
    "$ELISACORE_BIN" -emit semantic "$1" \
        | awk '
            /^func / { fn = $2; sub(/^.*\./, "", fn) }
            /fact_snapshot:.*required_effects=\[/ {
                effects = $0
                sub(/^.*required_effects=\[/, "", effects)
                sub(/\].*$/, "", effects)
                count = split(effects, parts, /, */)
                for (i = 1; i <= count; i++)
                    if (parts[i] == "Global.Read" || parts[i] == "Global.Write")
                        print fn " " parts[i]
            }
        ' | sort -u
}

stage1_globals() {
    local src="$WORK/rows-$(basename "$1")"
    { printf '# rows\n# permissive\n'; cat "$1"; } > "$src"
    "$ROW_REPORT" < "$src" \
        | awk '$1 == "R" && $2 != "" && ($3 == "Global.Read" || $3 == "Global.Write") { print $2 " " $3 }' \
        | sort -u
}

expect_agree() {
    local name="$1" s0 s1
    s0="$(stage0_globals "$2")"
    s1="$(stage1_globals "$2")"
    if [ -z "$s0" ]; then
        echo "global permissions smoke FAILED: $name produced no stage0 Global row" >&2
        failed=$((failed + 1))
        return
    fi
    if [ "$s0" != "$s1" ]; then
        printf 'global permissions smoke FAILED: %s\nStage0: %s\nStage1: %s\n' \
            "$name" "${s0//$'\n'/ | }" "${s1//$'\n'/ | }" >&2
        failed=$((failed + 1))
    fi
}

expect_same() {
    local name="$1" s0 s1
    s0="$(stage0_globals "$2")"
    s1="$(stage1_globals "$2")"
    if [ "$s0" != "$s1" ]; then
        printf 'global permissions smoke FAILED: %s\nStage0: %s\nStage1: %s\n' \
            "$name" "${s0//$'\n'/ | }" "${s1//$'\n'/ | }" >&2
        failed=$((failed + 1))
    fi
}

expect_stage1_row() {
    local name="$1" file="$2" expected="$3" rows
    rows="$(stage1_globals "$file")"
    if ! printf '%s\n' "$rows" | grep -F -x -q "$expected"; then
        printf 'global permissions smoke FAILED: %s missing row %s\nRows: %s\n' \
            "$name" "$expected" "${rows//$'\n'/ | }" >&2
        failed=$((failed + 1))
    fi
}

# --- agreeing corpus -----------------------------------------------------------------

# A reader needs Global.Read alone, a compound store needs both, a caller inherits what its
# callees need, and a `const` is not a global at all.
cat > "$WORK/reads_writes.elisa" <<'EOF'
global mutable hot: i32 = 0
global cold: i32 = 7
const frozen: i32 = 9

def bump() -> void:
    can Global{Read, Write}:
        hot <- hot + 1

def peek() -> i32:
    return cold

def frozen_peek() -> i32:
    return frozen

def caller() -> i32:
    can Global{Read, Write}:
        bump()
    can Global.Read:
        return peek() + frozen_peek()

def main() -> i64:
    can Global{Read, Write}:
        caller()
    return 0
EOF

# A plain store is Global.Write ALONE; a `can` block discharges the call site locally but
# still surfaces the effect upward, which is why `granted` is still reported to its caller.
cat > "$WORK/store_and_grant.elisa" <<'EOF'
global mutable hot: i32 = 0
global cold: i32 = 7

def store_only() -> void:
    can Global.Write:
        hot <- 1

def granted() -> i32:
    can Global.Read:
        return cold

def user() -> i32:
    can Global.Write:
        store_only()
    can Global.Read:
        return granted()

def main() -> i64:
    can Global{Read, Write}:
        user()
    return 0
EOF

# `trusted` only drops Unsafe tracking. Naming Global.Read or the whole Global family does not
# authorize mutable access or suppress its inferred rows; those accesses need local can grants.
cat > "$WORK/trusted_firewall.elisa" <<'EOF'
global mutable hot: i32 = 0
global cold: i32 = 7

def read_only_trusted() -> void:
    can Global{Read, Write}:
        trusted Global.Read:
            hot <- hot + 1

def whole_family_trusted() -> void:
    can Global{Read, Write}:
        trusted Global:
            hot <- hot + 1

def unrelated_trusted() -> i32:
    trusted Unsafe.Alias:
        return cold

def user() -> i32:
    can Global{Read, Write}:
        read_only_trusted()
        whole_family_trusted()
    return unrelated_trusted()

def main() -> i64:
    can Global{Read, Write}:
        user()
    return 0
EOF

# A store THROUGH a global (`slots[cursor] <- 1`) writes the global at the root and reads the
# one in the subscript; `cursor += 1` reads before it writes.
cat > "$WORK/rooted_store.elisa" <<'EOF'
global mutable slots: array[i32, 4] = [0, 0, 0, 0]
global mutable cursor: i32 = 0

def store_at() -> void:
    can Global{Read, Write}:
        slots[cursor] <- 1

def bump_compound() -> void:
    can Global{Read, Write}:
        cursor += 1

def user() -> void:
    can Global{Read, Write}:
        store_at()
        bump_compound()

def main() -> i64:
    can Global{Read, Write}:
        user()
    return 0
EOF

# Qualification preserves the callee identity, and a call in return position propagates
# the callee's effect through the wrapper.
cat > "$WORK/qualified_return.elisa" <<'EOF'
global mutable hot: i32 = 0

module Boxes:
    public:
        def build() -> i32:
            can Global.Read:
                return hot

def wrapper() -> i32:
    can Global.Read:
        return Boxes::build()

def main() -> i64:
    can Global.Read:
        wrapper()
    return 0
EOF

for case_file in reads_writes store_and_grant trusted_firewall rooted_store qualified_return; do
    expect_agree "$case_file" "$WORK/$case_file.elisa"
done

# Grouped permission clauses retain every member in both signatures and local grants.
# The separate mutable-global authority smoke rejects a one-member Global{Read} grant
# when the operation needs Global.Write.
cat > "$WORK/grouped_signature.elisa" <<'EOF'
global mutable hot: i32 = 0

def bump() -> void can[Global{Read, Write}]:
    can Global{Read, Write}:
        hot += 1

def caller() -> void:
    can Global{Read, Write}:
        bump()

def main() -> i64:
    can Global{Read, Write}:
        caller()
    return 0
EOF
# The exact local grant covers both grouped members, so there is no call-site warning.
# The grouped signature itself is also compiled by the focused effect-handler fixture.
expect_agree "grouped signature and local grant" "$WORK/grouped_signature.elisa"

cat > "$WORK/grouped_member_selective.elisa" <<'EOF'
global mutable hot: i32 = 0

def write_hot() -> void can[Global.Write]:
    can Global.Write:
        hot <- 1

def caller() -> void:
    can Global.Write:
        write_hot()

def main() -> i64:
    can Global.Write:
        caller()
    return 0
EOF
# The function and its caller both retain the member-specific write row.
expect_agree "grouped member remains selective" "$WORK/grouped_member_selective.elisa"
expect_stage1_row "grouped member remains selective" "$WORK/grouped_member_selective.elisa" "caller Global.Write"

# --- former divergences --------------------------------------------------------------

# A parameter named after a global is a parameter, not global storage.
cat > "$WORK/shadowed_param.elisa" <<'EOF'
global mutable hot: i32 = 0

def shadowed(hot: i32) -> i32:
    return hot

def main() -> i64:
    shadowed(1)
    return 0
EOF
expect_same "shadowed parameter" "$WORK/shadowed_param.elisa"

# The bracketed clause spelling must retain its member-selective meaning.
cat > "$WORK/bracketed_trusted.elisa" <<'EOF'
global mutable hot: i32 = 0

def read_only_trusted() -> void:
    can Global{Read, Write}:
        trusted [Global.Read]:
            hot <- hot + 1

def main() -> i64:
    can Global{Read, Write}:
        read_only_trusted()
    return 0
EOF
expect_agree "bracketed trusted clause" "$WORK/bracketed_trusted.elisa"

cat > "$WORK/rows.elisa" <<'EOF'
# rows
# permissive
global mutable hot: i32 = 0
global mutable slots: array[i32, 4] = [0, 0, 0, 0]
global mutable cursor: i32 = 0
global cold: i32 = 7
const frozen: i32 = 9

def reader() -> i32:
    can Global.Read:
        return hot

def writer() -> void:
    can Global.Write:
        hot <- 1

def increment() -> void:
    can Global{Read,Write}:
        hot <- hot + 1

def root_store() -> void:
    can Global{Read,Write}:
        slots[cursor] <- 1
        cursor += 1

def caller() -> i32:
    can Global{Read,Write}:
        writer()
        increment()
        root_store()
    can Global.Read:
        return reader() + cold + frozen

def main() -> i64:
    can Global{Read,Write}:
        caller()
    return 0
EOF

stage0_rows() {
    "$ELISACORE_BIN" -emit semantic "$WORK/rows.elisa" \
        | awk '
            /^func / { fn = $2; sub(/^.*\./, "", fn) }
            /fact_snapshot:.*required_effects=\[/ {
                effects = $0
                sub(/^.*required_effects=\[/, "", effects)
                sub(/\].*$/, "", effects)
                count = split(effects, parts, /, */)
                for (i = 1; i <= count; i++)
                    if (parts[i] == "Global.Read" || parts[i] == "Global.Write")
                        print fn " " parts[i]
            }
        ' | sort -u
}

stage1_rows() {
    "$ROW_REPORT" < "$WORK/rows.elisa" \
        | awk '$1 == "R" && $2 != "" && ($3 == "Global.Read" || $3 == "Global.Write") { print $2 " " $3 }' \
        | sort -u
}

stage0_rows_actual="$(stage0_rows)"
stage1_rows_actual="$(stage1_rows)"
if [ "$stage0_rows_actual" != "$stage1_rows_actual" ]; then
    printf 'global permissions smoke FAILED: inferred rows differ\nStage0:\n%s\nStage1:\n%s\n' \
        "$stage0_rows_actual" "$stage1_rows_actual" >&2
    failed=$((failed + 1))
fi
for expected in \
    'reader Global.Read' \
    'writer Global.Write' \
    'increment Global.Read' \
    'increment Global.Write' \
    'root_store Global.Read' \
    'root_store Global.Write' \
    'caller Global.Read' \
    'caller Global.Write' \
    'main Global.Read' \
    'main Global.Write'; do
    if ! printf '%s\n' "$stage1_rows_actual" | grep -F -x -q "$expected"; then
        echo "global permissions smoke FAILED: missing inferred row '$expected'" >&2
        failed=$((failed + 1))
    fi
done

if [ "$failed" -ne 0 ]; then
    echo "global permissions smoke FAILED: $failed check(s)" >&2
    exit 1
fi
echo "global permissions smoke OK: Stage0/Stage1 rows agree across local grants, propagation, trusted scopes, shadowing, and grouped effects" >&2
