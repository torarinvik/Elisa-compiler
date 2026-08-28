#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! "$PYTHON_BIN" -c 'import sysconfig; raise SystemExit(0 if sysconfig.get_config_var("EXT_SUFFIX") else 1)' >/dev/null 2>&1; then
    echo "pymodule nested darrays smoke SKIP (Python extension toolchain unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_nested_darrays.elisa"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/nested_darrays.json" "$SOURCE" >/dev/null
"$PYTHON_BIN" - "$WORK/nested_darrays.json" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
rows = {row["name"]: row for row in manifest["functions"]}
assert rows["roundtrip"]["parameters"] == [{"name": "values", "type": "darray[darray[i64]]"}]
assert rows["roundtrip"]["return"] == "darray[darray[i64]]"
assert rows["count"]["return"] == "i64"
assert rows["roundtrip_deep"]["parameters"] == [{"name": "values", "type": "darray[darray[darray[darray[i64]]]]"}]
assert rows["roundtrip_deep"]["return"] == "darray[darray[darray[darray[i64]]]]"
assert rows["roundtrip_points"]["parameters"] == [{"name": "values", "type": "darray[darray[Point]]"}]
assert rows["roundtrip_points"]["return"] == "darray[darray[Point]]"
assert rows["roundtrip_points_deep"]["parameters"] == [{"name": "values", "type": "darray[darray[darray[Point]]]"}]
assert rows["roundtrip_points_deep"]["return"] == "darray[darray[darray[Point]]]"
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/nested_darrays.pyi" "$SOURCE" >/dev/null
grep -Fq 'def roundtrip(values: Sequence[Sequence[int]]) -> list[list[int]]: ...' "$WORK/nested_darrays.pyi"
grep -Fq 'def roundtrip_deep(values: Sequence[Sequence[Sequence[Sequence[int]]]]) -> list[list[list[list[int]]]]: ...' "$WORK/nested_darrays.pyi"
grep -Fq 'def roundtrip_points(values: Sequence[Sequence[Point | PointInput]]) -> list[list[Point]]: ...' "$WORK/nested_darrays.pyi"
grep -Fq 'def roundtrip_points_deep(values: Sequence[Sequence[Sequence[Point | PointInput]]]) -> list[list[list[Point]]]: ...' "$WORK/nested_darrays.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/nested_darrays.pyi"

# The recursive input helper takes a protective reference because its nested converter consumes
# the field object on failure.  It must release that reference on the successful path too.
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$WORK/nested_darrays.c" "$SOURCE" >/dev/null
grep -Fq 'Py_DECREF(field_obj); *destination = holder.value; return 0;' "$WORK/nested_darrays.c"

if ! command -v clang >/dev/null 2>&1 || ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    echo "pymodule nested darrays manifest/stub smoke OK (native build unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so -o "$WORK/nested_darrays$("$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')" "$SOURCE" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import nested_darrays
import sys

payload = [[1, 2, 3], [], [40, 50]]
assert nested_darrays.roundtrip(payload) == payload
assert nested_darrays.count(payload) == 3
payload_refcount = sys.getrefcount(payload)
for _ in range(100):
    nested_darrays.roundtrip(payload)
assert sys.getrefcount(payload) == payload_refcount
deep_payload = [[[[1], []], [[2, 3]]], [], [[[4]]]]
assert nested_darrays.roundtrip_deep(deep_payload) == deep_payload
points = [[{"x": 1, "label": "a"}], [], [{"x": 2, "label": "b\x00c"}]]
assert nested_darrays.roundtrip_points(points) == points
deep_points = [[[{"x": 1, "label": "a"}], []], [], [[{"x": 2, "label": "b\x00c"}]]]
assert nested_darrays.roundtrip_points_deep(deep_points) == deep_points

for bad in ([[1, "bad"]], [None], [[2**63]]):
    try:
        nested_darrays.roundtrip(bad)
    except (OverflowError, TypeError, ValueError) as exc:
        if bad == [[1, "bad"]]:
            assert exc.path == "[0][1]"
            assert "at path [0][1]" in str(exc)
    else:
        raise AssertionError(f"invalid nested value accepted: {bad!r}")

print("pymodule nested darrays smoke OK")
PY
