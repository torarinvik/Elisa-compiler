#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-incremental-ga-cache.XXXXXX")"
source "$ROOT/test/parity/control_artifacts.sh"
elisa_control_artifacts "$WORK"
CACHE="$WORK/cache"
mkdir -p "$CACHE"

cat >"$WORK/check.elisa" <<'ELISA'
global mutable counter: i64 = 0

def pure() -> i64:
    return 7

def read_counter() -> i64:
    can Global.Read:
        return counter

def second_read() -> i64:
    can Global.Read:
        return counter

def write_counter() -> void:
    can Global.Write:
        counter <- 11

def grant_only() -> i64:
    can Global.Read:
        return 9

def trusted_only() -> i64:
    trusted Global.Read:
        return 10

def panic_only() -> void:
    trusted Abort.Panic:
        panic()

def main() -> i64:
    can Global.Read:
        return read_counter()
ELISA

run_check() {
    local cache_mode="$1" source="$2" stem="$3" semantic_mode="${4:-strict}" status
    if [[ "$cache_mode" == enabled ]]; then
        if [[ "$semantic_mode" == permissive ]]; then
            if env ELISA_STAGE1_PERMISSIVE=1 ELISA_STAGE1_INCREMENTAL_CACHE_DIR="$CACHE" \
                ELISA_STAGE1_INCREMENTAL_CACHE_REPORT=1 ELISA_ALLOW_STALE_STAGE1=0 \
                "$STAGE1" -emit check "$source" >"$WORK/$stem.out" 2>"$WORK/$stem.err"; then
                status=0
            else
                status=$?
            fi
        else
            if env -u ELISA_STAGE1_PERMISSIVE ELISA_STAGE1_INCREMENTAL_CACHE_DIR="$CACHE" \
                ELISA_STAGE1_INCREMENTAL_CACHE_REPORT=1 ELISA_ALLOW_STALE_STAGE1=0 \
                "$STAGE1" -emit check "$source" >"$WORK/$stem.out" 2>"$WORK/$stem.err"; then
                status=0
            else
                status=$?
            fi
        fi
    else
        if [[ "$semantic_mode" == permissive ]]; then
            if env -u ELISA_STAGE1_INCREMENTAL_CACHE_DIR -u ELISA_STAGE1_INCREMENTAL_CACHE_REPORT \
                ELISA_STAGE1_PERMISSIVE=1 ELISA_ALLOW_STALE_STAGE1=0 \
                "$STAGE1" -emit check "$source" >"$WORK/$stem.out" 2>"$WORK/$stem.err"; then
                status=0
            else
                status=$?
            fi
        else
            if env -u ELISA_STAGE1_PERMISSIVE -u ELISA_STAGE1_INCREMENTAL_CACHE_DIR \
                -u ELISA_STAGE1_INCREMENTAL_CACHE_REPORT ELISA_ALLOW_STALE_STAGE1=0 \
                "$STAGE1" -emit check "$source" >"$WORK/$stem.out" 2>"$WORK/$stem.err"; then
                status=0
            else
                status=$?
            fi
        fi
    fi
    printf '%s\n' "$status" >"$WORK/$stem.status"
}

compare_without_cache_report() {
    local left="$1" right="$2"
    diff -u "$WORK/$left.status" "$WORK/$right.status"
    diff -u "$WORK/$left.out" "$WORK/$right.out"
    sed '/^incremental-ga-cache:/d' "$WORK/$left.err" >"$WORK/$left.clean.err"
    sed '/^incremental-ga-cache:/d' "$WORK/$right.err" >"$WORK/$right.clean.err"
    diff -u "$WORK/$left.clean.err" "$WORK/$right.clean.err"
}

run_check cold "$WORK/check.elisa" cold
run_check enabled "$WORK/check.elisa" first
compare_without_cache_report cold first
grep -Eq 'incremental-ga-cache: input=ordinary prior=miss matched=0 visited=8 rejected=0 ga_walks_skipped=0 published=yes' "$WORK/first.err"

run_check enabled "$WORK/check.elisa" warm
compare_without_cache_report cold warm
grep -Eq 'incremental-ga-cache: input=ordinary prior=valid matched=8 visited=8 rejected=0 ga_walks_skipped=6 published=yes' "$WORK/warm.err"

python3 - "$WORK/check.elisa" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
assert "return 7" in s
p.write_text(s.replace("return 7", "return 8", 1))
PY
run_check cold "$WORK/check.elisa" edited-cold
run_check enabled "$WORK/check.elisa" edited-warm
compare_without_cache_report edited-cold edited-warm
grep -Eq 'incremental-ga-cache: input=ordinary prior=valid matched=7 visited=8 rejected=0 ga_walks_skipped=4 published=yes' "$WORK/edited-warm.err"

run_check cold "$WORK/check.elisa" options-cold permissive
run_check enabled "$WORK/check.elisa" options-warm permissive
compare_without_cache_report options-cold options-warm
grep -Eq 'incremental-ga-cache: input=ordinary prior=miss matched=0 visited=8 rejected=0 ga_walks_skipped=0 published=yes' "$WORK/options-warm.err"
run_check enabled "$WORK/check.elisa" options-confirm-warm permissive
compare_without_cache_report options-cold options-confirm-warm
grep -Eq 'incremental-ga-cache: input=ordinary prior=valid matched=8 visited=8 rejected=0 ga_walks_skipped=3 published=yes' "$WORK/options-confirm-warm.err"

