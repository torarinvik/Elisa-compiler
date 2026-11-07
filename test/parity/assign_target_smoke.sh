#!/usr/bin/env bash
# `<-` on a bare undeclared name reports the specific "undefined assignment
# target" (parity with stage0), distinct from a plain undefined reference. A
# `<-` on a declared-mutable local is fine. 0 findings across frontend+stdlib
# (whose globals all resolve within that self-contained set).
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "assign-target smoke FAIL: $1" >&2; exit 1; }

# 1. `<-` on an undeclared name is flagged specifically.
out=$(printf 'def f() -> i64:\n    x <- 5\n    return x\n' | "$RPT")
grep -q "undefined assignment target \"x\" (use = to introduce a new local; <- requires an existing mutable target)" <<< "$out" || fail "not flagged: $out"

# 2. `<-` on a declared-mutable local is fine.
out=$(printf 'def f() -> i64:\n    x: mutable i64 = 0\n    x <- 5\n    return x\n' | "$RPT")
grep -q "undefined assignment target" <<< "$out" && fail "false positive on declared mutable: $out"

# 2b. `<-` to an immutable const is rejected; to a `global mutable` is fine.
out=$(printf 'const K: i64 = 5\ndef f() -> i64:\n    K <- 10\n    return K\n' | "$RPT")
grep -q "cannot assign to immutable local \"K\"" <<< "$out" || fail "const write not flagged: $out"
out=$(printf 'global mutable G: i64 = 0\ndef f() -> i64:\n    G <- 10\n    return G\n' | "$RPT")
grep -q "cannot assign to immutable" <<< "$out" && fail "false positive on global mutable write: $out"

# 2c. assigning to a call result is an invalid assignment target.
out=$(printf 'def g() -> i64:\n    return 1\ndef f() -> i64:\n    g() <- 5\n    return 1\n' | "$RPT")
grep -q "invalid assignment target" <<< "$out" || fail "call-target assign not flagged: $out"

# 2d. a compound assign to an undeclared name is an undefined assignment target.
out=$(printf 'def f() -> i64:\n    y += 1\n    return 1\n' | "$RPT")
grep -q "undefined assignment target \"y\"" <<< "$out" || fail "compound-assign undeclared not flagged: $out"

# 2e. Read-only view and string-derived places cannot be written through.
out=$(printf 'def f(src: mutable darray[i64]&) -> void:\n    ro: view[i64] = src[0:2]\n    ro[0] <- 1\n' | "$RPT")
grep -q "cannot assign to read-only view index result" <<< "$out" || fail "readonly view index not flagged: $out"
out=$(printf 'def f(src: mutable darray[i64]&) -> void:\n    rw: mutable view[i64] = src[0:2]\n    rw[0] <- 1\n' | "$RPT")
grep -q "cannot assign to read-only view index result" <<< "$out" && fail "mutable view index false positive: $out"
out=$(printf 'def f(text: cstr[row], view: sview) -> void:\n    text[0] <- 1\n    view[0] <- 1\n    text.len <- 1\n' | "$RPT")
grep -q "cannot assign to string index" <<< "$out" || fail "string index not flagged: $out"
grep -q "cannot assign to string view index" <<< "$out" || fail "string view index not flagged: $out"
grep -q "field \"len\" is immutable" <<< "$out" || fail "string len field not flagged: $out"

