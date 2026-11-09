"""Unsafe grant regression cases for pointer pattern."""

CASES = {
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
}
