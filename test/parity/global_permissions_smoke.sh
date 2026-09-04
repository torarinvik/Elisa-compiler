#!/usr/bin/env bash
# The Global{Read, Write} permission family, differentially against stage0.
#
# stage0 infers the family from the body and propagates it to callers, but only ENFORCES it
# under `-Wglobals` (which `-Wstrict` implies). stage1 mirrors that dial as the `# globals`
# replay header. This gate holds three things:
#
#   1. OFF BY DEFAULT on both compilers. A program that reads and writes globals is silent
#      without the dial — the property that lets the family exist at all without rewriting
#      the `can` row of every program that touches a global.
#   2. BYTE-EXACT agreement under the dial over the corpus below: read-only vs read+write,
#      transitivity, `const` purity, the member-selective `trusted` firewall, an index-rooted
#      store, and a `can` grant at the call site.
#   3. Shadowing and bracketed effect-list syntax agree as well; both were former
#      divergences fixed alongside this gate.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

RPT="${ELISA_PARSE_REPORT:-$REPO_ROOT/build/parse_report}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0

# Location prefixes differ (stage0 spells a column range, stage1 an `L<line>` tag), so both
# sides are compared on the message text alone — the same normalisation diagnostics_diff.sh
# uses, and the reason a wording drift on either side still fails this gate.
norm() {
    sed -E -e 's/^[^:]*:[0-9]+:[0-9]+(-[0-9]+(:[0-9]+)?)?:[[:space:]]*//' \
           -e 's/^  L[0-9]+[[:space:]]*//' -e 's/[[:space:]]+/ /g' \
           -e 's/call to "[A-Za-z_][A-Za-z0-9_]*\.([A-Za-z_][A-Za-z0-9_]*)"/call to "\1"/' \
           -e 's/^ //' -e 's/ $//' | sort
}

stage0_globals() {   # $1 = source file, $2 = "on"|"off"
    # `set -u` and an EMPTY array do not mix on bash 3.2 (the macOS system shell), where
    # "${flags[@]}" is an unbound reference rather than zero words. Guard the expansion, or
    # the default-OFF half of this gate errors out and passes vacuously.
    local flags=()
    [ "$2" = "on" ] && flags=(-Wglobals)
    "$ELISACORE_BIN" ${flags[@]+"${flags[@]}"} -emit semantic "$1" 2>&1 >/dev/null \
        | grep -E ':[0-9]+:[0-9]+' | grep 'can\[Global' | norm
}

stage1_globals() {   # $1 = source file, $2 = "on"|"off"
    local src="$WORK/replay.elisa"
    if [ "$2" = "on" ]; then printf '# globals\n' > "$src"; else : > "$src"; fi
    cat "$1" >> "$src"
    "$RPT" < "$src" \
        | awk '/^D [0-9]+$/{d=1;next} d && /^  L[0-9]+ /{sub(/^  L[0-9]+ /,"");print}' \
        | grep 'can\[Global' | norm
}

expect_agree() {     # $1 = case name, $2 = source file
    local s0 s1
    s0="$(stage0_globals "$2" on)"
    s1="$(stage1_globals "$2" on)"
    if [ -z "$s0" ]; then
        echo "global permissions smoke FAILED: $1 produced no stage0 Global diagnostic to compare" >&2
        failed=$((failed + 1))
        return
    fi
    if [ "$s0" != "$s1" ]; then
        printf 'global permissions smoke FAILED: %s\nstage0: %s\nstage1: %s\n' \
            "$1" "${s0//$'\n'/ | }" "${s1//$'\n'/ | }" >&2
        failed=$((failed + 1))
    fi
}

expect_same() {      # $1 = case name, $2 = source file (agreement may be silence)
    local s0 s1
    s0="$(stage0_globals "$2" on)"
    s1="$(stage1_globals "$2" on)"
    if [ "$s0" != "$s1" ]; then
        printf 'global permissions smoke FAILED: %s\nstage0: %s\nstage1: %s\n' \
            "$1" "${s0//$'\n'/ | }" "${s1//$'\n'/ | }" >&2
        failed=$((failed + 1))
    fi
}

expect_silent_by_default() {   # $1 = case name, $2 = source file
    local s0 s1
    s0="$(stage0_globals "$2" off)"
    s1="$(stage1_globals "$2" off)"
    if [ -n "$s0" ] || [ -n "$s1" ]; then
        printf 'global permissions smoke FAILED: %s is not silent without the dial\nstage0: %s\nstage1: %s\n' \
            "$1" "${s0//$'\n'/ | }" "${s1//$'\n'/ | }" >&2
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
    hot <- hot + 1

def peek() -> i32:
    return cold

def frozen_peek() -> i32:
    return frozen

def caller() -> i32:
    bump()
    return peek() + frozen_peek()

def main() -> i64:
    caller()
    return 0
EOF

# A plain store is Global.Write ALONE; a `can` block discharges the call site locally but
# still surfaces the effect upward, which is why `granted` is still reported to its caller.
cat > "$WORK/store_and_grant.elisa" <<'EOF'
global mutable hot: i32 = 0
global cold: i32 = 7

def store_only() -> void:
    hot <- 1

def granted() -> i32:
    can Global.Read:
        return cold

def user() -> i32:
    store_only()
    return granted()

def main() -> i64:
    can Global{Read, Write}:
        user()
    return 0
EOF

# `trusted` is the firewall, and selective: naming Global.Read leaves Global.Write required,
# naming the bare family discharges both, and naming an unrelated family discharges neither.
cat > "$WORK/trusted_firewall.elisa" <<'EOF'
global mutable hot: i32 = 0
global cold: i32 = 7

def read_only_trusted() -> void:
    trusted Global.Read:
        hot <- hot + 1

def whole_family_trusted() -> void:
    trusted Global:
        hot <- hot + 1

def unrelated_trusted() -> i32:
    trusted Unsafe.Alias:
        return cold

def user() -> i32:
    read_only_trusted()
    whole_family_trusted()
    return unrelated_trusted()

def main() -> i64:
    user()
    return 0
EOF

# A store THROUGH a global (`slots[cursor] <- 1`) writes the global at the root and reads the
# one in the subscript; `cursor += 1` reads before it writes.
cat > "$WORK/rooted_store.elisa" <<'EOF'
global mutable slots: array[i32, 4] = [0, 0, 0, 0]
global mutable cursor: i32 = 0

def store_at() -> void:
    slots[cursor] <- 1

def bump_compound() -> void:
    cursor += 1

def user() -> void:
    store_at()
    bump_compound()

def main() -> i64:
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
            return hot

def wrapper() -> i32:
    return Boxes::build()

def main() -> i64:
    wrapper()
    return 0
EOF

for case_file in reads_writes store_and_grant trusted_firewall rooted_store qualified_return; do
    expect_agree "$case_file" "$WORK/$case_file.elisa"
    expect_silent_by_default "$case_file" "$WORK/$case_file.elisa"
done

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
    trusted [Global.Read]:
        hot <- hot + 1

def main() -> i64:
    read_only_trusted()
    return 0
EOF
expect_agree "bracketed trusted clause" "$WORK/bracketed_trusted.elisa"

if [ "$failed" -ne 0 ]; then
    echo "global permissions smoke FAILED: $failed check(s)" >&2
    exit 1
fi
echo "global permissions smoke OK: 7 agreeing cases (5 checked with dial on and off)" >&2
