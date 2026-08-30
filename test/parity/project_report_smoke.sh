#!/bin/bash
# `project view` and `project deps` must produce stage0's bytes.
#
# These two reports are the user-facing face of the project system: they name the selected
# target, resolve every path, order the dependency graph, and expand the include closure.
# Nothing about that is checked by compiling a program, so the only way to know stage1 agrees
# is to run both compilers over the same scaffold and diff.
#
# The probe (project_report_probe.elisa) is stage1's src/driver/project.elisa driven through a
# CLI shaped like stage0's. The work is done in Elisa — deliberately not in
# scripts/elisac_stage1.sh, where `-emit deps` lives: that wrapper's Python is justified for
# include EXPANSION, but resolving a project through it would make this smoke measure Python
# rather than stage1.
#
# Fixtures, in rising order of nastiness:
#   scaffold  stage0's own `init` output, unmodified
#   rich      two targets, a dependency chain, native inputs, per-target warnings,
#             inherit-project-native=false, duplicate search paths and include dirs
#   cyclic    a -> b -> a, which stage0 ORDERS rather than rejects (see below)
#   err/*     one resolution or decoding failure each
#
# Two known, deliberate divergences, asserted as such rather than silently skipped:
#   * A JSON SYNTAX error's detail text. stage0 decodes with encoding/json and reports
#     character-level detail ("invalid character '}' looking for beginning of object key
#     string"); reproducing that verbatim means reimplementing Go's scanner phrasing. The
#     unknown-FIELD message, which is deterministic and far likelier in practice, IS
#     reproduced exactly and is checked below.
#   * `platforms` selects on the host platform. stage0 reads runtime.GOOS; a self-hosted
#     binary has no equivalent, so ProjectSystem::host_platform_name is a constant. This
#     smoke runs both compilers on the same host, so the constant agrees here by
#     construction — it is a portability limit, not an untested path.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EC="${ELISAC:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
BUILD="$ROOT/build/project_report"
rm -rf "$BUILD"
mkdir -p "$BUILD"

pass=0
fail=0

note_pass() { pass=$((pass + 1)); }
note_fail() { fail=$((fail + 1)); echo "FAIL: $1"; }

if [[ ! -x "$EC" ]]; then
    echo "SKIP: stage0 binary not found at $EC (set ELISAC)"
    exit 0
fi

# The probe includes the std, so the runtime is already in the object; linking
# elisacore_runtime.o as well is a duplicate-symbol error, not a missing one.
if ! bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -o "$BUILD/probe" \
        "$ROOT/test/parity/project_report_probe.elisa" >"$BUILD/compile.log" 2>&1; then
    echo "FAIL: could not build the project-report probe"
    grep -v "warning:" "$BUILD/compile.log" | head -20
    exit 1
fi
PROBE="$BUILD/probe"

# ---- fixtures ---------------------------------------------------------------------------

SCAFFOLD="$BUILD/scaffold"
mkdir -p "$SCAFFOLD"
( cd "$SCAFFOLD" && "$EC" init demo >/dev/null 2>&1 )
[[ -f "$SCAFFOLD/demo/project.json" ]] || { echo "FAIL: stage0 init produced no project.json"; exit 1; }

