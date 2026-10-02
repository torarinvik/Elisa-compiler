#!/usr/bin/env bash
# The parser's name stores (module_name_storage / machine_name_storage) hand out sviews
# that live as long as the AST. They used to reserve `tokens * 64 + 4096` once and then
# push freely: one long identifier costs far more than 64 bytes per token, so nested
# modules with long names grew the store past its reservation and moved the buffer under
# every name already handed out. name_store_make_room now retires a full buffer instead
# of growing it. This generates a source whose qualified names need ~60x the old
# reservation and checks every emitted symbol byte for byte.
set -u
root="$(cd "$(dirname "$0")/../.." && pwd)"
bin="${ELISAC_STAGE1:-$root/bin/elisac-stage1}"
work="$(mktemp -d "${TMPDIR:-/tmp}/name_store_growth.XXXXXX")"
trap 'rm -rf "$work"' EXIT
long="$(printf 'Q%.0s' $(seq 1 3000))"
{
    echo "module ${long}A:"
    for i in $(seq 0 39); do
        echo "    module ${long}${i}:"
        echo "        def f${i}() -> i32:"
        echo "            return ${i}"
    done
    echo "def main() -> i32:"
    echo "    return 0"
} > "$work/long.elisa"
if ! "$bin" -emit obj -o "$work/long.o" "$work/long.elisa" > "$work/err" 2>&1 || [ ! -s "$work/long.o" ]; then
    echo "name_store_growth_smoke FAIL: compile"; cat "$work/err"; exit 1
fi
for i in $(seq 0 39); do echo "_${long}A::${long}${i}.f${i}"; done | sort > "$work/want"
nm "$work/long.o" | awk '{print $NF}' | grep '::' | sed 's/^_*/_/' | sort > "$work/got"
if ! cmp -s "$work/want" "$work/got"; then
    echo "name_store_growth_smoke FAIL: qualified symbols differ ($(wc -l < "$work/got") emitted)"; exit 1
fi
echo "name_store_growth_smoke PASS (40 qualified names, $(wc -c < "$work/long.elisa") source bytes)"
