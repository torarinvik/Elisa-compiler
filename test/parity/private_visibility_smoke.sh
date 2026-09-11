#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

check_case() {
    local name="$1" expected="$2"
    local file="$WORK/$name.elisa"
    cat > "$file"

    local stage0
    stage0="$("$ELISACORE_BIN" -emit semantic "$file" 2>&1 >/dev/null || true)"
    local stage1
    stage1="$("$RPT" < "$file")"
    grep -q '^P 0$' <<< "$stage1"

    if [[ "$expected" == reject ]]; then
        grep -qF 'is private to module' <<< "$stage0"
        grep -qF 'is private to module' <<< "$stage1"
    else
        if grep -qF 'is private to module' <<< "$stage0" || grep -qF 'is private to module' <<< "$stage1"; then
            echo "private visibility false positive in $name" >&2
            echo "stage0:\n$stage0" >&2
            echo "stage1:\n$stage1" >&2
            return 1
        fi
        grep -q '^D 0$' <<< "$stage1"
    fi
}

check_case unqualified_import reject <<'ELISA'
module Vault:
    private:
        def hidden() -> i64:
            return 41

using Vault

def main() -> i64:
    return hidden()
ELISA

check_case reopened_module_import reject <<'ELISA'
module Vault:
    private:
        def first() -> i64:
            return 1

extend Vault:
    private:
        def hidden() -> i64:
            return 41

using Vault

def main() -> i64:
    return hidden()
ELISA

check_case selective_public_collision accept <<'ELISA'
module A:
    private:
        const hidden: i64 = 1

module B:
    public:
        const hidden: i64 = 41

from B import hidden

def main() -> i64:
    return hidden + 1
ELISA

echo "private visibility smoke OK"