RICH="$BUILD/rich"
mkdir -p "$RICH/src" "$RICH/lib/mathcore.elisalib/src" "$RICH/lib/util.elisalib/src" "$RICH/native" "$RICH/asm"
cat > "$RICH/project.json" <<'JSON'
{
  "version": "0.2.0",
  "dependency-search-paths": ["lib", "lib"],
  "dependencies": ["mathcore"],
  "include-dirs": ["src", "./src"],
  "foreign": ["native/shim.c"],
  "easm": ["asm/boot.easm"],
  "link-flags": ["-lm"],
  "exec": ["echo project"],
  "targets": {
    "zeta": {
      "entry": "src/zeta.elisa",
      "emit": "object",
      "run-emit": "run",
      "opt": "O2",
      "target-triple": "arm64-apple-macosx14.0.0",
      "dependencies": ["util"],
      "include-dirs": ["src/extra"],
      "link-flags": ["-lz"],
      "exec": ["echo zeta"],
      "warnings": {"strict": true}
    },
    "app": {
      "entry": "src/main.elisa",
      "output": "build/app.ll",
      "warnings": {"perf": true, "concurrency": true},
      "inherit-project-native": false
    }
  }
}
JSON
cat > "$RICH/lib/mathcore.elisalib/manifest.json" <<'JSON'
{"provides": "mathcore", "entry": "src/mathcore.elisa", "include-dirs": ["src"], "foreign": ["shim.c"], "link-flags": ["-lmath"], "exec": ["echo mathcore"]}
JSON
cat > "$RICH/lib/util.elisalib/manifest.json" <<'JSON'
{"provides": "util", "interface": "src/util.elisai", "dependencies": ["mathcore"], "easm": ["u.easm"]}
JSON
printf 'include "helper.elisa"\ndef main() -> int:\n    return 0\n' > "$RICH/src/main.elisa"
printf 'def helper() -> int:\n    return 1\n'                      > "$RICH/src/helper.elisa"
printf 'def zeta() -> int:\n    return 2\n'                        > "$RICH/src/zeta.elisa"
printf 'def m() -> int:\n    return 3\n'                           > "$RICH/lib/mathcore.elisalib/src/mathcore.elisa"
printf 'def u() -> int\n'                                          > "$RICH/lib/util.elisalib/src/util.elisai"

# A dependency cycle is NOT an error: stage0's visit() marks a manifest seen before recursing,
# so `a -> b -> a` stops at the second `a` and orders as `b, a`. stage1 reported a cycle here
# until this fixture caught it.
CYCLIC="$BUILD/cyclic"
mkdir -p "$CYCLIC/src" "$CYCLIC/lib/a.elisalib/src" "$CYCLIC/lib/b.elisalib/src"
printf 'def main() -> int:\n    return 0\n' > "$CYCLIC/src/main.elisa"
echo '{"dependencies":["a"],"targets":{"app":{"entry":"src/main.elisa"}}}' > "$CYCLIC/project.json"
echo '{"provides":"a","entry":"src/a.elisa","dependencies":["b"]}' > "$CYCLIC/lib/a.elisalib/manifest.json"
echo '{"provides":"b","entry":"src/b.elisa","dependencies":["a"]}' > "$CYCLIC/lib/b.elisalib/manifest.json"
printf 'def a() -> int:\n    return 1\n' > "$CYCLIC/lib/a.elisalib/src/a.elisa"
printf 'def b() -> int:\n    return 2\n' > "$CYCLIC/lib/b.elisalib/src/b.elisa"

make_error_fixture() {
    local name="$1"
    local dir="$BUILD/err/$name"
    mkdir -p "$dir/src"
    printf 'def main() -> int:\n    return 0\n' > "$dir/src/main.elisa"
    cat > "$dir/project.json"
}
make_error_fixture missingdep <<'JSON'
{"dependencies":["ghost"],"targets":{"app":{"entry":"src/main.elisa"}}}
JSON
# "O9", not "O1". O1 USED to be this fixture's example of an invalid level, and
# stopped being one when -O1 support was added -- at which point the fixture was
# silently asserting that a VALID option is rejected, and it only surfaced as a
# stage0/stage1 exit-status disagreement (stage0 accepted, stage1 still refused).
# Pick a level neither compiler will ever grow.
make_error_fixture badopt <<'JSON'
{"targets":{"app":{"entry":"src/main.elisa","opt":"O9"}}}
JSON
make_error_fixture badentry <<'JSON'
{"targets":{"app":{"entry":"src/main.txt"}}}
JSON
make_error_fixture noentry <<'JSON'
{"targets":{"app":{"emit":"llvm"}}}
JSON
make_error_fixture packedabi <<'JSON'
{"targets":{"app":{"entry":"src/main.elisa","packed-abi":"legacy"}}}
JSON
make_error_fixture unknownkey <<'JSON'
{"targets":{"app":{"entry":"src/main.elisa"}},"bogus":1}
JSON
make_error_fixture unknowntargetkey <<'JSON'
{"targets":{"app":{"entry":"src/main.elisa","nope":true}}}
JSON
make_error_fixture badjson <<'JSON'
{"targets":{"app":{"entry":"src/main.elisa"},}}
JSON

