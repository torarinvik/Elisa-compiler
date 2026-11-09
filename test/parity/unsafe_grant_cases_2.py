"""Unsafe capability scope regression cases, group 2."""

CASES = {
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
    "pointer arithmetic through module-qualified typed calls": (
        "# strict\n"
        "module PointerOps:\n"
        "    def as_pointer(value: u8&) -> u8&:\n        return value\n"
        "    def as_offset(value: usize) -> usize:\n        return value\n"
        "def bad(pointer: u8&, offset: usize) -> u8&:\n"
        "    return PointerOps::as_pointer(pointer) + PointerOps::as_offset(offset)\n"
        "def main() -> i64:\n    return 0\n",
        "pointer arithmetic requires",
    ),
    "pointer arithmetic through module-qualified typed calls exact grant": (
        "# strict\n"
        "module PointerOps:\n"
        "    def as_pointer(value: u8&) -> u8&:\n        return value\n"
        "    def as_offset(value: usize) -> usize:\n        return value\n"
        "def bad(pointer: u8&, offset: usize) -> u8&:\n"
        "    can Unsafe.PointerArithmetic:\n"
        "        return PointerOps::as_pointer(pointer) + PointerOps::as_offset(offset)\n"
        "def main() -> i64:\n    return 0\n",
        None,
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
}
