#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

check_rejected() {
    local source="$1"
    local message="$2"
    local output
    output="$(printf '%s' "$source" | "$RPT")"
    printf '%s\n' "$output" | grep -q "$message"
}

check_rejected $'struct Box:\n    value: mutable int\nextern maybe_box() -> Box&?\ndef bad() -> int:\n    box: Box&? = maybe_box()\n    return box.value\n' 'field access requires proven non-null reference'

check_rejected $'struct Box:\n    value: int\nextern maybe_box() -> Box&?\ndef bad() -> Box&:\n    box: Box&? = maybe_box()\n    return box.cast[Box&]\n' 'invalid cast from nullable reference'

check_rejected $'struct Box:\n    value: mutable int\nextern maybe_box() -> Box&?\ndef bad() -> int:\n    box: mutable Box&? = maybe_box()\n    alias: Box&? = box\n    if alias == null:\n        return 0\n    box <- null\n    return alias.value\n' 'field access requires proven non-null reference'

guarded=$(printf 'struct Box:\n    value: mutable int\nextern maybe_box() -> Box&?\ndef ok() -> int:\n    box: Box&? = maybe_box()\n    if box == null:\n        return 0\n    return box.value\n' | "$RPT")
printf '%s\n' "$guarded" | grep -q '^D 0$'

decorated_guard=$(printf 'struct Box:\n    value: int\n@guard_nonnull(box)\ndef has_box(box: Box&?) -> bool:\n    return box != null\ndef read(box: Box&?) -> int:\n    if not has_box(box):\n        return 0\n    return box.value\n' | "$RPT")
printf '%s\n' "$decorated_guard" | grep -q '^D 0$'

invalid_guard=$(printf '@guard_nonnull(text)\ndef has_text(text: sview) -> bool:\n    return true\n' | "$RPT")
printf '%s\n' "$invalid_guard" | grep -q '@guard_nonnull on function "has_text" requires a nullable reference or optional parameter, got sview'

echo "nullable flow smoke OK" >&2
