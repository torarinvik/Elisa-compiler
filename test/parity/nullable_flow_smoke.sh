#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

check_rejected() {
    local source="$1"
    local message="$2"
    local output
    output="$(printf '%s' "$source" | "$RPT")"
    grep -q "$message" <<< "$output"
}

check_rejected $'struct Box:\n    value: mutable int\nextern maybe_box() -> Box&?\ndef bad() -> int:\n    box: Box&? = maybe_box()\n    return box.value\n' 'field access requires proven non-null reference'

check_rejected $'struct Box:\n    value: int\nextern maybe_box() -> Box&?\ndef bad() -> Box&:\n    box: Box&? = maybe_box()\n    return box.cast[Box&]\n' 'invalid cast from nullable reference'

check_rejected $'def bad(value: i64&?) -> i64:\n    value - 5\n' 'nullable reference "value" must be proven non-null before scalar use'
check_rejected $'def bad(value: i64&?) -> i64:\n    value + 1\n' 'nullable reference "value" must be proven non-null before scalar use'
check_rejected $'struct Box:\n    field: i64\ndef bad(box: Box&?) -> void:\n    box.field <- 1\n' 'field access requires proven non-null reference'
check_rejected $'def bad(values: darray[i64]&?) -> i64:\n    return values[0]\n' 'indexing requires proven non-null reference'
guarded_scalar=$(printf 'def ok(value: i64&?) -> i64:\n    if value == null:\n        return 0\n    return value + 1\n' | "$RPT")
grep -q 'operator requires numeric operands' <<< "$guarded_scalar"
check_rejected $'struct Box:\n    field: i64\ndef bad(box: Box&?, count: i64) -> i64:\n    while count > 0:\n        return box.field\n    return 0\n' 'field access requires proven non-null reference'
check_rejected $'struct Box:\n    field: i64\ndef bad(box: Box&?, branch: bool) -> i64:\n    if box == null:\n        return 0\n    if branch:\n        box: Box&? = null\n        return box.field\n    return 1\n' 'field access requires proven non-null reference'
check_rejected $'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\ndef bad(branch: bool) -> i64:\n    box: mutable Box&? = maybe_box()\n    if box == null:\n        return 0\n    if branch:\n        box <- null\n    return box.field\n' 'field access requires proven non-null reference'
check_rejected $'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\ndef bad(branch: bool) -> i64:\n    box: mutable Box&? = maybe_box()\n    if box == null:\n        return 0\n    while branch:\n        box <- null\n    return box.field\n' 'field access requires proven non-null reference'
check_rejected $'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\ndef bad(branch: bool) -> i64:\n    box: mutable Box&? = maybe_box()\n    if box == null:\n        return 0\n    can Abort.Panic:\n        box <- null\n    return box.field\n' 'field access requires proven non-null reference'
check_rejected $'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\ndef bad(branch: bool) -> i64:\n    box: mutable Box&? = maybe_box()\n    if box == null:\n        return 0\n    match branch:\n        true:\n            box <- null\n        _:\n            pass\n    return box.field\n' 'field access requires proven non-null reference'
check_rejected $'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\ndef bad() -> void:\n    box: Box&? = maybe_box()\n    match true:\n        _ if box.field == 1 and box != null:\n            pass\n        _:\n            pass\n' 'field access requires proven non-null reference'

guarded=$(printf 'struct Box:\n    value: mutable int\nextern maybe_box() -> Box&?\ndef ok() -> int:\n    box: Box&? = maybe_box()\n    if box == null:\n        return 0\n    return box.value\n' | "$RPT")
grep -q '^D 0$' <<< "$guarded"

guarded_loop=$(printf 'struct Box:\n    field: i64\ndef ok(box: Box&?) -> i64:\n    while box != null:\n        return box.field\n    return 0\n' | "$RPT")
grep -q '^D 0$' <<< "$guarded_loop"

# Keep a nested nullable-local/while regression covered; guarded field reads must
# not acquire nullable-proof errors across the loop scopes.
nullable_while_repro=$("$RPT" < "$REPO_ROOT/test/parity/fixtures/nullable_local_while.elisa")
if grep -q 'field access requires proven non-null reference' <<< "$nullable_while_repro"; then
    echo "nullable while repro lost its non-null proof" >&2
    exit 1
fi

# Rebinding the ROOT of a nullable copy revokes the copy's proof (stage0 rejects
# this; an earlier stage1 accepted it).
check_rejected $'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\ndef bad() -> i64:\n    box: mutable Box&? = maybe_box()\n    if box == null:\n        return 0\n    alias: Box&? = box\n    box <- null\n    return alias.field\n' 'field access requires proven non-null reference'
check_rejected $'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\nextern other_box() -> Box&\ndef bad() -> i64:\n    box: mutable Box&? = maybe_box()\n    if box == null:\n        return 0\n    alias: Box&? = box\n    box <- other_box()\n    return alias.field\n' 'field access requires proven non-null reference'

# A check through an alias proves its root ...
alias_proves_root=$(printf 'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\ndef ok() -> i64:\n    box: mutable Box&? = maybe_box()\n    alias: Box&? = box\n    if alias == null:\n        return 0\n    return box.field\n' | "$RPT")
grep -q '^D 0$' <<< "$alias_proves_root"
# ... but a check of the root says nothing about an earlier copy,
check_rejected $'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\ndef bad() -> i64:\n    box: mutable Box&? = maybe_box()\n    alias: Box&? = box\n    if box == null:\n        return 0\n    return alias.field\n' 'field access requires proven non-null reference'
# and rebinding the alias withdraws the proof it lent the root.
check_rejected $'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\nextern other_box() -> Box&\ndef bad() -> i64:\n    box: mutable Box&? = maybe_box()\n    alias: mutable Box&? = box\n    if alias == null:\n        return 0\n    alias <- other_box()\n    return box.field\n' 'field access requires proven non-null reference'

# Rebinding the copied name must not revoke the original binding's non-null fact.
rebound_alias=$(printf 'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\ndef ok() -> i64:\n    box: mutable Box&? = maybe_box()\n    if box == null:\n        return 0\n    alias: mutable Box&? = box\n    alias <- null\n    return box.field\n' | "$RPT")
grep -q '^D 0$' <<< "$rebound_alias"

# Rebinding an alias does revoke that alias's own fact.
check_rejected $'struct Box:\n    field: i64\nextern maybe_box() -> Box&?\ndef bad() -> i64:\n    box: mutable Box&? = maybe_box()\n    if box == null:\n        return 0\n    alias: mutable Box&? = box\n    alias <- null\n    return alias.field\n' 'field access requires proven non-null reference'

null_test=$(printf 'def ok(value: i64&?) -> bool:\n    value == null\n' | "$RPT")
grep -q '^D 0$' <<< "$null_test"

decorated_guard=$(printf 'struct Box:\n    value: int\n@guard_nonnull(box)\ndef has_box(box: Box&?) -> bool:\n    return box != null\ndef read(box: Box&?) -> int:\n    if not has_box(box):\n        return 0\n    return box.value\n' | "$RPT")
grep -q '^D 0$' <<< "$decorated_guard"

invalid_guard=$(printf '@guard_nonnull(text)\ndef has_text(text: sview) -> bool:\n    return true\n' | "$RPT")
grep -q '@guard_nonnull on function "has_text" requires a nullable reference or optional parameter, got sview' <<< "$invalid_guard"

echo "nullable flow smoke OK" >&2
