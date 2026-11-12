#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"

stored="$("$RPT" <<'ELISA'
enum Node layout(handle: u32):
    common:
        value: i64
    pass
enum Leaf is Node:
    Item

def read(node: Node, store: Node.Store[Local]) -> i64:
    match node in store:
        Leaf.Item:
            return node.value
ELISA
)"
[[ "$stored" == *$'P 0\nD 0'* ]] || { printf 'store-backed hierarchy rejected:\n%s\n' "$stored" >&2; exit 1; }
inline="$("$RPT" <<'ELISA'
enum Node layout(handle: u32): pass
enum Leaf is Node:
    Item

def read(node: Node, store: Node.Store[Local]) -> i64:
    return 0
ELISA
)"
[[ "$inline" == *$'P 0\nD 0'* ]] && { printf 'inline hierarchy unexpectedly exposes a store:\n%s\n' "$inline" >&2; exit 1; }
echo 'hierarchy store representation OK'
