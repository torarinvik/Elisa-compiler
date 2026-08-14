#!/usr/bin/env bash
# `elisac init` and `elisac init-lib` SCAFFOLD PARITY: same directory tree, same file bytes, same exit status.
#
# `init` writes to the FILESYSTEM, so a divergence is not a report mismatch — it is a
# project that does not build, or (as with the nested `--path` bug this gate was written
# for) no project at all alongside a success exit code.
#
# Deliberately compares with `diff -r`, so an EXTRA file on either side fails too. A
# scaffold that quietly omits `lib/.gitkeep` still `diff`s clean file-by-file.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

STAGE1_BIN="${STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
[[ -x "$STAGE1_BIN" ]] || { echo "error: stage1 binary not built: $STAGE1_BIN" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
differ=0

# The subcommand under test; `check` runs whatever `SUBCOMMAND` names so the same
# tree/bytes/exit-status comparison covers `init` and `init-lib` alike.
SUBCOMMAND=init

check() {
    local label="$1"; shift
    rm -rf "$WORK/s0" "$WORK/s1"
    mkdir -p "$WORK/s0" "$WORK/s1"
    ( cd "$WORK/s0" && "$ELISACORE_BIN" "$SUBCOMMAND" "$@" >/dev/null 2>&1 ); local rc0=$?
    ( cd "$WORK/s1" && "$STAGE1_BIN"     "$SUBCOMMAND" "$@" >/dev/null 2>&1 ); local rc1=$?
    if [[ "$rc0" != "$rc1" ]]; then
        differ=$((differ + 1))
        echo "DIFF $label: exit status $rc0 (stage0) vs $rc1 (stage1)"
        return
    fi
    if diff -r "$WORK/s0" "$WORK/s1" >/dev/null 2>&1; then
        same=$((same + 1))
    else
        differ=$((differ + 1))
        echo "DIFF $label:"
        diff -r "$WORK/s0" "$WORK/s1" 2>&1 | head -8
    fi
}

check "plain"                demo
check "strict"               demo --strict
check "nested path"          app --path custom/demo
check "deep nested path"     app --path a/b/c/d
check "path with dot"        app --path ./here
check "trailing slash path"  app --path out/
check "missing name"
check "unknown flag"         demo --bogus

# `init-lib` writes a DIFFERENT shape: a `<name>.elisalib` bundle with a manifest, a
# README, a name-derived source and its `.elisai` interface, and an EMPTY `native/` that
# only `diff -r` can see. It takes no `--strict`.
SUBCOMMAND=init-lib
check "lib plain"               mylib
check "lib nested path"         pkg --path vendor
check "lib deep nested path"    pkg --path a/b/c
check "lib trailing slash path" pkg --path out/
check "lib missing name"
check "lib unknown flag"        mylib --bogus
check "lib rejects --strict"    mylib --strict

echo "init scaffold parity: $same identical, $differ divergent"
[[ "$differ" -eq 0 ]] || { echo "init scaffold parity FAILED"; exit 1; }
echo "init scaffold parity OK"
