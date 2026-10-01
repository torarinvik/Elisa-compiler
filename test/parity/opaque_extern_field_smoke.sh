#!/usr/bin/env bash
# A struct field whose type is a bare `extern Val` opaque handle (or a darray of one) must
# lower. The handle's CStr bits-1 alias used to be registered only in the late declaration
# pass, AFTER struct bodies were sized, so every function touching such a field was declined
# (stage0 accepts all of these) and passing the field as a call argument emitted invalid IR.
# register_opaque_extern_aliases now registers it before set_struct_bodies_from_metadata.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run_timeout.sh"
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISAC_STAGE1:-$ROOT/bin/elisac-stage1}"
DIR="$ROOT/test/fixtures/backend/opaque_extern_field"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/opaque_extern_field.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
fail=0; n=0
for f in "$DIR"/*.elisa; do
    n=$((n + 1))
    out="$TMP/$(basename "$f" .elisa).o"
    log="$(ELISA_DBG_DECLINE=1 elisa_run_timeout 60 "$BIN" -emit obj "$f" -o "$out" 2>&1)"
    rc=$?
    if [ $rc -ne 0 ] || [ ! -s "$out" ] || printf '%s\n' "$log" | grep -v 'warning:' | grep -qi 'declin\|DROPPED\|invalid LLVM'; then
        echo "FAIL $(basename "$f") rc=$rc"; printf '%s\n' "$log" | grep -v 'warning:' | head -5; fail=1
    fi
done
[ $fail -eq 0 ] && echo "opaque-extern-field OK ($n fixtures lower)" || exit 1