# ---- the diff ----------------------------------------------------------------------------

# Both stage1 front ends are checked against stage0:
#
#   PROBE  the module compiled fresh from src/driver/project.elisa on every run, so a source
#          regression is caught here without waiting for a seed rebuild;
#   CLI    bin/elisac-stage1's own `project` subcommand — what a user actually types, and the
#          only one that proves the report survived the self-host build.
#
# The CLI leg is skipped when the seed predates the source, since it would then be testing a
# stale binary and reporting a pass or a failure that neither reflects the tree.
CLI="$ROOT/bin/elisac-stage1"
CLI_FRESH=0
if [[ -x "$CLI" ]]; then
    CLI_FRESH=1
    for source in "$ROOT/src/driver/project.elisa" "$ROOT/src/driver/elisac.elisa"; do
        [[ "$source" -nt "$CLI" ]] && CLI_FRESH=0
    done
fi
[[ "$CLI_FRESH" -eq 1 ]] || echo "note: bin/elisac-stage1 is older than the driver sources; CLI leg skipped"

# One report, every front end, compared as bytes AND exit status.
check() {
    local label="$1" dir="$2"
    shift 2
    local out0="$BUILD/out0.txt" out1="$BUILD/out1.txt"
    ( cd "$dir" && "$EC" project "$@" ) >"$out0" 2>&1
    local rc0=$?

    local runner
    for runner in probe cli; do
        [[ "$runner" == cli && "$CLI_FRESH" -ne 1 ]] && continue
        if [[ "$runner" == probe ]]; then
            ( cd "$dir" && "$PROBE" "$@" ) >"$out1" 2>&1
        else
            ( cd "$dir" && "$CLI" project "$@" ) >"$out1" 2>&1
        fi
        local rc1=$?
        if [[ "$rc0" != "$rc1" ]]; then
            note_fail "$label [$runner]: exit status stage0=$rc0 stage1=$rc1"
            continue
        fi
        if ! diff -q "$out0" "$out1" >/dev/null; then
            note_fail "$label [$runner]: output differs"
            diff "$out0" "$out1" | head -12
            continue
        fi
        note_pass
    done
}

for target in "" zeta app nope; do
    label="${target:-<default>}"
    check "rich view $label"        "$RICH" view ${target:+"$target"}
    check "rich deps $label"        "$RICH" deps ${target:+"$target"}
    check "rich deps --json $label" "$RICH" deps ${target:+"$target"} --json
done

check "scaffold view"        "$SCAFFOLD/demo" view
check "scaffold deps"        "$SCAFFOLD/demo" deps
check "scaffold deps --json" "$SCAFFOLD/demo" deps --json

check "cyclic view"        "$CYCLIC" view
check "cyclic deps"        "$CYCLIC" deps
check "cyclic deps --json" "$CYCLIC" deps --json

for name in missingdep badopt badentry noentry packedabi unknownkey unknowntargetkey; do
    check "err/$name view" "$BUILD/err/$name" view
    check "err/$name deps" "$BUILD/err/$name" deps
done

# Cases the first pass of this port got WRONG, each kept as a fixture:
#   platforms    only the host entry contributes; the others must be stepped over, not read
#   notargets    an empty target table is rejected at LOAD time, BEFORE the view header —
#                stage1 printed the header and then a "target not found" error
#   provides     a manifest whose `provides` disagrees with the requested name
#   plaindir     a dependency in `lib/<name>/` rather than `lib/<name>.elisalib/`
PLAT="$BUILD/platforms"
mkdir -p "$PLAT/src"
printf 'def main() -> int:\n    return 0\n' > "$PLAT/src/main.elisa"
cat > "$PLAT/project.json" <<'JSON'
{"targets":{"app":{"entry":"src/main.elisa","link-flags":["-lbase"],"platforms":{"linux":{"link-flags":["-lonlylinux"]},"macos":{"link-flags":["-lonlymac","-framework","CoreFoundation"]},"windows":{"link-flags":["-lonlywin"]}}}}}
JSON
check "platforms view" "$PLAT" view
check "platforms deps" "$PLAT" deps

