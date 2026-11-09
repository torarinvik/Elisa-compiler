"""Unsafe capability scope regression cases, group 1."""

CASES = {
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
    "closure may trusted-grant its own alias operation without propagation": (
        "# strict\n"
        "def get_ref[@r](x: mutable i64& @r) -> mutable i64& @r:\n    return x\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "def bad(x: mutable i64&) -> void:\n"
        "    callback: fn() -> void = fn():\n"
        "        alias: mutable i64& = get_ref(x)\n"
        "        trusted Unsafe.Alias:\n            pair(alias, x)\n"
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
    "line-zero generic owner does not suppress concrete unsafe check": (
        "# strict\n"
        "#line 0 generic_owner.elisa\n"
        "def phantom[T](value: T) -> void:\n    return\n"
        "#line 0 pair_owner.elisa\n"
        "def pair(a: mutable i64&, b: mutable i64&) -> void:\n    return\n"
        "#line 0 bad_owner.elisa\n"
        "def bad(x: mutable i64&) -> void:\n    pair(x, x)\n"
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
    "unsafe predicate call under exact local grant": (
        "# strict\n"
        "def unsafe_predicate() -> bool can[Unsafe.PointerCast]:\n    return true\n"
        "def caller() -> bool:\n"
        "    can Unsafe.PointerCast:\n        return unsafe_predicate()\n"
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
        "    mutable callback: fn() -> void can[Unsafe.PointerCast] = safe_api\n"
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
        "def unsafe_api2() -> void can[Unsafe.PointerCast]:\n    return\n"
        "def call() -> void:\n"
        "    mutable callback: fn() -> void can[Unsafe.PointerCast] = unsafe_api\n"
        "    callback <- unsafe_api2\n"
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
        "def bad() -> i64:\n    can Global.Read, Unsafe.MutableGlobal:\n        return hot\n"
        "def main() -> i64:\n    return 0\n",
        None,
    ),
    "mutable global requires Global.Read independently of Unsafe.MutableGlobal": (
        "# strict\n"
        "global mutable hot: i64 = 0\n"
        "def bad() -> i64:\n    can Unsafe.MutableGlobal:\n        return hot\n"
        "def main() -> i64:\n    return 0\n",
        "accesses a global mutable binding without Global.Read",
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
}
