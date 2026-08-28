#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for invalid_default in negative_unsigned out_of_range bad_escape; do
    if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
        -o "$WORK/$invalid_default.json" \
        "$ROOT/test/repro/pymodule_defaults_${invalid_default}.elisa" \
        >"$WORK/${invalid_default}.log" 2>&1; then
        echo "$invalid_default default unexpectedly accepted by pymodule" >&2
        exit 1
    fi
    grep -Fq 'only literal scalar/text or recursively literal container defaults' "$WORK/${invalid_default}.log"
done

for invalid_shape in error_struct_return error_fixed_array_return mutable_darray_ref unsupported_struct_list_element unsupported_struct_list_return unsupported_dict_struct_list; do
    if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
        -o "$WORK/$invalid_shape.json" \
        "$ROOT/test/repro/pymodule_${invalid_shape}.elisa" \
        >"$WORK/${invalid_shape}.log" 2>&1; then
        echo "$invalid_shape unexpectedly accepted by pymodule" >&2
        exit 1
    fi
done
grep -Fq 'does not support struct returns for error targets' "$WORK/error_struct_return.log"
grep -Fq 'does not support fixed-array returns for error targets' "$WORK/error_fixed_array_return.log"
grep -Fq 'does not support mutable darray references' "$WORK/mutable_darray_ref.log"
grep -Fq 'darray element contains an unsupported Python aggregate shape' "$WORK/unsupported_struct_list_element.log"
grep -Fq 'darray element contains an unsupported Python aggregate shape' "$WORK/unsupported_struct_list_return.log"
grep -Fq 'supports nested darray dictionary values up to eight levels' "$WORK/unsupported_dict_struct_list.log"

for invalid_shape in error_struct_return error_fixed_array_return mutable_darray_ref unsupported_struct_list_element unsupported_struct_list_return unsupported_dict_struct_list; do
    if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
        -o "$WORK/${invalid_shape}.c" \
        "$ROOT/test/repro/pymodule_${invalid_shape}.elisa" \
        >"$WORK/${invalid_shape}-c.log" 2>&1; then
        echo "$invalid_shape unexpectedly accepted by pymodule-c" >&2
        exit 1
    fi
done
grep -Fq 'darray element contains an unsupported Python aggregate shape' "$WORK/unsupported_struct_list_element-c.log"

echo "pymodule manifest-contract diagnostics OK"