# 2f. Writable capability cannot be laundered through a mutable view or loop binder.
out=$(printf 'def f(src: darray[i64]&) -> void:\n    v: mutable view[i64] = src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "mutable view provenance not flagged: $out"
out=$(printf 'def f(src: mutable darray[i64]&) -> void:\n    v: mutable view[i64] = src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view" <<< "$out" && fail "mutable source provenance false positive: $out"
out=$(printf 'def f(src: mutable darray[i64]&) -> void:\n    v: view[i64] = src[0:2]\n    for mutable e in v:\n        e <- e + 1\n' | "$RPT")
grep -q "mutable iteration requires a writable view" <<< "$out" || fail "readonly mutable iteration not flagged: $out"

# 2g. Parentheses and aliases must not hide a readonly slice source.
out=$(printf 'def f(src: darray[i64]&) -> void:\n    v: mutable view[i64] = ((src))[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "parenthesized readonly source not flagged: $out"
out=$(printf 'type Writable = mutable view[i64]\ndef f(src: darray[i64]&) -> void:\n    v: Writable = (src[0:2])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "mutable-view alias readonly source not flagged: $out"

# 2h. Rebinding an existing mutable view is checked, and mutable sources remain accepted.
out=$(printf 'def f(writable: mutable darray[i64]&, readonly: darray[i64]&) -> void:\n    v: mutable view[i64] = writable[0:2]\n    v <- readonly[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly mutable-view rebind not flagged: $out"
out=$(printf 'def f(left: mutable darray[i64]&, right: mutable darray[i64]&) -> void:\n    v: mutable view[i64] = left[0:2]\n    v <- right[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "mutable-view rebind false positive: $out"

# 2i. Element mutability comes from the indexed element type, not the outer container.
out=$(printf 'def f(rows: mutable darray[view[i64]]&) -> void:\n    v: mutable view[i64] = rows[0][0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "nested readonly view source not flagged: $out"
out=$(printf 'def f(rows: mutable darray[mutable view[i64]]&) -> void:\n    v: mutable view[i64] = rows[0][0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "nested mutable view source false positive: $out"

# 2j. Shadowed names restore the outer binding's provenance when a block exits.
out=$(printf 'def f(src: darray[i64]&, writable: mutable darray[i64]&) -> void:\n    if true:\n        src: mutable darray[i64]& = writable\n    v: mutable view[i64] = src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "outer readonly source lost after shadow scope: $out"

# 2k. Struct field construction, reassignment, and indexed projection use the field's
# original annotation, including nested mutable qualifiers.
out=$(printf 'struct Holder:\n    bytes: mutable view[i64]\ndef f(src: darray[i64]&) -> void:\n    holder: Holder = Holder{bytes: src[0:2]}\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice in mutable-view field constructor not flagged: $out"
out=$(printf 'struct Holder:\n    bytes: mutable view[i64]\ndef f(holder: mutable Holder&, src: darray[i64]&) -> void:\n    holder.bytes <- src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly mutable-view field rebind not flagged: $out"
out=$(printf 'module Data:\n    struct Holder:\n        bytes: mutable view[i64]\ndef f(src: darray[i64]&) -> void:\n    holder: Data::Holder = Data::Holder{bytes: src[0:2]}\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice in qualified mutable-view field constructor not flagged: $out"
out=$(printf 'struct Store:\n    views: mutable darray[mutable view[i64]]\ndef f(store: mutable Store&, src: darray[i64]&) -> void:\n    store.views[0] <- src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly indexed mutable-view field rebind not flagged: $out"
out=$(printf 'struct Store:\n    rows: mutable darray[mutable darray[i64]]\ndef f(store: Store&) -> void:\n    v: mutable view[i64] = store.rows[0][0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "mutable nested field source false positive: $out"

# 2l. Const globals reject; a writable global array remains a valid backing source.
out=$(printf 'const Values: i64[3] = [1, 2, 3]\ndef f() -> void:\n    v: mutable view[i64] = Values[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "const global slice source not flagged: $out"
out=$(printf 'global mutable Values: array[i64, 3] = [1, 2, 3]\ndef f() -> void:\n    v: mutable view[i64] = Values[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "writable global array source false positive: $out"

# 2m. Expression catch arms still walk local view initializers and restore their bindings.
out=$(printf 'error Failure:\n    Nope\ndef produce(src: mutable darray[i64]&) -> mutable view[i64] error[Failure]:\n    return src[0:2]\ndef f(writable: mutable darray[i64]&, readonly: darray[i64]&) -> void:\n    v: mutable view[i64] = catch produce(writable):\n        ok:\n            ok\n        Failure.Nope:\n            hidden: mutable view[i64] = readonly[0:2]\n            hidden\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly mutable-view initializer in catch arm not flagged: $out"
out=$(printf 'error Failure:\n    Nope\ndef produce(src: mutable darray[i64]&) -> mutable view[i64] error[Failure]:\n    return src[0:2]\ndef f(writable: mutable darray[i64]&) -> void:\n    v: mutable view[i64] = catch produce(writable):\n        ok:\n            ok\n        Failure.Nope:\n            hidden: mutable view[i64] = writable[0:2]\n            hidden\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "writable mutable-view initializer in catch arm false positive: $out"

# 2n. Mutable-view function boundaries preserve the backing source capability.
out=$(printf 'def leak(src: darray[i64]&) -> mutable view[i64]:\n    return src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice returned as mutable view not flagged: $out"
out=$(printf 'def leak(src: mutable darray[i64]&) -> mutable view[i64]:\n    return src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "writable mutable-view return false positive: $out"
out=$(printf 'def take(v: mutable view[i64]) -> void:\n    pass\ndef f(src: darray[i64]&) -> void:\n    take(src[0:2])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice passed to mutable-view parameter not flagged: $out"
out=$(printf 'def take(v: mutable view[i64]) -> void:\n    pass\ndef f(src: mutable darray[i64]&) -> void:\n    take(src[0:2])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "writable slice passed to mutable-view parameter false positive: $out"
out=$(printf 'def readonly(src: darray[i64]&) -> view[i64]:\n    return src[0:2]\ndef take(v: mutable view[i64]) -> void:\n    pass\ndef f(src: darray[i64]&) -> void:\n    take((readonly(src)))\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly function result passed as mutable view not flagged: $out"
out=$(printf 'def writable(src: mutable darray[i64]&) -> mutable view[i64]:\n    return src[0:2]\ndef take(v: mutable view[i64]) -> void:\n    pass\ndef f(src: mutable darray[i64]&) -> void:\n    take(writable(src))\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "validated writable function result false positive: $out"

# 2o. Nested mutable views keep their capability through container literals and insertions.
out=$(printf 'def f(src: darray[i64]&) -> void:\n    views: mutable darray[mutable view[i64]] = [src[0:2]]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice in mutable-view darray literal not flagged: $out"
out=$(printf 'def f(src: darray[i64]&, views: mutable darray[mutable view[i64]]&) -> void:\n    views.push(src[0:2])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice pushed into mutable-view darray not flagged: $out"
out=$(printf 'def f(src: mutable darray[i64]&, views: mutable darray[mutable view[i64]]&) -> void:\n    views.push(src[0:2])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "writable slice pushed into mutable-view darray false positive: $out"
out=$(printf 'def f(src: darray[i64]&, views: mutable dict[cstr, mutable view[i64]]&) -> void:\n    views.put("x", src[0:2])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice put into mutable-view dict not flagged: $out"
out=$(printf 'def f(src: darray[i64]&, views: mutable dict[cstr, mutable view[i64]]) -> void:\n    views <- {"x": src[0:2]}\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice in mutable-view dict literal not flagged: $out"

# 2p. Generic view element projection preserves the inner mutability for dictionary values
# and fixed arrays whose extent is named by a constant.
out=$(printf 'const N: usize = 3\ndef f(src: darray[i64]&, rows: mutable dict[cstr, view[i64]]&) -> void:\n    v: mutable view[i64] = rows["x"][0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly nested dict view not flagged: $out"
out=$(printf 'const N: usize = 3\ndef f(src: i64[N]) -> void:\n    v: mutable view[i64] = src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "named-extent readonly fixed-array source not flagged: $out"
out=$(printf 'const N: usize = 3\ndef f(src: mutable i64[N]) -> void:\n    v: mutable view[i64] = src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "named-extent mutable fixed-array source false positive: $out"

# 2q. Match expression branches are checked independently, including writable controls.
out=$(printf 'def f(flag: bool, readonly: darray[i64]&, writable: mutable darray[i64]&) -> void:\n    v: mutable view[i64] = match flag:\n        true: readonly[0:2]\n        false: writable[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly Match result arm not flagged: $out"
out=$(printf 'def f(flag: bool, left: mutable darray[i64]&, right: mutable darray[i64]&) -> void:\n    v: mutable view[i64] = match flag:\n        true: left[0:2]\n        false: right[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "writable Match result arms false positive: $out"

# `extend` copies each source element into the receiver; preserve nested view capability.
out=$(printf 'def f(readonly: darray[view[i64]]&, writable: mutable darray[mutable view[i64]]&) -> void:\n    target: mutable darray[mutable view[i64]] = []\n    target.extend(readonly)\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly view elements extended into mutable-view darray not flagged: $out"
out=$(printf 'def f(src: darray[i64]&, target: mutable darray[mutable view[i64]]&) -> void:\n    target.extend([src[0:2] for _ in 0..<1])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice comprehension extended into mutable-view darray not flagged: $out"
out=$(printf 'def f(writable: mutable darray[mutable view[i64]]&) -> void:\n    target: mutable darray[mutable view[i64]] = []\n    target.extend(writable)\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "writable view elements extended into mutable-view darray false positive: $out"
out=$(printf 'def readonly(src: darray[i64]&) -> view[i64]:\n    return src[0:2]\ndef f(src: darray[i64]&) -> void:\n    views: mutable darray[mutable view[i64]] = [readonly(src) for _ in 0..<1]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly call result in mutable-view comprehension not flagged: $out"
out=$(printf 'def readonly(src: darray[i64]&) -> view[i64]:\n    return src[0:2]\ndef writable(src: mutable darray[i64]&) -> mutable view[i64]:\n    return src[0:2]\ndef f(flag: bool, src: darray[i64]&, dst: mutable darray[i64]&) -> void:\n    v: mutable view[i64] = writable(dst) if flag else readonly(src)\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly function result in conditional mutable-view value not flagged: $out"

# Cross-module aliases keep the declaring module while nested view types are checked.
out=$(printf 'module Store:\n    type Writable = mutable view[i64]\n    type Bank = mutable darray[Writable]\ndef take(bank: Store::Bank) -> void:\n    pass\ndef f(src: darray[i64]&) -> void:\n    take([src[0:2]])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly nested view through cross-module aliases not flagged: $out"
out=$(printf 'module Store:\n    type Writable = mutable view[i64]\n    struct Bank:\n        views: mutable darray[Writable]\ndef f(bank: mutable Store::Bank&, src: darray[i64]&) -> void:\n    bank.views.push(src[0:2])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly nested view through cross-module field alias not flagged: $out"
out=$(printf 'module Store:\n    type Writable = mutable view[i64]\n    type Pair = (Writable, Writable)\ndef take(pair: Store::Pair) -> void:\n    pass\ndef f(src: darray[i64]&) -> void:\n    take((src[0:1], src[1:2]))\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly view through cross-module tuple alias not flagged: $out"
out=$(printf 'module Store:\n    type Writable = mutable view[i64]\n    type Bank = mutable darray[Writable]\ndef f(bank: Store::Bank&) -> void:\n    for view in bank:\n        nested: mutable view[i64] = view[0:1]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "mutable view binder through cross-module alias false positive: $out"
out=$(printf 'module A:\n    type ReadView = view[i64]\n    struct Box:\n        items: mutable darray[ReadView]\nmodule B:\n    type Writable = mutable view[i64]\n    struct Box:\n        items: mutable darray[Writable]\ndef f(box: A::Box, target: mutable darray[mutable view[i64]]&) -> void:\n    target.extend(box.items)\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly view from colliding cross-module struct field not flagged: $out"
out=$(printf 'global mutable Views: mutable darray[view[i64]] = []\ndef f(target: mutable darray[mutable view[i64]]&) -> void:\n    target.extend(Views)\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly view elements from mutable global not flagged: $out"
out=$(printf 'global mutable Views: mutable darray[mutable view[i64]] = []\ndef f(src: darray[i64]&) -> void:\n    Views.push(src[0:2])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice pushed into mutable-view global not flagged: $out"
out=$(printf 'module Store:\n    global mutable Views: mutable darray[view[i64]] = []\ndef f(target: mutable darray[mutable view[i64]]&) -> void:\n    target.extend(Store::Views)\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly view elements from qualified mutable global not flagged: $out"
out=$(printf 'def readonly_views(src: darray[i64]&) -> darray[view[i64]]:\n    return [src[0:2]]\ndef f(src: darray[i64]&, target: mutable darray[mutable view[i64]]&) -> void:\n    target.extend(readonly_views(src)[0:1])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly call-result slice extended into mutable-view darray not flagged: $out"
out=$(printf 'struct Holder:\n    data: darray[i64]\nglobal mutable holder: Holder = Holder{data: []}\ndef f() -> void:\n    view: mutable view[i64] = holder.data[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice from global struct field not flagged: $out"
out=$(printf 'struct Holder:\n    data: mutable darray[i64]\nglobal mutable holder: Holder = Holder{data: []}\ndef f() -> void:\n    view: mutable view[i64] = holder.data[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "mutable slice from global struct field false positive: $out"
out=$(printf 'struct Holder:\n    views: mutable darray[mutable view[i64]]\nglobal mutable holder: Holder = Holder{views: []}\ndef f(src: darray[i64]&) -> void:\n    holder.views.push(src[0:2])\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice pushed through global struct field not flagged: $out"
out=$(printf 'global mutable current: mutable view[i64] = zeroed\ndef f(src: darray[i64]&) -> void:\n    current <- src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice assigned to global mutable view not flagged: $out"
out=$(printf 'global mutable current: mutable view[i64] = zeroed\ndef f(src: mutable darray[i64]&) -> void:\n    current <- src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "writable slice assigned to global mutable view false positive: $out"
out=$(printf 'module Views:\n    public:\n        global mutable current: mutable view[i64] = zeroed\ndef f(src: darray[i64]&) -> void:\n    Views::current <- src[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice assigned to qualified global mutable view not flagged: $out"
out=$(printf 'module First:\n    public:\n        global mutable Readonly: view[i64] = zeroed\nmodule Second:\n    public:\n        global mutable Readonly: mutable view[i64] = zeroed\nfrom First import Readonly\nfrom Second import Readonly\ndef f() -> void:\n    view: mutable view[i64] = Readonly\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "first selective import readonly view owner not selected: $out"
out=$(printf 'module First:\n    public:\n        global mutable Views: mutable darray[view[i64]] = []\nmodule Second:\n    public:\n        global mutable Views: mutable darray[mutable view[i64]] = []\nfrom First import Views\nfrom Second import Views\ndef f(target: mutable darray[mutable view[i64]]&) -> void:\n    target.extend(Views)\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "first selective import readonly view container owner not selected: $out"
out=$(printf 'global mutable Readonly: mutable view[i64] = zeroed\nmodule Provider:\n    public:\n        global mutable Readonly: view[i64] = zeroed\nfrom Provider import Readonly\ndef f() -> void:\n    view: mutable view[i64] = Readonly\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "selective import did not override root mutable-view global: $out"
out=$(printf 'module Parent:\n    public:\n        global mutable Readonly: view[i64] = zeroed\n    module Child:\n        def f() -> void:\n            view: mutable view[i64] = Readonly\nmodule Other:\n    public:\n        global mutable Readonly: mutable view[i64] = zeroed\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "Parent::Child did not resolve lexical Parent::Readonly over an external collision: $out"
out=$(printf 'module Installer:\n    module Provider:\n        public:\n            global mutable Readonly: view[i64] = zeroed\n    module Other:\n        public:\n            global mutable Readonly: mutable view[i64] = zeroed\n    from Provider import Readonly\n    from Other import Readonly\n    def f() -> void:\n        view: mutable view[i64] = Readonly\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "first nested selective import readonly owner not selected: $out"
out=$(printf 'module Data:\n    struct Holder:\n        data: darray[i64]\n    public:\n        global mutable holder: Holder = Holder{data: []}\nmodule Client:\n    struct Holder:\n        data: mutable darray[i64]\n    def f() -> void:\n        view: mutable view[i64] = Data::holder.data[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "readonly slice from qualified global struct field not flagged: $out"
out=$(printf 'struct Holder:\n    data: darray[i64]\nglobal mutable holder: Holder = Holder{data: []}\nmodule Other:\n    struct Holder:\n        data: mutable darray[i64]\n    global mutable holder: Holder = Holder{data: []}\nmodule Client:\n    def f() -> void:\n        view: mutable view[i64] = holder.data[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" || fail "root global projection lost to same-named module global: $out"
out=$(printf 'struct Holder:\n    data: darray[i64]\nglobal mutable holder: Holder = Holder{data: []}\nmodule LocalWins:\n    struct Holder:\n        data: mutable darray[i64]\n    global mutable holder: Holder = Holder{data: []}\n    def f() -> void:\n        view: mutable view[i64] = holder.data[0:2]\n' | "$RPT")
grep -q "cannot create a mutable view from a read-only source" <<< "$out" && fail "module-local global did not shadow root global: $out"

# 3. 0 findings across frontend + stdlib (self-contained resolution set).
#
# Scanned one DIRECTORY at a time, not one file at a time. A `global mutable` is declared in
# one part file and assigned in its siblings — they are all `include`d into the same unit, so
# per-file scanning reports an "undefined assignment target" for every such write even though
# the unit resolves. Per-directory is both closer to what the compiler actually sees and still
# catches the thing this guards: a `<-` to a name nothing in the unit declares.
t=0
while IFS= read -r d; do
  c=$(cat "$d"/*.elisa 2>/dev/null | "$RPT" 2>/dev/null | grep -cE "undefined assignment target|invalid assignment target" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -type d | sort)
[ "$t" -eq 0 ] || fail "$t assignment-target findings across frontend+stdlib"

echo "assign-target smoke OK: flags undeclared <-/compound, call-target, const write; silent on declared-mutable + global mutable; 0 across frontend+stdlib"
