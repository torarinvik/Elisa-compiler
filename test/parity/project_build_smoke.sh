#!/usr/bin/env bash
# `build|run|test|bench` — the four project subcommands that RESOLVE a target and compile
# its entry, rather than report on it.
#
# stage0 is the oracle: same stdout, same stderr, same exit code, and for `build` an artifact
# actually written at the path the target names. The artifact is not byte-compared — this
# target emits `llvm`, and stage1's textual IR is its own lowering, which the project
# deliberately does not hold to stage0's bytes. Each subcommand runs in its own copy of the
# scaffold so a build artifact from one cannot be mistaken for another's.
#
# `run` and `test` LINK before running, so they need the Elisa runtime object. There is no
# path an installed binary could guess, so the driver requires ELISA_RUNTIME_OBJ and says so
# by name; the last check pins that message rather than letting it regress into the raw
# "Undefined symbols: _arena_free" dump the host linker produces.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 300 "$@"; else "$@"; fi; }
set -u
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"

[ -x "$BIN" ] || { echo "project_build_smoke SKIP: no stage1 binary at $BIN"; exit 0; }
[ -x "$ELISACORE_BIN" ] || { echo "project_build_smoke SKIP: no elisac at $ELISACORE_BIN"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

pass=0; total=0

# scaffold <name> -> two identical projects, one per compiler, under $WORK/<name>/{s0,s1}
scaffold() {
    local name="$1"
    mkdir -p "$WORK/$name/s0" "$WORK/$name/s1"
    ( cd "$WORK/$name/s0" && "$ELISACORE_BIN" init demo >/dev/null 2>&1 )
    cp -r "$WORK/$name/s0/demo" "$WORK/$name/s1/demo"
}

# compare <case> <subcommand...> — stdout+stderr+rc against stage0
compare() {
    local name="$1"; shift
    total=$((total + 1))
    scaffold "$name"
    local o0 o1 r0 r1
    # The two projects live at .../s0/demo and .../s1/demo, so any path in the output
    # differs by construction. Fold that one segment; everything else must match verbatim.
    o0="$( cd "$WORK/$name/s0/demo" && RUN "$ELISACORE_BIN" "$@" 2>&1 | sed "s|/s0/demo|/PROJ|g" )"; r0=${PIPESTATUS[0]}
    o1="$( cd "$WORK/$name/s1/demo" && ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" RUN "$BIN" "$@" 2>&1 | sed "s|/s1/demo|/PROJ|g" )"; r1=${PIPESTATUS[0]}
    if [ "$r0" -ne "$r1" ]; then
        echo "  FAIL $name: rc stage0=$r0 stage1=$r1"; return
    fi
    if [ "$o0" != "$o1" ]; then
        echo "  FAIL $name: output differs"
        echo "    stage0: $(printf '%s' "$o0" | head -2 | tr '\n' '|')"
        echo "    stage1: $(printf '%s' "$o1" | head -2 | tr '\n' '|')"
        return
    fi
    pass=$((pass + 1))
}

compare build_default   build
compare run_default     run
compare test_default    test
compare bench_default   bench
# Explicit target name, and the `--project DIR` form invoked from OUTSIDE the project.
compare build_named     build app
compare run_named       run app

total=$((total + 1))
scaffold project_flag
o0="$( RUN "$ELISACORE_BIN" build --project "$WORK/project_flag/s0/demo" 2>&1 )"; r0=$?
o1="$( ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" RUN "$BIN" build --project "$WORK/project_flag/s1/demo" 2>&1 )"; r1=$?
# The paths differ by design (s0 vs s1), so compare the SHAPE: same rc, same line count.
if [ "$r0" -eq "$r1" ] && [ "$(printf '%s' "$o0" | wc -l)" -eq "$(printf '%s' "$o1" | wc -l)" ]; then
    pass=$((pass + 1))
else
    echo "  FAIL project_flag: rc=$r0/$r1"
fi

# Errors: an unknown target, and no project at all.
compare build_missing_target  build nope
total=$((total + 1))
o0="$( cd "$WORK" && RUN "$ELISACORE_BIN" build 2>&1 | head -1 | sed "s|$WORK|WORK|g" )"
o1="$( cd "$WORK" && RUN "$BIN" build 2>&1 | head -1 | sed "s|$WORK|WORK|g" )"
if [ "$o0" = "$o1" ]; then pass=$((pass + 1)); else
    echo "  FAIL build_no_project:"; echo "    stage0: $o0"; echo "    stage1: $o1"
