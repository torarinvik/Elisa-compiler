"""Unsafe grant regression cases for cast and extern."""

CASES = {
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
