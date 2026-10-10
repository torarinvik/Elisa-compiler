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
    result = subprocess.run([args.reporter], input=source, text=True, capture_output=True, check=True)
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
print(f"mutable global grants: {len(cases)} canonical local-authority cases passed")
