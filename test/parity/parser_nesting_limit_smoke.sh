#!/usr/bin/env bash
# Parser limits protect later recursive passes and match Stage0's accepted shapes.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 - "$RPT" <<'PY'
import subprocess
import sys

reporter = sys.argv[1]


def program(shape, depth):
    if shape == "paren":
        expression = "(" * depth + "1" + ")" * depth
    elif shape == "binary":
        expression = " + ".join(["1"] * depth)
    elif shape == "prefix":
        expression = "-" * depth + "1"
    elif shape == "postfix":
        expression = "x" + ".v" * depth
    elif shape == "type":
        annotation = "darray[" * depth + "i32" + "]" * depth
        return f"def f() -> i32:\n    x: {annotation} = new darray[i32]()\n    return 0\n"
    elif shape == "block":
        body = "".join("    " * (index + 1) + "if true:\n" for index in range(depth))
        return "def f() -> i32:\n" + body + "    " * (depth + 1) + "return 1\n    return 0\n"
    else:
        raise ValueError(shape)
    return f"def f(x: i32) -> i32:\n    return {expression}\n"


def check(shape, depth, rejected):
    result = subprocess.run([reporter], input=program(shape, depth), text=True,
                            capture_output=True, timeout=20, check=True)
    lines = result.stdout.splitlines()
    expected = "P 1" if rejected else "P 0"
    if not lines or lines[0] != expected:
        raise SystemExit(f"{shape} depth {depth}: expected {expected}, got {lines[:5]}")
    if rejected and (len(lines) < 2 or "nesting too deep: exceeds the maximum depth of 1000" not in lines[1]):
        raise SystemExit(f"{shape} depth {depth}: missing nesting diagnostic: {lines[:5]}")


for shape, below, above in (("paren", 990, 1001), ("binary", 999, 1001),
                            ("prefix", 990, 1001), ("postfix", 990, 1100),
                            ("type", 500, 1100), ("block", 990, 1001)):
    check(shape, below, False)
    check(shape, above, True)
for shape, depth in (("paren", 20000), ("binary", 200000),
                     ("prefix", 20000), ("postfix", 20000)):
    check(shape, depth, True)

# Unary plus is not part of Stage0's expression grammar; infix addition remains valid.
for expression, rejected in (("+1", True), ("1 + +2", True), ("1 + 2", False), ("-1 + 2", False)):
    result = subprocess.run([reporter], input=f"def f() -> i32:\n    return {expression}\n",
                            text=True, capture_output=True, timeout=20, check=True)
    first = result.stdout.splitlines()[0]
    count = int(first.split()[1]) if first.startswith("P ") else -1
    if (count > 0) != rejected or count < 0:
        raise SystemExit(f"expression {expression!r}: unexpected parser result {first}")

siblings = "def f() -> i32:\n" + "".join(f"    x{i}: i32 = (((1)))\n" for i in range(3000)) + "    return 0\n"
result = subprocess.run([reporter], input=siblings, text=True, capture_output=True,
                        timeout=20, check=True)
if result.stdout.splitlines()[0] != "P 0":
    raise SystemExit("nesting depth accumulated across sibling expressions")
print("parser nesting boundaries, deep inputs, and sibling reset OK")
PY
