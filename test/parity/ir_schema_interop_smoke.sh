#!/bin/bash
# Two independent readings of the same `.elisair` must agree.
#
# This is the claim the v2 schema exists to support. stage0 writes the bundle
# from its Go AST; the reader under test is written in Elisa (src/driver/
# frontend_ir.elisa) and has no access to stage0's types — only to the type table
# the file carries and the length prefix on every field. If the format really is
# language-neutral, the two must report the same structure for every bundle.
#
# The v1 gob format could not be checked this way at all: its payload WAS Go's
# type graph, so there was no second implementation to disagree with.
#
# Each side prints one line:
#   ok 2 types=<n> nodes=<n> root=<n> source=<name>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"
EC="${ELISAC:-$HOME/.elisac/elisac}"
BUILD="$ROOT/build/ir_interop"
mkdir -p "$BUILD"

if [[ ! -d "$CORE/compiler/src/frontendir" ]]; then
    echo "SKIP: stage0 checkout not found at $CORE (set ELISA_CORE)"
    exit 0
fi

# Build the Elisa-side reader probe. It includes the std, so the runtime is
# already in the object — linking elisacore_runtime.o as well is a duplicate
# symbol error, not a missing one.
if ! "$EC" -emit obj -o "$BUILD/probe.o" "$ROOT/test/parity/ir_reader_probe.elisa" 2>"$BUILD/compile.log"; then
    echo "FAIL: could not compile the Elisa reader probe"
    grep -v "warning:" "$BUILD/compile.log" | head -10
    exit 1
fi
if ! clang -o "$BUILD/probe" "$BUILD/probe.o" 2>"$BUILD/link.log"; then
    echo "FAIL: could not link the Elisa reader probe"
    head -10 "$BUILD/link.log"
    exit 1
fi

# Build the Go-side reader once. `go run` per bundle dominated the runtime of
# this check (a compile per case, hundreds of cases) for no benefit.
if ! (cd "$CORE/compiler" && go build -o "$BUILD/stat" ./src/frontendir/stat) 2>"$BUILD/gobuild.log"; then
    echo "FAIL: could not build the stage0 bundle reader"
    head -10 "$BUILD/gobuild.log"
    exit 1
fi

pass=0
fail=0
skip=0

check_one() {
    local source="$1"
    local bundle="$BUILD/case.elisair"
    if ! "$EC" -emit ir -o "$bundle" "$source" >/dev/null 2>&1; then
        skip=$((skip + 1))
        return
    fi
    local from_go from_elisa
    from_go="$("$BUILD/stat" "$bundle" 2>&1)"
    from_elisa="$("$BUILD/probe" "$bundle" 2>&1)"
    if [[ "$from_go" == "$from_elisa" && "$from_elisa" == ok* ]]; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1))
        echo "DISAGREE $source"
        echo "  stage0 (Go):    $from_go"
        echo "  stage1 (Elisa): $from_elisa"
    fi
}

while IFS= read -r -d '' source; do
    check_one "$source"
done < <(find "$ROOT/test/repro" "$ROOT/test/fixtures" -name "*.elisa" -print0 2>/dev/null)

echo "ir schema interop: pass=$pass fail=$fail skipped=$skip"
[[ $fail -eq 0 && $pass -gt 0 ]] || exit 1
