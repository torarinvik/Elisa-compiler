"""Unsafe capability scope regression cases, group 3."""

CASES = {
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
    "relocated view remains invalid under exact stale-ref grant": (
        "# strict\n# unsafe\n"
        "def bad(values: mutable darray[i64]&) -> i64:\n"
        "    window: view[i64] = values[0:values.count]\n"
        "    can Memory.Allocate:\n        values.push(1)\n"
        "    can Unsafe.StaleRef:\n        return window[0]\n"
        "def main() -> i64:\n    return 0\n",
        'view "window" cannot be used: storage dependency facts were invalidated by darray push of values',
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
    "grouped unsafe capability covers listed members": (
        "# strict\n# unsafe\n"
        "def unsafe_api() -> void can[Unsafe.PointerCast]:\n    return\n"
        "def memory_api() -> void can[Memory{Allocate, Release}]:\n    return\n"
        "def good() -> void:\n"
        "    can Unsafe{PointerCast, RawExtern}:\n"
        "        unsafe_api()\n"
        "    can Memory{Allocate, Release}:\n"
        "        memory_api()\n"
        "        value: i64 = 1\n"
        "def main() -> i64:\n"
        "    can Abort.Panic, Memory{Allocate, Release}, Unsafe{PointerCast, RawExtern}:\n"
        "        good()\n"
        "    return 0\n",
        None,
    ),
    "grouped unsafe capability remains member-selective": (
        "# strict\n# unsafe\n"
        "def unsafe_api() -> void can[Unsafe.PointerCast]:\n    return\n"
        "def bad() -> void:\n"
        "    can Unsafe{RawExtern}:\n"
        "        unsafe_api()\n"
        "def main() -> i64:\n    return 0\n",
        'call to "unsafe_api" requires can[Unsafe]',
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