cache_file="$(find "$CACHE" -type f -name '*.elisa-semantic' -print -quit)"
[[ -n "$cache_file" ]]
python3 - "$cache_file" "$ROOT/src/semantic/incremental_semantic_options.elisa" <<'PY'
from pathlib import Path
import re
import struct
import sys

path = Path(sys.argv[1])
data = bytearray(path.read_bytes())[:-8]
u64 = lambda offset: struct.unpack_from("<Q", data, offset)[0]
put = lambda offset, value: struct.pack_into("<Q", data, offset, value)
byte_count = u64(5 * 8)
function_count = u64(6 * 8)
fact_count = u64(7 * 8)
options_source = Path(sys.argv[2]).read_text()
key_length = int(re.search(r"INCREMENTAL_SEMANTIC_OPTIONS_KEY_LENGTH: usize = (\d+)", options_source).group(1))
pool_start = 14 * 8 + key_length
functions_at = pool_start + byte_count
facts_at = functions_at + function_count * 72
pool = data[pool_start : pool_start + byte_count]
target = None
for index in range(function_count):
    start = functions_at + index * 72
    key_start, key_length = u64(start), u64(start + 8)
    record_fact_start, record_fact_count = u64(start + 40), u64(start + 48)
    key = pool[key_start : key_start + key_length]
    if b"read_counter" in key:
        assert record_fact_count > 0, "read_counter must have cached direct facts"
        target = (index, record_fact_start, record_fact_count)
        break
assert target is not None, "read_counter record not found"
index, fact_start, removed = target
fact_begin = facts_at + fact_start * 56
fact_end = fact_begin + removed * 56
del data[fact_begin:fact_end]
put(functions_at + index * 72 + 48, 0)
for following in range(index + 1, function_count):
    start = functions_at + following * 72
    following_fact_start = u64(start + 40)
    assert following_fact_start >= fact_start + removed
    put(start + 40, following_fact_start - removed)
put(7 * 8, fact_count - removed)

hash_value = 14695981039346656037
for byte in data:
    hash_value = ((hash_value ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
data.extend(struct.pack("<Q", hash_value))
path.write_bytes(data)
PY
run_check cold "$WORK/check.elisa" forged-cold permissive
run_check enabled "$WORK/check.elisa" forged-warm permissive
compare_without_cache_report forged-cold forged-warm
grep -Eq 'incremental-ga-cache: input=ordinary prior=valid matched=8 visited=8 rejected=0 ga_walks_skipped=3 published=yes' "$WORK/forged-warm.err"
python3 - "$cache_file" "$ROOT/src/semantic/incremental_semantic_options.elisa" <<'PY'
from pathlib import Path
import re
import struct
import sys

data = Path(sys.argv[1]).read_bytes()
u64 = lambda offset: struct.unpack_from("<Q", data, offset)[0]
byte_count = u64(5 * 8)
function_count = u64(6 * 8)
options_source = Path(sys.argv[2]).read_text()
key_length = int(re.search(r"INCREMENTAL_SEMANTIC_OPTIONS_KEY_LENGTH: usize = (\d+)", options_source).group(1))
pool_start = 14 * 8 + key_length
functions_at = pool_start + byte_count
pool = data[pool_start : pool_start + byte_count]
matches = []
for index in range(function_count):
    start = functions_at + index * 72
    key_start, key_length = u64(start), u64(start + 8)
    key = pool[key_start : key_start + key_length]
    if b"read_counter" in key:
        matches.append(u64(start + 48))
assert len(matches) == 1, "published source rescan must retain one read_counter record"
assert matches[0] > 0, "current-source scan must retain read_counter's direct global facts"
PY

printf 'corrupt' >"$cache_file"
run_check cold "$WORK/check.elisa" corrupt-cold permissive
run_check enabled "$WORK/check.elisa" corrupt-warm permissive
compare_without_cache_report corrupt-cold corrupt-warm
grep -Eq 'incremental-ga-cache: input=ordinary prior=miss matched=0 visited=8 rejected=0 ga_walks_skipped=0 published=yes' "$WORK/corrupt-warm.err"

CACHE="$WORK/generated-cache"
mkdir -p "$CACHE"
cat >"$WORK/generated.elisa" <<'ELISA'
enum Color:
    Red

static generate:
    for variant in variants(Color):
        emit def generated_${variant.name}() -> i64:
            return 42

def main() -> i64:
    return generated_Red()
ELISA
run_check cold "$WORK/generated.elisa" generated-cold
run_check enabled "$WORK/generated.elisa" generated-first
compare_without_cache_report generated-cold generated-first
grep -Eq 'incremental-ga-cache: input=generated prior=miss matched=0 visited=2 rejected=0 ga_walks_skipped=0 published=yes' "$WORK/generated-first.err"
run_check enabled "$WORK/generated.elisa" generated-warm
compare_without_cache_report generated-cold generated-warm
grep -Eq 'incremental-ga-cache: input=generated prior=valid matched=2 visited=2 rejected=0 ga_walks_skipped=2 published=yes' "$WORK/generated-warm.err"

echo "incremental GA cache control OK: cold/warm parity, grant-only skip boundaries, forged-sidecar source revalidation, body/option invalidation, generated input, and corrupt-cache miss"