NOTARGETS="$BUILD/notargets"
mkdir -p "$NOTARGETS/src"
printf 'def main() -> int:\n    return 0\n' > "$NOTARGETS/src/main.elisa"
echo '{"targets":{}}' > "$NOTARGETS/project.json"
check "notargets view" "$NOTARGETS" view
check "notargets deps" "$NOTARGETS" deps

PROVIDES="$BUILD/provides"
mkdir -p "$PROVIDES/src" "$PROVIDES/lib/real.elisalib/src"
printf 'def main() -> int:\n    return 0\n' > "$PROVIDES/src/main.elisa"
echo '{"dependencies":["real"],"targets":{"app":{"entry":"src/main.elisa"}}}' > "$PROVIDES/project.json"
echo '{"provides":"other","entry":"src/r.elisa"}' > "$PROVIDES/lib/real.elisalib/manifest.json"
printf 'def r() -> int:\n    return 1\n' > "$PROVIDES/lib/real.elisalib/src/r.elisa"
check "provides mismatch view" "$PROVIDES" view

PLAINDIR="$BUILD/plaindir"
mkdir -p "$PLAINDIR/src" "$PLAINDIR/lib/plain/src"
printf 'def main() -> int:\n    return 0\n' > "$PLAINDIR/src/main.elisa"
echo '{"dependencies":["plain"],"targets":{"app":{"entry":"src/main.elisa"}}}' > "$PLAINDIR/project.json"
echo '{"provides":"plain","entry":"src/p.elisa"}' > "$PLAINDIR/lib/plain/manifest.json"
printf 'def p() -> int:\n    return 1\n' > "$PLAINDIR/lib/plain/src/p.elisa"
check "plain-dir dependency view" "$PLAINDIR" view
check "plain-dir dependency deps" "$PLAINDIR" deps

# Project DISCOVERY: the --project forms, and the walk up from a subdirectory. The
# not-found message names the search origin, and stage0 gets that name from Go's os.Getwd —
# which prefers $PWD over getcwd(3), so a shell sitting in /tmp reports "/tmp" and not the
# resolved "/private/tmp". ProjectSystem::working_directory mirrors that.
mkdir -p "$RICH/src/deep/deeper"
check "discovery --project DIR"          "$RICH" view --project "$RICH"
check "discovery --project project.json" "$RICH" view --project "$RICH/project.json"
check "discovery --project ."            "$RICH" view --project .
check "discovery deps --project DIR"     "$RICH" deps --project "$RICH"
check "discovery upward walk"            "$RICH/src/deep/deeper" view
check "discovery no project.json"        "$BUILD" view

# The declined case, asserted rather than skipped: the two must agree on the PREFIX and on
# failing, and must NOT agree on the detail. If they ever do agree in full, this check fails
# and the exclusion above should be deleted.
( cd "$BUILD/err/badjson" && "$EC" project view ) >"$BUILD/j0.txt" 2>&1
( cd "$BUILD/err/badjson" && "$PROBE" view )      >"$BUILD/j1.txt" 2>&1
if ! grep -q "^error: invalid json in .*project.json: " "$BUILD/j1.txt"; then
    note_fail "badjson: stage1 did not report the expected 'invalid json in PATH: ' prefix"
elif diff -q "$BUILD/j0.txt" "$BUILD/j1.txt" >/dev/null; then
    note_fail "badjson: the syntax-error detail now MATCHES stage0 — drop this exclusion"
else
    note_pass
fi

echo "project report parity: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
