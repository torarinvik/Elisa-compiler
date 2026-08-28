#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule list-of-sets smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_list_sets.elisa"
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["roundtrip"]["parameters"] == [{"name": "values", "type": "darray[set[i64]]"}]
assert functions["roundtrip"]["return"] == "darray[set[i64]]"
assert functions["count"]["parameters"] == [{"name": "values", "type": "darray[set[i64]]"}]
assert functions["count"]["return"] == "i64"
assert functions["roundtrip_bundle"]["parameters"] == [{"name": "value", "type": "Bundle"}]
assert functions["roundtrip_bundle"]["return"] == "Bundle"
assert functions["roundtrip_map"]["parameters"] == [{"name": "value", "type": "dict[i64,darray[set[i64]]]"}]
assert functions["roundtrip_map"]["return"] == "dict[i64,darray[set[i64]]]"
assert manifest["structs"] == [{"name": "Bundle", "fields": [{"name": "values", "type": "darray[set[i64]]"}]}]
PY

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/list_sets.pyi" "$SOURCE" >/dev/null
grep -Fq 'def roundtrip(values: Sequence[Iterable[int]]) -> list[set[int]]: ...' "$WORK/list_sets.pyi"
grep -Fq 'def count(values: Sequence[Iterable[int]]) -> int: ...' "$WORK/list_sets.pyi"
grep -Fq 'def roundtrip_bundle(value: Bundle | BundleInput) -> Bundle: ...' "$WORK/list_sets.pyi"
grep -Fq 'def roundtrip_map(value: Mapping[int, Sequence[Iterable[int]]]) -> dict[int, list[set[int]]]: ...' "$WORK/list_sets.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/list_sets.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/list_sets$($PYTHON_BIN -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')" \
    "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import list_sets

payload = [{1, 2}, frozenset(), [3, 4]]
assert list_sets.roundtrip(payload) == [{1, 2}, set(), {3, 4}]
assert list_sets.count(payload) == 3
assert list_sets.roundtrip([]) == []
assert list_sets.roundtrip_bundle({"values": payload}) == {"values": [{1, 2}, set(), {3, 4}]}
assert list_sets.roundtrip_bundle({"values": []}) == {"values": []}
assert list_sets.roundtrip_map({1: payload, 2: [[5]]}) == {1: [{1, 2}, set(), {3, 4}], 2: [{5}]}
assert list_sets.roundtrip_map({}) == {}

for bad in ([{2**70}], [{"not an integer"}], [None], {1, 2}):
    try:
        list_sets.roundtrip(bad)
    except (TypeError, OverflowError, ValueError):
        pass
    else:
        raise AssertionError(f"invalid list-of-sets value accepted: {bad!r}")

try:
    list_sets.roundtrip([{2**70}])
except OverflowError as exc:
    assert "at path [0][1180591620717411303424]:" in str(exc)
    assert exc.function == "roundtrip"
    assert exc.parameter == "values"
    assert exc.path == "[0][1180591620717411303424]"
else:
    raise AssertionError("list-of-sets error did not include list and set paths")

for bad in ({"values": [{2**70}]}, {"values": [{"bad"}]}, {"values": [None]}):
    try:
        list_sets.roundtrip_bundle(bad)
    except (TypeError, OverflowError, ValueError):
        pass
    else:
        raise AssertionError(f"invalid struct list-of-sets value accepted: {bad!r}")

try:
    list_sets.roundtrip_map({1: [{2**70}]})
except OverflowError as exc:
    assert "at path [1][0][1180591620717411303424]:" in str(exc)
    assert exc.function == "roundtrip_map"
    assert exc.parameter == "value"
    assert exc.path == "[1][0][1180591620717411303424]"
else:
    raise AssertionError("dictionary list-of-sets error did not include all paths")

for bad in ({1: [{2**70}]}, {1: [{"bad"}]}, {1: None}, []):
    try:
        list_sets.roundtrip_map(bad)
    except (TypeError, OverflowError, ValueError):
        pass
    else:
        raise AssertionError(f"invalid dictionary list-of-sets value accepted: {bad!r}")

print("pymodule list-of-sets smoke OK")
PY