fi

# `build` must EMIT the artifact at the path the target names — rc=0 alone would pass with no
# file written at all.
#
# NOT byte-compared: this target emits `llvm`, and stage1's textual IR is its own lowering,
# which the project deliberately does not hold to stage0's bytes (only obj/bc behaviour and
# `nm` are compared). So the assertion is that both compilers produce a module defining the
# program's entry point.
total=$((total + 1))
scaffold artifact
( cd "$WORK/artifact/s0/demo" && RUN "$ELISACORE_BIN" build >/dev/null 2>&1 )
( cd "$WORK/artifact/s1/demo" && ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" RUN "$BIN" build >/dev/null 2>&1 )
a0="$WORK/artifact/s0/demo/build/app.ll"; a1="$WORK/artifact/s1/demo/build/app.ll"
if [ -s "$a0" ] && [ -s "$a1" ] && grep -q "define .*@main" "$a0" && grep -q "define .*@main" "$a1"; then
    pass=$((pass + 1))
else
    echo "  FAIL build_artifact: missing or entry-less module ($(wc -c < "$a0" 2>/dev/null) vs $(wc -c < "$a1" 2>/dev/null) bytes)"
fi

# Resolution must follow the PROCESS's working directory, not an inherited $PWD.
#
# `working_directory` prefers $PWD so the symlinked spelling survives (stage0 prints
# /tmp, not /private/tmp). It used to take $PWD whenever it was absolute and existed —
# but a process whose cwd differs from the $PWD it inherited then resolved the project from
# the PARENT's directory, and any tool that spawns the compiler with a working directory
# (a build script, subprocess(cwd=...)) got "could not find project.json" for a project
# sitting right there. Go's os.Getwd takes $PWD only when it names the same directory.
#
# Both halves are checked: the stale-$PWD case, and that the symlinked spelling still wins.
total=$((total + 1))
scaffold cwd_honoured
cwd0="$( cd "$WORK/cwd_honoured/s0/demo" && env PWD=/ RUN "$ELISACORE_BIN" project view 2>&1 | head -1 | sed "s|/s0/demo|/PROJ|" )"
cwd1="$( cd "$WORK/cwd_honoured/s1/demo" && env PWD=/ RUN "$BIN" project view 2>&1 | head -1 | sed "s|/s1/demo|/PROJ|" )"
if [ "$cwd0" = "$cwd1" ]; then
    pass=$((pass + 1))
else
    echo "  FAIL cwd_honoured (stale PWD):"; echo "    stage0: $cwd0"; echo "    stage1: $cwd1"
fi

total=$((total + 1))
rm -rf /tmp/elisa_pwd_probe && mkdir -p /tmp/elisa_pwd_probe
( cd /tmp/elisa_pwd_probe && "$ELISACORE_BIN" init demo >/dev/null 2>&1 )
sym0="$( cd /tmp/elisa_pwd_probe/demo && RUN "$ELISACORE_BIN" project view 2>&1 | head -1 )"
sym1="$( cd /tmp/elisa_pwd_probe/demo && RUN "$BIN" project view 2>&1 | head -1 )"
rm -rf /tmp/elisa_pwd_probe
if [ "$sym0" = "$sym1" ] && printf '%s' "$sym1" | grep -q "^Project: /tmp/"; then
    pass=$((pass + 1))
else
    echo "  FAIL cwd_symlink_spelling:"; echo "    stage0: $sym0"; echo "    stage1: $sym1"
fi

# The runtime-object requirement names itself.
total=$((total + 1))
scaffold no_runtime
msg="$( cd "$WORK/no_runtime/s1/demo" && env -u ELISA_RUNTIME_OBJ "$BIN" run 2>&1 | head -1 )"
if printf '%s' "$msg" | grep -q "needs the Elisa runtime object"; then
    pass=$((pass + 1))
else
    echo "  FAIL runtime_object_message: got '$msg'"
fi

if [ "$pass" -ne "$total" ]; then
    echo "project_build_smoke FAILED: passed=$pass total=$total"
    exit 1
fi
echo "project_build_smoke OK: $pass/$total (build|run|test|bench match stage0)"
