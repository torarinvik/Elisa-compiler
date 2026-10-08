#!/usr/bin/env python3
"""Mandatory mutable-global access grants in the real Stage1 semantic pipeline."""
import argparse
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
    ("index read propagates", "global mutable cursor: usize = 0\nglobal mutable slots: i64[4] = zeroed\ndef store() -> void:\n    can Global.Read, Global.Write:\n        slots[cursor] <- 1\ndef caller() -> void:\n    can Global.Write:\n        store()\n", {"Global.Read"}),
    ("transitive reader", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\ndef caller() -> i64:\n    return read_count()\n", {"Global.Read"}),
    ("transitive writer", "global mutable count: i64 = 0\ndef write_count() -> void can[Global.Write]:\n    count <- 1\ndef caller() -> void:\n    write_count()\n", {"Global.Write"}),
    ("transitive grant", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\ndef caller() -> i64:\n    can Global.Read:\n        return read_count()\n", set()),
    ("transitive wrong member", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\ndef caller() -> i64:\n    can Global.Write:\n        return read_count()\n", {"Global.Read"}),
    ("read before shadow", "global mutable count: i64 = 0\ndef read_count() -> i64:\n    previous: i64 = count\n    count: i64 = 7\n    return previous + count\n", {"Global.Read"}),
    ("inner shadow does not escape", "global mutable count: i64 = 0\ndef read_count(flag: bool) -> i64:\n    if flag:\n        count: i64 = 7\n    return count\n", {"Global.Read"}),
    ("read", "global mutable count: i64 = 0\ndef read_count() -> i64:\n    return count\n", {"Global.Read"}),
    ("write", "global mutable count: i64 = 0\ndef write_count() -> void:\n    count <- 1\n", {"Global.Write"}),
    ("read-modify-write", "global mutable count: i64 = 0\ndef bump() -> void:\n    count <- count + 1\n", {"Global.Read", "Global.Write"}),
    ("read signature", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Read]:\n    return count\n", set()),
    ("write signature", "global mutable count: i64 = 0\ndef write_count() -> void can[Global.Write]:\n    count <- 1\n", set()),
    ("wrong member", "global mutable count: i64 = 0\ndef read_count() -> i64 can[Global.Write]:\n    return count\n", {"Global.Read"}),
    ("block grants", "global mutable count: i64 = 0\ndef bump() -> void:\n    can Global.Read, Global.Write:\n        count <- count + 1\n", set()),
    ("unrelated block", "global mutable count: i64 = 0\ndef read_count() -> i64:\n    can Memory.Allocate:\n        return count\n", {"Global.Read"}),
    ("immutable global", "global count: i64 = 7\ndef read_count() -> i64:\n    return count\n", set()),
    ("constant", "const count: i64 = 7\ndef read_count() -> i64:\n    return count\n", set()),
    ("parameter shadows", "global mutable count: i64 = 0\ndef read_count(count: i64) -> i64:\n    return count\n", set()),
    ("index target reads", "global mutable cursor: usize = 0\nglobal mutable slots: i64[4] = zeroed\ndef store() -> void:\n    slots[cursor] <- 1\n", {"Global.Read", "Global.Write"}),
]
for name, source, expected in cases:
    result = subprocess.run([args.reporter], input=source, text=True, capture_output=True, check=True)
    assert result.stdout.startswith("P 0\n"), (name, result.stdout, result.stderr)
    messages = [line for line in result.stdout.splitlines() if "accesses a global mutable binding without" in line]
    observed = {member for member in ("Global.Read", "Global.Write") if any("without " + member + ";" in message for message in messages)}
    assert observed == expected, (name, expected, observed, result.stdout)
    print("PASS", name)
print(f"mutable global grants: {len(cases)} direct-access cases passed")
