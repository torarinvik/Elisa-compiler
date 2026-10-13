#!/usr/bin/env python3
"""Mandatory mutable-global access grants in the real Stage1 semantic pipeline."""
import argparse
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("reporter")
args = parser.parse_args()
cases = [
    ("local function alias", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\ndef caller() -> i64:\n    callback = read_count\n    return callback()\n", {"Global.Read"}),
    ("local function alias grant", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\ndef caller() -> i64:\n    callback = read_count\n    can Global.Read:\n        return callback()\n", set()),
    ("conditional nested call", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\ndef caller(flag: bool) -> i64:\n    return read_count() if flag else 0\n", {"Global.Read"}),
    ("tuple nested call", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\ndef caller() -> (a: i64, b: i64):\n    return read_count(), 1\n", {"Global.Read"}),
    ("conditional call propagates", "global mutable count: i64 = 0\ndef read_count() -> i64:\n    can Global.Read:\n        return count\ndef middle(flag: bool) -> i64:\n    can Global.Read:\n        return read_count() if flag else 0\ndef caller() -> i64:\n    return middle(true)\n", {"Global.Read"}),
    ("conditional expression read", "global mutable count: i64 = 0\ndef read_count(flag: bool) -> i64:\n    return count if flag else 0\n", {"Global.Read"}),
    ("tuple expression read", "global mutable count: i64 = 0\ndef read_count() -> (a: i64, b: i64):\n    return count, 1\n", {"Global.Read"}),
    ("local-granted callee still propagates", "global mutable count: i64 = 0\ndef read_count() -> i64:\n    can Global.Read:\n        return count\ndef caller() -> i64:\n    return read_count()\n", {"Global.Read"}),
    ("three-level propagation", "global mutable count: i64 = 0\ndef read_count() -> i64:\n    can Global.Read:\n        return count\ndef middle() -> i64:\n    can Global.Read:\n        return read_count()\ndef caller() -> i64:\n    return middle()\n", {"Global.Read"}),
    ("index read propagates", "global mutable cursor: usize = 0\nglobal mutable slots: i64[4] = zeroed\ndef store() -> void:\n    can Global{Read,Write}:\n        slots[cursor] <- 1\ndef caller() -> void:\n    can Global.Write:\n        store()\n", {"Global.Read"}),
    ("transitive reader", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\ndef caller() -> i64:\n    return read_count()\n", {"Global.Read"}),
    ("transitive writer", "global mutable count: i64 = 0\ndef write_count() -> void can[Global.Write]:\n    count <- 1\ndef caller() -> void:\n    write_count()\n", {"Global.Write"}),
    ("transitive grant", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\ndef caller() -> i64:\n    can Global.Read:\n        return read_count()\n", set()),
    ("transitive wrong member", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\ndef caller() -> i64:\n    can Global.Write:\n        return read_count()\n", {"Global.Read"}),
    ("read before shadow", "global mutable count: i64 = 0\ndef read_count() -> i64:\n    previous: i64 = count\n    count: i64 = 7\n    return previous + count\n", {"Global.Read"}),
    ("inner shadow does not escape", "global mutable count: i64 = 0\ndef read_count(flag: bool) -> i64:\n    if flag:\n        count: i64 = 7\n    return count\n", {"Global.Read"}),
    ("read", "global mutable count: i64 = 0\ndef read_count() -> i64:\n    return count\n", {"Global.Read"}),
    ("write", "global mutable count: i64 = 0\ndef write_count() -> void:\n    count <- 1\n", {"Global.Write"}),
    ("read-modify-write", "global mutable count: i64 = 0\ndef bump() -> void:\n    count <- count + 1\n", {"Global.Read", "Global.Write"}),
    ("scalar self-update with only Global.Write", "global mutable count: i64 = 0\ndef bump() -> void:\n    can Global.Write:\n        count <- count + 1\n", {"Global.Read"}),
    ("indexed self-update with only Global.Write", "global mutable cursor: usize = 0\nglobal mutable slots: i64[4] = zeroed\ndef bump() -> void:\n    can Global.Write:\n        slots[cursor] <- slots[cursor] + 1\n", {"Global.Read"}),
    ("alias read-modify-write missing read", "global mutable count: i64 = 0\ndef bump() -> void:\n    can Global.Write:\n        reference: mutable i64& = &count\n        reference <- reference + 1\n", {"Global.Read"}),
    ("alias read-modify-write missing write", "global mutable count: i64 = 0\ndef bump() -> void:\n    can Global.Read:\n        reference: mutable i64& = &count\n        reference <- reference + 1\n", {"Global.Write"}),
    ("alias read-modify-write granted", "global mutable count: i64 = 0\ndef bump() -> void:\n    can Global{Read, Write}:\n        reference: mutable i64& = &count\n        reference <- reference + 1\n", set()),
    ("signature does not authorize read", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\n", set()),
    ("signature does not authorize write", "global mutable count: i64 = 0\ndef write_count() -> void can[Global.Write]:\n    count <- 1\n", set()),
    ("wrong member", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Write]:\n    return count\n", {"Global.Read"}),
    ("block grants", "global mutable count: i64 = 0\ndef bump() -> void:\n    can Global{Read,Write}:\n        count <- count + 1\n", set()),
    ("unrelated block", "global mutable count: i64 = 0\ndef read_count() -> i64:\n    can Memory.Allocate:\n        return count\n", {"Global.Read"}),
    ("immutable global", "global count: i64 = 7\ndef read_count() -> i64:\n    return count\n", set()),
    ("constant", "const count: i64 = 7\ndef read_count() -> i64:\n    return count\n", set()),
    ("parameter shadows", "global mutable count: i64 = 0\ndef read_count(count: i64) -> i64:\n    return count\n", set()),
    ("index target reads", "global mutable cursor: usize = 0\nglobal mutable slots: i64[4] = zeroed\ndef store() -> void:\n    slots[cursor] <- 1\n", {"Global.Read", "Global.Write"}),
    ("mutable reference write requires Global.Write", "global mutable counter: i64 = 0\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef main() -> void:\n    can Global.Read:\n        reference: mutable i64& = &counter\n        set_one(reference)\n", {"Global.Write"}),
    ("mutable reference write with both grants", "global mutable counter: i64 = 0\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef main() -> void:\n    can Global{Read, Write}:\n        reference: mutable i64& = &counter\n        set_one(reference)\n", set()),
    ("for reference binder requires Global.Write", "global mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> i64:\n    value <- 1\n    return 0\ndef main() -> void:\n    can Global.Read:\n        references: darray[mutable i64&] = [&hot]\n        for pointer in references:\n            set_one(pointer)\n", {"Global.Write"}),
    ("for reference binder accepts both grants", "global mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> i64:\n    value <- 1\n    return 0\ndef main() -> void:\n    can Global{Read, Write}:\n        references: darray[mutable i64&] = [&hot]\n        for pointer in references:\n            set_one(pointer)\n", set()),
    ("for borrowed-container reference binder requires Global.Write", "global mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef main(references: darray[mutable i64&]&) -> void:\n    can Global.Read:\n        for pointer in references:\n            set_one(pointer)\n", {"Global.Write"}),
    ("for borrowed-container reference binder accepts both grants", "global mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef main(references: darray[mutable i64&]&) -> void:\n    can Global{Read, Write}:\n        for pointer in references:\n            set_one(pointer)\n", set()),
    ("comprehension reference binder requires Global.Write", "global mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> i64:\n    value <- 1\n    return 0\ndef main() -> void:\n    can Global.Read:\n        references: darray[mutable i64&] = [&hot]\n        values: darray[i64] = [set_one(pointer) for pointer in references]\n", {"Global.Write"}),
    ("comprehension reference binder accepts both grants", "global mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> i64:\n    value <- 1\n    return 0\ndef main() -> void:\n    can Global{Read, Write}:\n        references: darray[mutable i64&] = [&hot]\n        values: darray[i64] = [set_one(pointer) for pointer in references]\n", set()),
    ("match payload reference binder requires Global.Write", "enum RefCarrier:\n    Wrap(value: mutable i64&)\nglobal mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef main() -> void:\n    seed: mutable i64 = 0\n    carrier: mutable RefCarrier = RefCarrier.Wrap(&seed)\n    can Global.Read:\n        carrier <- RefCarrier.Wrap(&hot)\n    can Global.Read:\n        match carrier:\n            RefCarrier.Wrap(pointer):\n                set_one(pointer)\n", {"Global.Write"}),
    ("match payload reference binder accepts both grants", "enum RefCarrier:\n    Wrap(value: mutable i64&)\nglobal mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef main() -> void:\n    seed: mutable i64 = 0\n    carrier: mutable RefCarrier = RefCarrier.Wrap(&seed)\n    can Global.Read:\n        carrier <- RefCarrier.Wrap(&hot)\n    can Global{Read, Write}:\n        match carrier:\n            RefCarrier.Wrap(pointer):\n                set_one(pointer)\n", set()),
    ("local enum constructor payload keeps local origin", "enum GrantOriginCarrier:\n    Wrap(pointer: mutable i64&)\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef local() -> void:\n    seed: mutable i64 = 0\n    carrier: GrantOriginCarrier = GrantOriginCarrier.Wrap(pointer: &seed)\n    match carrier:\n        GrantOriginCarrier.Wrap(pointer):\n            set_one(pointer)\n", set()),
    ("external enum payload binder requires Global.Write", "enum GrantOriginCarrier:\n    Wrap(pointer: mutable i64&)\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef write_carrier(carrier: GrantOriginCarrier) -> void:\n    can Global.Read:\n        match carrier:\n            GrantOriginCarrier.Wrap(pointer):\n                set_one(pointer)\n", {"Global.Write"}),
    ("external enum payload binder accepts both grants", "enum GrantOriginCarrier:\n    Wrap(pointer: mutable i64&)\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef write_carrier(carrier: GrantOriginCarrier) -> void:\n    can Global{Read, Write}:\n        match carrier:\n            GrantOriginCarrier.Wrap(pointer):\n                set_one(pointer)\n", set()),
    ("mixed enum payload origins require Global.Write", "enum GrantOriginPair:\n    Wrap(left: mutable i64&, right: mutable i64&)\nglobal mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef write_pair() -> void:\n    seed: mutable i64 = 0\n    carrier: GrantOriginPair = GrantOriginPair.Wrap(left: &seed, right: &hot)\n    can Global.Read:\n        match carrier:\n            GrantOriginPair.Wrap(left, right):\n                set_one(left)\n", {"Global.Write"}),
    ("local reference items stay local through tuple iteration", "def set_one(value: mutable i64&) -> i64:\n    value <- 1\n    return 0\ndef local() -> void:\n    seed: mutable i64 = 0\n    items: darray[(pointer: mutable i64&, step: usize)] = [(pointer: &seed, step: 0.usize())]\n    for item in items:\n        set_one(item.pointer)\n", set()),
    ("local reference items stay local through tuple comprehension", "def set_one(value: mutable i64&) -> i64:\n    value <- 1\n    return 0\ndef local() -> void:\n    seed: mutable i64 = 0\n    items: darray[(pointer: mutable i64&, step: usize)] = [(pointer: &seed, step: 0.usize())]\n    values: darray[i64] = [set_one(item.pointer) for item in items]\n", set()),
    ("local reference payloads stay local through tuple matching", "def set_one(value: mutable i64&) -> void:\n    value <- 1\ndef local() -> void:\n    seed: mutable i64 = 0\n    match (pointer: &seed, step: 0.usize()):\n        (pointer, _):\n            set_one(pointer)\n", set()),
    ("named tuple reference binder requires Global.Write", "global mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef write_item(items: darray[(pointer: mutable i64&, step: usize)]&) -> void:\n    can Global.Read:\n        for item in items:\n            set_one(item.pointer)\n", {"Global.Write"}),
    ("named tuple reference binder accepts both grants", "global mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef write_item(items: darray[(pointer: mutable i64&, step: usize)]&) -> void:\n    can Global{Read, Write}:\n        for item in items:\n            set_one(item.pointer)\n", set()),
    ("local nominal reference items stay local through iteration", "struct GrantOriginHolder:\n    pointer: mutable i64&\n    step: usize\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef local() -> void:\n    seed: mutable i64 = 0\n    items: darray[GrantOriginHolder] = [GrantOriginHolder{pointer: &seed, step: 0.usize()}]\n    for item in items:\n        set_one(item.pointer)\n", set()),
    ("nominal reference binder requires Global.Write", "struct GrantOriginHolder:\n    pointer: mutable i64&\n    step: usize\nglobal mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef write_item(items: darray[GrantOriginHolder]&) -> void:\n    can Global.Read:\n        for item in items:\n            set_one(item.pointer)\n", {"Global.Write"}),
    ("nominal reference binder accepts both grants", "struct GrantOriginHolder:\n    pointer: mutable i64&\n    step: usize\nglobal mutable hot: i64 = 7\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef write_item(items: darray[GrantOriginHolder]&) -> void:\n    can Global{Read, Write}:\n        for item in items:\n            set_one(item.pointer)\n", set()),
    ("local nominal reference binder stays local through match", "struct GrantOriginMatchHolder:\n    pointer: mutable i64&\n    step: usize\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef local() -> void:\n    seed: mutable i64 = 0\n    holder: GrantOriginMatchHolder = GrantOriginMatchHolder{pointer: &seed, step: 0.usize()}\n    match holder:\n        GrantOriginMatchHolder{pointer: pointer}:\n            set_one(pointer)\n", set()),
    ("nominal match reference binder requires Global.Write", "struct GrantOriginMatchHolder:\n    pointer: mutable i64&\n    step: usize\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef write_item(holder: GrantOriginMatchHolder) -> void:\n    can Global.Read:\n        match holder:\n            GrantOriginMatchHolder{pointer: pointer}:\n                set_one(pointer)\n", {"Global.Write"}),
    ("nominal match reference binder accepts both grants", "struct GrantOriginMatchHolder:\n    pointer: mutable i64&\n    step: usize\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef write_item(holder: GrantOriginMatchHolder) -> void:\n    can Global{Read, Write}:\n        match holder:\n            GrantOriginMatchHolder{pointer: pointer}:\n                set_one(pointer)\n", set()),
    ("nominal reference origin does not taint scalar siblings", "struct GrantOriginSiblingHolder:\n    pointer: mutable i64&\n    step: usize\ndef read_step(holder: GrantOriginSiblingHolder) -> usize:\n    return holder.step\n", set()),
    ("omitted default reference field keeps aggregate origin unknown", "global mutable hot: i64 = 7\nstruct GrantOriginDefaultHolder:\n    pointer: mutable i64& = &hot\n    local: mutable i64&\ndef set_one(value: mutable i64&) -> void:\n    value <- 1\ndef write_default() -> void:\n    seed: mutable i64 = 0\n    items: darray[GrantOriginDefaultHolder] = [GrantOriginDefaultHolder{local: &seed}]\n    can Global.Read:\n        for item in items:\n            set_one(item.pointer)\n", {"Global.Write"}),
    ("mutable reference rebind cannot carry Global.Read past grant scope", "global mutable hot: i64 = 7\ndef read_after_rebind() -> i64:\n    seed: mutable i64 = 1\n    reference: mutable i64& = &seed\n    can Global{Read,Write}:\n        reference <- &hot\n    return reference\n", {"Global.Read"}),
    ("mutable reference rebind cannot carry Global.Write past grant scope", "global mutable hot: i64 = 7\ndef write_after_rebind() -> i64:\n    seed: mutable i64 = 1\n    reference: mutable i64& = &seed\n    can Global{Read,Write}:\n        reference <- &hot\n    reference <- 2\n    return seed\n", {"Global.Write"}),
    ("mutable reference rebind uses grants at each access", "global mutable hot: i64 = 7\ndef write_after_rebind() -> i64:\n    seed: mutable i64 = 1\n    reference: mutable i64& = &seed\n    can Global{Read,Write}:\n        reference <- &hot\n    can Global.Write:\n        reference <- 2\n    return seed\n", set()),
    ("conditional reference binder preserves Global.Write origin", "global mutable hot: i64 = 7\ndef write_after_condition() -> i64:\n    reference: mutable i64&? = null\n    can Global.Write:\n        reference <- &hot\n    can Global.Read:\n        if reference is alias:\n            alias <- 2\n    return 0\n", {"Global.Write"}),
    ("aggregate reference field read requires Global.Read", "struct GrantRefBox:\n    item: mutable i64&\nglobal mutable hot: i64 = 7\ndef read_after_aggregate_rebind() -> i64:\n    seed: mutable i64 = 1\n    box: mutable GrantRefBox = GrantRefBox{item: &seed}\n    can Global{Read,Write}:\n        box.item <- &hot\n    return box.item[0.usize()]\n", {"Global.Read"}),
    ("aggregate reference field write requires Global.Write", "struct GrantRefBox:\n    item: mutable i64&\nglobal mutable hot: i64 = 7\ndef write_after_aggregate_rebind() -> i64:\n    seed: mutable i64 = 1\n    box: mutable GrantRefBox = GrantRefBox{item: &seed}\n    can Global{Read,Write}:\n        box.item <- &hot\n    box.item[0.usize()] <- 2\n    return seed\n", {"Global.Write"}),
    ("aggregate reference field write uses grants at each access", "struct GrantRefBox:\n    item: mutable i64&\nglobal mutable hot: i64 = 7\ndef write_after_aggregate_rebind() -> i64:\n    seed: mutable i64 = 1\n    box: mutable GrantRefBox = GrantRefBox{item: &seed}\n    can Global{Read,Write}:\n        box.item <- &hot\n    can Global.Write:\n        box.item[0.usize()] <- 2\n    return seed\n", set()),
    ("mutable record field read grant", "struct GrantRecord:\n    value: mutable i64\nglobal mutable record: GrantRecord = GrantRecord{value: 0}\ndef read_record() -> i64:\n    can Global.Read:\n        return record.value\n", set()),
    ("mutable record field write grant", "struct GrantRecord:\n    value: mutable i64\nglobal mutable record: GrantRecord = GrantRecord{value: 0}\ndef write_record() -> void:\n    can Global.Write:\n        record.value <- 1\n", set()),
    ("mutable record field read missing grant", "struct GrantRecord:\n    value: mutable i64\nglobal mutable record: GrantRecord = GrantRecord{value: 0}\ndef read_record() -> i64:\n    return record.value\n", {"Global.Read"}),
    ("mutable record field write wrong grant", "struct GrantRecord:\n    value: mutable i64\nglobal mutable record: GrantRecord = GrantRecord{value: 0}\ndef write_record() -> void:\n    can Global.Read:\n        record.value <- 1\n", {"Global.Write"}),
    ("generic handled effect write propagates", "global mutable counter: i64 = 0\neffect Tick[T]:\n    def put(value: T) -> void\nhandler static Sink() for Tick[i64]:\n    def put(value: i64) -> void:\n        can Global.Write:\n            counter <- value\ndef forward[T](value: T) -> void can[Tick[T]]:\n    can Global.Write:\n        Tick[T].put(value)\ndef caller() -> void:\n    can Tick[i64] with Sink:\n        forward(1)\n", {"Global.Write"}),
    ("generic handled effect write grant", "global mutable counter: i64 = 0\neffect Tick[T]:\n    def put(value: T) -> void\nhandler static Sink() for Tick[i64]:\n    def put(value: i64) -> void:\n        can Global.Write:\n            counter <- value\ndef forward[T](value: T) -> void can[Tick[T]]:\n    can Global.Write:\n        Tick[T].put(value)\ndef caller() -> void:\n    can Global.Write:\n        can Tick[i64] with Sink:\n            forward(1)\n", set()),
    ("generic handled effect read propagates", "global mutable counter: i64 = 0\neffect Tick[T]:\n    def get() -> T\nhandler static Source() for Tick[i64]:\n    def get() -> i64:\n        can Global.Read:\n            return counter\ndef forward[T]() -> T can[Tick[T]]:\n    can Global.Read:\n        return Tick[T].get()\ndef caller() -> i64:\n    can Tick[i64] with Source:\n        return forward()\n", {"Global.Read"}),
    ("generic handled effect read grant", "global mutable counter: i64 = 0\neffect Tick[T]:\n    def get() -> T\nhandler static Source() for Tick[i64]:\n    def get() -> i64:\n        can Global.Read:\n            return counter\ndef forward[T]() -> T can[Tick[T]]:\n    can Global.Read:\n        return Tick[T].get()\ndef caller() -> i64:\n    can Global.Read:\n        can Tick[i64] with Source:\n            return forward()\n", set()),
    ("qualified module global read missing grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\ndef read_hits() -> i64:\n    return Counters::hits\n", {"Global.Read"}),
    ("qualified module global read grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\ndef read_hits() -> i64:\n    can Global.Read:\n        return Counters::hits\n", set()),
    ("qualified module global write missing grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\ndef write_hits() -> void:\n    Counters::hits <- 8\n", {"Global.Write"}),
    ("qualified module global write grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\ndef write_hits() -> void:\n    can Global.Write:\n        Counters::hits <- 8\n", set()),
    ("using module alias global read missing grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\nusing Counters as C\ndef read_hits() -> i64:\n    return C::hits\n", {"Global.Read"}),
    ("using module alias global read grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\nusing Counters as C\ndef read_hits() -> i64:\n    can Global.Read:\n        return C::hits\n", set()),
    ("using module alias global write missing grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\nusing Counters as C\ndef write_hits() -> void:\n    C::hits <- 8\n", {"Global.Write"}),
    ("using module alias global write grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\nusing Counters as C\ndef write_hits() -> void:\n    can Global.Write:\n        C::hits <- 8\n", set()),
    ("selective module global read missing grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\nfrom Counters import hits\ndef read_hits() -> i64:\n    return hits\n", {"Global.Read"}),
    ("selective module global read grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\nfrom Counters import hits\ndef read_hits() -> i64:\n    can Global.Read:\n        return hits\n", set()),
    ("selective module global write missing grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\nfrom Counters import hits\ndef write_hits() -> void:\n    hits <- 8\n", {"Global.Write"}),
    ("selective module global write grant", "module Counters:\n    public:\n        global mutable hits: i64 = 7\nfrom Counters import hits\ndef write_hits() -> void:\n    can Global.Write:\n        hits <- 8\n", set()),
]
# Signature rows describe caller contracts; they never authorize body access.
# Give transitive/callback fixtures their own immediate body grants so each test
# isolates the caller's authority. Keep signature-only fixtures deliberately bare.
for index, (name, source, expected) in enumerate(cases):
    if name == "signature does not authorize read":
        expected = {"Global.Read"}
    elif name == "signature does not authorize write":
        expected = {"Global.Write"}
    elif name != "wrong member":
        source = source.replace(
            "def read_count() -> i64 can[Global.Read]:\n    return count\n",
            "def read_count() -> i64 can[Global.Read]:\n    return count can Global.Read\n",
        )
        source = source.replace(
            "def write_count() -> void can[Global.Write]:\n    count <- 1\n",
            "def write_count() -> void can[Global.Write]:\n    can Global.Write:\n        count <- 1\n",
        )
    cases[index] = name, source, expected

for name, source, expected in cases:
    result = subprocess.run([args.reporter], input="# severity\n" + source, text=True, capture_output=True, check=True)
    assert result.stdout.startswith("P 0\n"), (name, result.stdout, result.stderr)
    messages = []
    severity = None
    for line in result.stdout.splitlines():
        if line.startswith("S "):
            severity = int(line.split()[1])
        elif ("requires can[Global]" in line or "accesses a global mutable binding without Global." in line) and "warning:" not in line:
            assert severity == 1, (name, "mandatory Global must be an error", result.stdout)
            messages.append(line)
    observed = set()
    for message in messages:
        observed.update("Global." + member for member in re.findall(r"Global\.(Read|Write)", message))
        for members in re.findall(r"Global\{([^}]+)\}", message):
            observed.update("Global." + member.strip() for member in members.split(","))
    assert observed == expected, (name, expected, observed, result.stdout)
    print("PASS", name)

# Statement nesting is not covered by the expression-only depth guard. The
# Global-authority walk must reject its own truncation instead of treating a
# deep body as effect-free or overflowing the native stack.
nested_depth = 140
nested_body = "".join("        " + "    " * level + "if true:\n" for level in range(nested_depth))
nested_source = (
    "global mutable count: i64 = 0\n"
    "def deep() -> i64 can[Global{Read, Write}]:\n"
    "    can Global{Read, Write}:\n"
    + nested_body
    + "        " + "    " * nested_depth
    + "return count\n"
)
nested_result = subprocess.run(
    [args.reporter],
    input="# severity\n" + nested_source,
    text=True,
    capture_output=True,
    check=True,
)
nested_output = nested_result.stdout + nested_result.stderr
assert "global mutable-global authority analysis nesting exceeds the safe semantic-analysis limit" in nested_output, (
    "deep statement body was not rejected by the bounded authority walk",
    nested_output,
)
assert "accesses a global mutable binding without Global." not in nested_output, (
    "the local Global grants should cover every effect conservatively marked on truncation",
    nested_output,
)
print("PASS deep statement body is rejected safely")
print(f"mutable global grants: {len(cases)} canonical local-authority cases passed")
