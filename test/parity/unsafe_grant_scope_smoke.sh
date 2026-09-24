#!/usr/bin/env bash
# Operation-specific unsafe capabilities must be lexical and must not leak across grants.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

python3 - "$STAGE1" "$REPO_ROOT" <<'PY'
import pathlib
import subprocess
import sys
import tempfile

stage1 = sys.argv[1]
repo = pathlib.Path(sys.argv[2])

cases = {
    "alias unrelated grant": (
        "# strict\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "def bad(x: mutable i64&) -> void:\n"
        "    can Memory.Allocate:\n        pair(x, x)\n"
        "def main() -> i64:\n    return 0\n",
        "mutable alias requires",
    ),
    "alias wrong unsafe capability": (
        "# strict\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "def bad(x: mutable i64&) -> void:\n"
        "    can Unsafe.PointerArithmetic:\n        pair(x, x)\n"
        "def main() -> i64:\n    return 0\n",
        "mutable alias requires",
    ),
    "alias exact grant": (
        "# strict\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "def bad(x: mutable i64&) -> void:\n"
        "    can Unsafe.Alias:\n        pair(x, x)\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "alias grant does not escape into closure": (
        "# strict\n"
        "def get_ref[@r](x: mutable i64& @r) -> mutable i64& @r:\n    return x\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "def bad(x: mutable i64&) -> void:\n"
        "    can Unsafe.Alias:\n"
        "        callback: fn() -> void = fn():\n"
        "            alias: mutable i64& = get_ref(x)\n"
        "            pair(alias, x)\n"
        "        callback()\n"
        "def main() -> i64:\n    return 0\n",
        "mutable alias requires",
    ),
    "closure may grant its own alias operation": (
        "# strict\n"
        "def get_ref[@r](x: mutable i64& @r) -> mutable i64& @r:\n    return x\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "def bad(x: mutable i64&) -> void:\n"
        "    callback: fn() -> void = fn():\n"
        "        alias: mutable i64& = get_ref(x)\n"
        "        can Unsafe.Alias:\n            pair(alias, x)\n"
        "    callback()\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "alias in match arm": (
        "# strict\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "def bad(x: mutable i64&, flag: i64) -> void:\n"
        "    match flag:\n"
        "        0:\n            pair(x, x)\n"
        "        1:\n            pass\n"
        "def main() -> i64:\n    return 0\n",
        "mutable alias requires",
    ),
    "alias in match arm under exact grant": (
        "# strict\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "def bad(x: mutable i64&, flag: i64) -> void:\n"
        "    match flag:\n"
        "        0:\n"
        "            can Unsafe.Alias:\n                pair(x, x)\n"
        "        1:\n            pass\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "local alias in match arm": (
        "# strict\n"
        "def get_ref[@r](x: mutable i64& @r) -> mutable i64& @r:\n    return x\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "def bad(x: mutable i64&, flag: i64) -> void:\n"
        "    alias: mutable i64& = get_ref(x)\n"
        "    match flag:\n"
        "        0:\n            pair(alias, x)\n"
        "        1:\n            pass\n"
        "def main() -> i64:\n    return 0\n",
        "mutable alias requires",
    ),
    "local alias in match arm under exact grant": (
        "# strict\n"
        "def get_ref[@r](x: mutable i64& @r) -> mutable i64& @r:\n    return x\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "def bad(x: mutable i64&, flag: i64) -> void:\n"
        "    alias: mutable i64& = get_ref(x)\n"
        "    match flag:\n"
        "        0:\n"
        "            can Unsafe.Alias:\n                pair(alias, x)\n"
        "        1:\n            pass\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "signature effect is not local authority": (
        "# strict\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "def bad(x: mutable i64&) -> void can[Unsafe.Alias]:\n    pair(x, x)\n"
        "def main() -> i64:\n    return 0\n",
        "mutable alias requires",
    ),
    "unsafe function call unrelated grant": (
        "# strict\n"
        "def unsafe_api() -> void can[Unsafe.PointerCast]:\n    return\n"
        "def wrapper() -> void:\n"
        "    can Memory.Allocate:\n        unsafe_api()\n"
        "def main() -> i64:\n"
        "    can Unsafe.PointerCast:\n        wrapper()\n"
        "    return 0\n",
        'call to "unsafe_api" requires can[Unsafe]',
    ),
    "unsafe function call wrong unsafe capability": (
        "# strict\n"
        "def unsafe_api() -> void can[Unsafe.PointerCast]:\n    return\n"
        "def wrapper() -> void:\n"
        "    can Unsafe.Alias:\n        unsafe_api()\n"
        "def main() -> i64:\n"
        "    can Unsafe.PointerCast:\n        wrapper()\n"
        "    return 0\n",
        'call to "unsafe_api" requires can[Unsafe]',
    ),
    "unsafe signature does not locally authorize its call": (
        "# strict\n"
        "def unsafe_api() -> void can[Unsafe.PointerCast]:\n    return\n"
        "def wrapper() -> void can[Unsafe.PointerCast]:\n"
        "    can Memory.Allocate:\n        unsafe_api()\n"
        "def main() -> i64:\n"
        "    can Unsafe.PointerCast:\n        wrapper()\n"
        "    return 0\n",
        'call to "unsafe_api" requires can[Unsafe]',
    ),
    "unsafe function call exact local grant": (
        "# strict\n"
        "def unsafe_api() -> void can[Unsafe.PointerCast]:\n    return\n"
        "def wrapper() -> void can[Unsafe.PointerCast]:\n"
        "    can Unsafe.PointerCast:\n        unsafe_api()\n"
        "def main() -> i64:\n"
        "    can Unsafe.PointerCast:\n        wrapper()\n"
        "    return 0\n",
        None,
    ),
    "contract expression unsafe call": (
        "# strict\n"
        "def unsafe_predicate() -> bool can[Unsafe.PointerCast]:\n    return true\n"
        "def caller() -> void:\n    requires unsafe_predicate()\n    return\n"
        "def main() -> i64:\n    return 0\n",
        'call to "unsafe_predicate" requires can[Unsafe]',
    ),
    "contract expression exact grant": (
        "# strict\n"
        "def unsafe_predicate() -> bool can[Unsafe.PointerCast]:\n    return true\n"
        "def caller() -> void:\n"
        "    can Unsafe.PointerCast:\n        requires unsafe_predicate()\n"
        "    return\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "unsafe function parameter call": (
        "# strict\n"
        "def call(callback: fn() -> void can[Unsafe.PointerCast]) -> void:\n    callback()\n"
        "def main() -> i64:\n    return 0\n",
        'call to "callback" requires can[Unsafe]',
    ),
    "unsafe function parameter unrelated grant": (
        "# strict\n"
        "def call(callback: fn() -> void can[Unsafe.PointerCast]) -> void:\n"
        "    can Memory.Allocate:\n        callback()\n"
        "def main() -> i64:\n    return 0\n",
        'call to "callback" requires can[Unsafe]',
    ),
    "unsafe function parameter exact grant": (
        "# strict\n"
        "def call(callback: fn() -> void can[Unsafe.PointerCast]) -> void:\n"
        "    can Unsafe.PointerCast:\n        callback()\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "unsafe local callback alias": (
        "# strict\n"
        "def call(callback: fn() -> void can[Unsafe.PointerCast]) -> void:\n"
        "    local_callback: fn() -> void can[Unsafe.PointerCast] = callback\n"
        "    local_callback()\n"
        "def main() -> i64:\n    return 0\n",
        'call to "local_callback" requires can[Unsafe]',
    ),
    "unsafe local callback alias unrelated grant": (
        "# strict\n"
        "def call(callback: fn() -> void can[Unsafe.PointerCast]) -> void:\n"
        "    local_callback: fn() -> void can[Unsafe.PointerCast] = callback\n"
        "    can Memory.Allocate:\n        local_callback()\n"
        "def main() -> i64:\n    return 0\n",
        'call to "local_callback" requires can[Unsafe]',
    ),
    "unsafe local callback alias exact grant": (
        "# strict\n"
        "def call(callback: fn() -> void can[Unsafe.PointerCast]) -> void:\n"
        "    local_callback: fn() -> void can[Unsafe.PointerCast] = callback\n"
        "    can Unsafe.PointerCast:\n        local_callback()\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "unsafe callback local rebind": (
        "# strict\n"
        "def safe_api() -> void:\n    return\n"
        "def unsafe_api() -> void can[Unsafe.PointerCast]:\n    return\n"
        "def call() -> void:\n"
        "    mutable callback: fn() -> void = safe_api\n"
        "    callback <- unsafe_api\n"
        "    callback()\n"
        "def main() -> i64:\n    return 0\n",
        'call to "callback" requires can[Unsafe]',
    ),
    "unsafe callback local rebind unrelated grant": (
        "# strict\n"
        "def safe_api() -> void:\n    return\n"
        "def unsafe_api() -> void can[Unsafe.PointerCast]:\n    return\n"
        "def call() -> void:\n"
        "    mutable callback: fn() -> void = safe_api\n"
        "    callback <- unsafe_api\n"
        "    can Memory.Allocate:\n        callback()\n"
        "def main() -> i64:\n    return 0\n",
        'call to "callback" requires can[Unsafe]',
    ),
    "unsafe callback local rebind exact grant": (
        "# strict\n"
        "def safe_api() -> void:\n    return\n"
        "def unsafe_api() -> void can[Unsafe.PointerCast]:\n    return\n"
        "def call() -> void:\n"
        "    mutable callback: fn() -> void = safe_api\n"
        "    callback <- unsafe_api\n"
        "    can Unsafe.PointerCast:\n        callback()\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "unsafe callback rebind branch join": (
        "# strict\n"
        "def safe_api() -> void:\n    return\n"
        "def unsafe_api() -> void can[Unsafe.PointerCast]:\n    return\n"
        "def call(flag: bool) -> void:\n"
        "    mutable callback: fn() -> void = safe_api\n"
        "    if flag:\n        callback <- unsafe_api\n"
        "    can Memory.Allocate:\n        callback()\n"
        "def main() -> i64:\n    return 0\n",
        'call to "callback" requires can[Unsafe]',
    ),
    "unchecked index unrelated grant": (
        "# strict\n"
        "def bad(xs: array[i64, 8], i: i64) -> i64:\n"
        "    can Memory.Allocate:\n        return xs[i]\n"
        "def main() -> i64:\n    return 0\n",
        "unchecked index requires",
    ),
    "unchecked index exact grant": (
        "# strict\n"
        "def bad(xs: array[i64, 8], i: i64) -> i64:\n"
        "    can Unsafe.UncheckedIndex:\n        return xs[i]\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "mutable global unrelated grant": (
        "# strict\n"
        "global mutable hot: i64 = 0\n"
        "def bad() -> i64:\n    can Memory.Allocate:\n        return hot\n"
        "def main() -> i64:\n    return 0\n",
        "mutable global access requires",
    ),
    "mutable global nested in array initializer": (
        "# strict\n"
        "global mutable hot: i64 = 0\n"
        "def bad() -> i64:\n"
        "    values: i64[1] = [hot]\n"
        "    return values[0]\n"
        "def main() -> i64:\n    return 0\n",
        "mutable global access requires",
    ),
    "mutable global exact grant": (
        "# strict\n"
        "global mutable hot: i64 = 0\n"
        "def bad() -> i64:\n    can Unsafe.MutableGlobal:\n        return hot\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic unrelated grant": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> i64:\n"
        "    can Unsafe.PointerCast:\n        pointer + offset\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic exact grant": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> i64:\n"
        "    can Unsafe.PointerArithmetic:\n        pointer + offset\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through local ref alias": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> u8&:\n"
        "    alias: u8& = pointer\n"
        "    return alias + offset\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through local ref alias exact grant": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> u8&:\n"
        "    alias: u8& = pointer\n"
        "    can Unsafe.PointerArithmetic:\n        return alias + offset\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic in value block tail": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> u8&:\n"
        "    result: u8& =\n"
        "        alias: u8& = pointer\n"
        "        alias + offset\n"
        "    return result\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic in value block tail exact grant": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> u8&:\n"
        "    can Unsafe.PointerArithmetic:\n"
        "        result: u8& =\n"
        "            alias: u8& = pointer\n"
        "            alias + offset\n"
        "        return result\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic with compound integer offset": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> u8&:\n"
        "    return pointer + (offset + 1)\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic with compound integer offset under unrelated grant": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> i64:\n"
        "    can Memory.Allocate:\n        pointer + (offset + 1)\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic with compound integer offset exact grant": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> i64:\n"
        "    can Unsafe.PointerArithmetic:\n        pointer + (offset + 1)\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic with local integer alias": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> u8&:\n"
        "    cursor: usize = offset\n"
        "    return pointer + (cursor + 1)\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through reference-returning call": (
        "# strict\n"
        "def identity(pointer: u8&) -> u8&:\n    return pointer\n"
        "def bad(pointer: u8&, offset: usize) -> u8&:\n"
        "    return identity(pointer) + (offset + 1)\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic with integer-returning call": (
        "# strict\n"
        "def step(offset: usize) -> usize:\n    return offset + 1\n"
        "def bad(pointer: u8&, offset: usize) -> u8&:\n"
        "    return pointer + step(offset)\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through typed struct fields": (
        "# strict\n"
        "struct PointerPair:\n    pointer: u8&\n    offset: usize\n"
        "def bad(pair: PointerPair&) -> u8&:\n"
        "    return pair.pointer + pair.offset\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through typed struct fields exact grant": (
        "# strict\n"
        "struct PointerPair:\n    pointer: u8&\n    offset: usize\n"
        "def bad(pair: PointerPair&) -> u8&:\n"
        "    can Unsafe.PointerArithmetic:\n        return pair.pointer + pair.offset\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through typed array element": (
        "# strict\n"
        "def bad(values: array[u8&, 4], offset: usize) -> u8&:\n"
        "    return values[0] + offset\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through typed array element exact grant": (
        "# strict\n"
        "def bad(values: array[u8&, 4], offset: usize) -> u8&:\n"
        "    can Unsafe.PointerArithmetic:\n        return values[0] + offset\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through reference-valued for binder": (
        "# strict\n"
        "def bad(values: darray[u8&], offset: usize) -> i64:\n"
        "    for pointer in values:\n        pointer + offset\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through reference-valued for binder exact grant": (
        "# strict\n"
        "def bad(values: darray[u8&], offset: usize) -> i64:\n"
        "    can Unsafe.PointerArithmetic:\n"
        "        for pointer in values:\n            pointer + offset\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through tuple-destructured for binders": (
        "# strict\n"
        "def bad(values: darray[(pointer: u8&, step: usize)]) -> i64:\n"
        "    for pointer, step in values:\n        pointer + step\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through tuple-destructured for binders exact grant": (
        "# strict\n"
        "def bad(values: darray[(pointer: u8&, step: usize)]) -> i64:\n"
        "    can Unsafe.PointerArithmetic:\n"
        "        for pointer, step in values:\n            pointer + step\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through dict-destructured for binders": (
        "# strict\n"
        "def bad(values: dict[u8&, usize]) -> i64:\n"
        "    for pointer, step in values:\n        pointer + step\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through dict-destructured for binders exact grant": (
        "# strict\n"
        "def bad(values: dict[u8&, usize]) -> i64:\n"
        "    can Unsafe.PointerArithmetic:\n"
        "        for pointer, step in values:\n            pointer + step\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic with range for index": (
        "# strict\n"
        "def bad(pointer: u8&, count: usize) -> i64:\n"
        "    for index in 0..<count:\n        pointer + index\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic with range for index exact grant": (
        "# strict\n"
        "def bad(pointer: u8&, count: usize) -> i64:\n"
        "    can Unsafe.PointerArithmetic:\n"
        "        for index in 0..<count:\n            pointer + index\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through reference-valued comprehension binder": (
        "# strict\n"
        "def bad(values: darray[u8&], offset: usize) -> i64:\n"
        "    result: darray[u8&] = [pointer + offset for pointer in values]\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through reference-valued comprehension binder exact grant": (
        "# strict\n"
        "def bad(values: darray[u8&], offset: usize) -> i64:\n"
        "    can Unsafe.PointerArithmetic:\n"
        "        result: darray[u8&] = [pointer + offset for pointer in values]\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic with range comprehension index": (
        "# strict\n"
        "def bad(pointer: u8&, count: usize) -> i64:\n"
        "    result: darray[u8&] = [pointer + index for index in 0..<count]\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic with range comprehension index exact grant": (
        "# strict\n"
        "def bad(pointer: u8&, count: usize) -> i64:\n"
        "    can Unsafe.PointerArithmetic:\n"
        "        result: darray[u8&] = [pointer + index for index in 0..<count]\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic ignores a shadowed reference name": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> i64:\n"
        "    if true:\n"
        "        pointer: usize = 0\n"
        "        pointer + offset\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic in match arm": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> i64:\n"
        "    match offset:\n"
        "        0:\n            pointer + offset\n"
        "        _:\n            pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic in match arm under unrelated grant": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> i64:\n"
        "    can Memory.Allocate:\n"
        "        match offset:\n"
        "            0:\n                pointer + offset\n"
        "            _:\n                pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic in match arm under exact grant": (
        "# strict\n"
        "def bad(pointer: u8&, offset: usize) -> i64:\n"
        "    match offset:\n"
        "        0:\n"
        "            can Unsafe.PointerArithmetic:\n"
        "                pointer + offset\n"
        "        _:\n            pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through enum payload match binding": (
        "# strict\n"
        "enum PointerOffset:\n    Offset(pointer: u8&, step: usize)\n    Empty\n"
        "def bad(value: PointerOffset) -> i64:\n"
        "    match value:\n"
        "        PointerOffset.Offset(pointer, step):\n            pointer + step\n"
        "        PointerOffset.Empty:\n            pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through enum payload match binding exact grant": (
        "# strict\n"
        "enum PointerOffset:\n    Offset(pointer: u8&, step: usize)\n    Empty\n"
        "def bad(value: PointerOffset) -> i64:\n"
        "    match value:\n"
        "        PointerOffset.Offset(pointer, step):\n"
        "            can Unsafe.PointerArithmetic:\n                pointer + step\n"
        "        PointerOffset.Empty:\n            pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through enum payload value match binding": (
        "# strict\n"
        "enum PointerOffset:\n    Offset(pointer: u8&, step: usize)\n    Empty\n"
        "def bad(value: PointerOffset, fallback: u8&) -> u8&:\n"
        "    return match value:\n"
        "        PointerOffset.Offset(pointer, step): pointer + step\n"
        "        PointerOffset.Empty: fallback\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through enum payload value match binding exact grant": (
        "# strict\n"
        "enum PointerOffset:\n    Offset(pointer: u8&, step: usize)\n    Empty\n"
        "def bad(value: PointerOffset, fallback: u8&) -> u8&:\n"
        "    can Unsafe.PointerArithmetic:\n"
        "        return match value:\n"
        "            PointerOffset.Offset(pointer, step): pointer + step\n"
        "            PointerOffset.Empty: fallback\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through enum payload match guard": (
        "# strict\n"
        "enum PointerOffset:\n    Offset(pointer: u8&, step: usize)\n    Empty\n"
        "def bad(value: PointerOffset) -> i64:\n"
        "    match value:\n"
        "        PointerOffset.Offset(pointer, step) if pointer + step == pointer:\n            pass\n"
        "        _:\n            pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through enum payload match guard exact grant": (
        "# strict\n"
        "enum PointerOffset:\n    Offset(pointer: u8&, step: usize)\n    Empty\n"
        "def bad(value: PointerOffset) -> i64:\n"
        "    can Unsafe.PointerArithmetic:\n        match value:\n"
        "            PointerOffset.Offset(pointer, step) if pointer + step == pointer:\n"
        "                pass\n"
        "            _:\n                pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through nested enum payload pattern": (
        "# strict\n"
        "enum InnerPointerOffset:\n    Offset(pointer: u8&, step: usize)\n    Empty\n"
        "enum OuterPointerOffset:\n    Wrapped(inner: InnerPointerOffset)\n    Empty\n"
        "def bad(value: OuterPointerOffset) -> i64:\n"
        "    match value:\n"
        "        OuterPointerOffset.Wrapped(InnerPointerOffset.Offset(pointer, step)):\n            pointer + step\n"
        "        OuterPointerOffset.Wrapped(_):\n            pass\n"
        "        OuterPointerOffset.Empty:\n            pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through nested enum payload pattern exact grant": (
        "# strict\n"
        "enum InnerPointerOffset:\n    Offset(pointer: u8&, step: usize)\n    Empty\n"
        "enum OuterPointerOffset:\n    Wrapped(inner: InnerPointerOffset)\n    Empty\n"
        "def bad(value: OuterPointerOffset) -> i64:\n"
        "    match value:\n"
        "        OuterPointerOffset.Wrapped(InnerPointerOffset.Offset(pointer, step)):\n"
        "            can Unsafe.PointerArithmetic:\n                pointer + step\n"
        "        OuterPointerOffset.Wrapped(_):\n            pass\n"
        "        OuterPointerOffset.Empty:\n            pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through tuple enum payload pattern": (
        "# strict\n"
        "enum TuplePointerOffset:\n    Offset(pair: (u8&, usize))\n    Empty\n"
        "def bad(value: TuplePointerOffset) -> i64:\n"
        "    match value:\n"
        "        TuplePointerOffset.Offset([pointer, step]):\n            pointer + step\n"
        "        TuplePointerOffset.Empty:\n            pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through tuple enum payload pattern exact grant": (
        "# strict\n"
        "enum TuplePointerOffset:\n    Offset(pair: (u8&, usize))\n    Empty\n"
        "def bad(value: TuplePointerOffset) -> i64:\n"
        "    match value:\n"
        "        TuplePointerOffset.Offset([pointer, step]):\n"
        "            can Unsafe.PointerArithmetic:\n                pointer + step\n"
        "        TuplePointerOffset.Empty:\n            pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through struct match pattern": (
        "# strict\n"
        "struct PointerOffsetFields:\n    pointer: u8&\n    step: usize\n"
        "def bad(value: PointerOffsetFields) -> i64:\n"
        "    match value:\n"
        "        PointerOffsetFields{pointer, step}:\n            pointer + step\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through struct match pattern exact grant": (
        "# strict\n"
        "struct PointerOffsetFields:\n    pointer: u8&\n    step: usize\n"
        "def bad(value: PointerOffsetFields) -> i64:\n"
        "    match value:\n"
        "        PointerOffsetFields{pointer, step}:\n"
        "            can Unsafe.PointerArithmetic:\n                pointer + step\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through referenced enum match pattern": (
        "# strict\n"
        "enum ReferencedPointerOffset:\n    Offset(pointer: u8&, step: usize)\n    Empty\n"
        "def bad(value: ReferencedPointerOffset&) -> i64:\n"
        "    match value:\n"
        "        ReferencedPointerOffset.Offset(pointer, step):\n            pointer + step\n"
        "        ReferencedPointerOffset.Empty:\n            pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through referenced enum match pattern exact grant": (
        "# strict\n"
        "enum ReferencedPointerOffset:\n    Offset(pointer: u8&, step: usize)\n    Empty\n"
        "def bad(value: ReferencedPointerOffset&) -> i64:\n"
        "    match value:\n"
        "        ReferencedPointerOffset.Offset(pointer, step):\n"
        "            can Unsafe.PointerArithmetic:\n                pointer + step\n"
        "        ReferencedPointerOffset.Empty:\n            pass\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer arithmetic through referenced struct match pattern": (
        "# strict\n"
        "struct ReferencedPointerOffset:\n    pointer: u8&\n    step: usize\n"
        "def bad(value: ReferencedPointerOffset&) -> i64:\n"
        "    match value:\n"
        "        ReferencedPointerOffset{pointer, step}:\n            pointer + step\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through referenced struct match pattern exact grant": (
        "# strict\n"
        "struct ReferencedPointerOffset:\n    pointer: u8&\n    step: usize\n"
        "def bad(value: ReferencedPointerOffset&) -> i64:\n"
        "    match value:\n"
        "        ReferencedPointerOffset{pointer, step}:\n"
        "            can Unsafe.PointerArithmetic:\n                pointer + step\n"
        "    return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "extern unrelated grant": (
        "# strict\n# unsafe\n"
        "extern foreign() -> i64\n"
        "def bad() -> i64:\n    can Memory.Allocate:\n        return foreign()\n"
        "def main() -> i64:\n    return 0\n",
        'call to "foreign" requires can[Unsafe]',
    ),
    "extern exact grant": (
        "# strict\n# unsafe\n"
        "extern foreign() -> i64\n"
        "def bad() -> i64:\n    can Unsafe.RawExtern:\n        return foreign()\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "extern in match arm": (
        "# strict\n# unsafe\n"
        "extern foreign() -> i64\n"
        "def bad(flag: i64) -> i64:\n"
        "    match flag:\n"
        "        0:\n            return foreign()\n"
        "        1:\n            return 0\n"
        "        _:\n            return 0\n"
        "def main() -> i64:\n    return 0\n",
        'call to "foreign" requires can[Unsafe]',
    ),
    "extern in match arm under exact grant": (
        "# strict\n# unsafe\n"
        "extern foreign() -> i64\n"
        "def bad(flag: i64) -> i64:\n"
        "    match flag:\n"
        "        0:\n"
        "            can Unsafe.RawExtern:\n                return foreign()\n"
        "        1:\n            return 0\n"
        "        _:\n            return 0\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "pointer cast unrelated grant": (
        "# strict\n"
        "def bad(pointer: i64&) -> void:\n"
        "    can Memory.Allocate:\n        erased: void& = pointer.cast[void&]\n"
        "def main() -> i64:\n    return 0\n",
        "pointer cast requires",
    ),
    "pointer cast exact grant": (
        "# strict\n"
        "def bad(pointer: i64&) -> void:\n"
        "    can Unsafe.PointerCast:\n        erased: void& = pointer.cast[void&]\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "stale view unrelated nested grant": (
        "# strict\n# unsafe\n"
        "def bad(values: mutable darray[i64]&) -> i64:\n"
        "    window: view[i64] = values[0:values.count]\n"
        "    can Memory.Allocate:\n        values.push(1)\n"
        "    return window[0]\n"
        "def main() -> i64:\n    return 0\n",
        'call to "stale reference" requires can[Unsafe]',
    ),
    "stale view wrong unsafe capability": (
        "# strict\n# unsafe\n"
        "def bad(values: mutable darray[i64]&) -> i64:\n"
        "    window: view[i64] = values[0:values.count]\n"
        "    can Memory.Allocate:\n        values.push(1)\n"
        "    can Unsafe.PointerCast:\n        return window[0]\n"
        "def main() -> i64:\n    return 0\n",
        'call to "stale reference" requires can[Unsafe]',
    ),
    "stale view exact grant": (
        "# strict\n# unsafe\n"
        "def bad(values: mutable darray[i64]&) -> i64:\n"
        "    window: view[i64] = values[0:values.count]\n"
        "    can Memory.Allocate:\n        values.push(1)\n"
        "    can Unsafe.StaleRef:\n        return window[0]\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "buffer reinterpret needs separate capability": (
        "# strict\n"
        "def bad() -> void:\n"
        "    can Memory.Allocate:\n"
        "        buffer: mutable darray[u8] = []\n"
        "        buffer.push(0)\n"
        "        erased: static u8& = (&buffer[0]).cast[static u8&]\n"
        "def main() -> i64:\n    return 0\n",
        "buffer reinterpret cast requires",
    ),
    "pointer grant does not grant buffer reinterpret": (
        "# strict\n"
        "def bad() -> void:\n"
        "    can Memory.Allocate:\n"
        "        buffer: mutable darray[u8] = []\n"
        "        buffer.push(0)\n"
        "        can Unsafe.PointerCast:\n"
        "            erased: static u8& = (&buffer[0]).cast[static u8&]\n"
        "def main() -> i64:\n    return 0\n",
        "buffer reinterpret cast requires",
    ),
    "buffer grant does not grant pointer cast": (
        "# strict\n"
        "def bad() -> void:\n"
        "    can Memory.Allocate:\n"
        "        buffer: mutable darray[u8] = []\n"
        "        buffer.push(0)\n"
        "        can Unsafe.BufferReinterpret:\n"
        "            erased: static u8& = (&buffer[0]).cast[static u8&]\n"
        "def main() -> i64:\n    return 0\n",
        "pointer cast requires",
    ),
    "buffer reinterpret exact pair": (
        "# strict\n"
        "def bad() -> void:\n"
        "    can Memory.Allocate:\n"
        "        buffer: mutable darray[u8] = []\n"
        "        buffer.push(0)\n"
        "        can Unsafe.PointerCast, Unsafe.BufferReinterpret:\n"
        "            erased: static u8& = (&buffer[0]).cast[static u8&]\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "buffer reference parameter still needs buffer capability": (
        "# strict\n# unsafe\n"
        "def bad(buffer: mutable darray[u8]&) -> void:\n"
        "    can Memory.Allocate:\n"
        "        buffer.push(0)\n"
        "        can Unsafe.PointerCast:\n"
        "            erased: static u8& = (&buffer[0]).cast[static u8&]\n"
        "def main() -> i64:\n    return 0\n",
        "buffer reinterpret cast requires",
    ),
    "buffer reference parameter exact capability pair": (
        "# strict\n# unsafe\n"
        "def bad(buffer: mutable darray[u8]&) -> void:\n"
        "    can Memory.Allocate:\n"
        "        buffer.push(0)\n"
        "        can Unsafe.PointerCast, Unsafe.BufferReinterpret:\n"
        "            erased: static u8& = (&buffer[0]).cast[static u8&]\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
}

with tempfile.TemporaryDirectory(prefix="elisa-unsafe-grants-") as temp:
    directory = pathlib.Path(temp)
    for name, (source, expected) in cases.items():
        path = directory / (name.replace(" ", "_") + ".elisa")
        path.write_text(source)
        result = subprocess.run(
            [stage1, "-emit", "interpret", "-o", "/dev/null", str(path)],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=90,
        )
        output = result.stdout
        if result.returncode not in (0, 1):
            raise SystemExit(f"{name}: compiler failed ({result.returncode})\n{output}")
        if expected is None and result.returncode != 0:
            raise SystemExit(f"{name}: expected an accepted program, compiler exited {result.returncode}\n{output}")
        if expected is None and any(
            message in output
            for message in (
                "mutable alias requires",
                "unchecked index requires",
                "mutable global access requires",
                "pointer arithmetic requires",
                'call to "foreign" requires can[Unsafe]',
                "pointer cast requires",
                "buffer reinterpret cast requires",
                'call to "stale reference" requires can[Unsafe]',
                'call to "unsafe_api" requires can[Unsafe]',
                'call to "unsafe_predicate" requires can[Unsafe]',
                'call to "callback" requires can[Unsafe]',
                'call to "local_callback" requires can[Unsafe]',
            )
        ):
            raise SystemExit(f"{name}: exact grant was rejected\n{output}")
        if expected is not None and expected not in output:
            raise SystemExit(f"{name}: expected {expected!r}\n{output}")

print(f"unsafe grant scope smoke OK: {len(cases)} unrelated, exact, and signature-effect cases")
PY
