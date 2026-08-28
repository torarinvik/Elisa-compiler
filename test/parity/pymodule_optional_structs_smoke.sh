#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
PYTHON312_BIN="${PYTHON312_BIN:-/opt/homebrew/bin/python3.12}"
PYTHON312_CONFIG="${PYTHON312_CONFIG:-/opt/homebrew/bin/python3.12-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule optional structs smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/optional_structs.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_optional_structs.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import optional_structs
from dataclasses import dataclass
from types import SimpleNamespace

assert optional_structs.Options.__module__ == "optional_structs"
assert optional_structs.Options.__required_keys__ == frozenset()
assert optional_structs.Options.__optional_keys__ == frozenset({"signed", "ratio", "enabled", "label", "text", "payload"})
assert optional_structs.OptionsInput is optional_structs.Options

@dataclass
class OptionsInput:
    signed: int

empty = {
    "signed": None,
    "ratio": None,
    "enabled": None,
    "label": None,
    "text": None,
    "payload": None,
}
assert optional_structs.roundtrip(empty) == empty
assert optional_structs.roundtrip({}) == empty
assert optional_structs.roundtrip(SimpleNamespace(signed=-7)) == {
    "signed": -7,
    "ratio": None,
    "enabled": None,
    "label": None,
    "text": None,
    "payload": None,
}
assert optional_structs.roundtrip(OptionsInput(-8)) == {
    "signed": -8,
    "ratio": None,
    "enabled": None,
    "label": None,
    "text": None,
    "payload": None,
}

marker = {"source": "python"}
present = {
    "signed": -42,
    "ratio": 1.25,
    "enabled": False,
    "label": "ready",
    "text": "hello\x00world",
    "payload": marker,
}
result = optional_structs.roundtrip(present)
assert result == present
assert result["payload"] is marker
assert result["text"] == "hello\x00world"

class Ephemeral:
    def __getattr__(self, name):
        values = {"signed": -9, "ratio": 2.5, "enabled": True, "label": "fresh-label", "text": "fresh\x00text", "payload": None}
        value = values[name]
        return "".join([value]) if isinstance(value, str) else value

ephemeral = optional_structs.roundtrip(Ephemeral())
assert ephemeral["label"] == "fresh-label"
assert ephemeral["text"] == "fresh\x00text"
assert optional_structs.roundtrip({**present, "text": b"bytes"})["text"] == "bytes"

for profile, expected in [
    ({**present, "label": "bad\x00label"}, ValueError),
    ({**present, "enabled": 1}, TypeError),
    ({**present, "signed": 1.5}, TypeError),
]:
    try:
        optional_structs.roundtrip(profile)
    except expected:
        pass
    else:
        raise AssertionError(f"expected {expected.__name__} for invalid optional struct field")

print("pymodule optional structs smoke OK")
PY

# Python 3.12's stdlib TypedDict implementation still references the module-global
# `NotRequired` while building a class.  Exercise the compiler's compatibility path
# with that attribute deliberately absent, including the no-typing_extensions case.
if [[ -x "$PYTHON312_BIN" && -x "$PYTHON312_CONFIG" ]]; then
    PY312_SUFFIX=$("$PYTHON312_CONFIG" --extension-suffix)
    mkdir -p "$WORK/py312"
    PYTHON_BIN="$PYTHON312_BIN" PYTHON_CONFIG="$PYTHON312_CONFIG" ELISA_CLANG="$CLANG" \
        bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
        -o "$WORK/py312/optional_structs${PY312_SUFFIX}" \
        "$ROOT/test/repro/pymodule_optional_structs.elisa" >/dev/null
    PYTHONPATH="$WORK/py312" "$PYTHON312_BIN" - <<'PY'
import typing

if hasattr(typing, "NotRequired"):
    delattr(typing, "NotRequired")
import optional_structs

assert not hasattr(typing, "NotRequired")
assert optional_structs.Options.__required_keys__ == frozenset()
assert optional_structs.roundtrip({"signed": 5}) == {
    "signed": 5,
    "ratio": None,
    "enabled": None,
    "label": None,
    "text": None,
    "payload": None,
}
print("pymodule optional structs Python 3.12 fallback OK")
PY
fi
