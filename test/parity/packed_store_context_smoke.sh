#!/usr/bin/env bash
# A packed-hierarchy handle is an INDEX into a store. A body that reaches such a
# value only through a GLOBAL has no store in scope, so there is nothing to decode
# the index against -- stage0 rejects that outright ("packed enum X decode requires
# store context").
#
# stage1 accepted it. The common-field WRITE path extracted the store state out of
# `runtime.active_store` without checking one was active; with no store that value
# is zeroed, so the emitter built an ExtractValue on garbage and the program
# segfaulted at runtime. A miscompile, not a diagnostic.
#
# This gate pins the DECLINE. It cannot live in the differential suite: stage0
# rejects the program too, and the runner skips a case stage0 will not compile, so
# a stage1 regression there would read as SKIP rather than as a failure.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 60 "$@"; else "$@"; fi; }
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
[ -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ] || { echo "packed_store_context_smoke SKIP: no stage1 binary"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/no_store.elisa" <<'EOF'
enum Widget:
    common:
        @storage(inline)
        pressed: mutable bool
    pass

enum Control is Widget:
    Button(size: f32)

global mutable active: Widget? = null

def release() -> void:
    if active is held:
        held.pressed <- false
    active <- null

def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        region ui(65536):
            w: Widget = Control.Button(pressed: true, size: 1.0)
            active <- w
            release()
            return 1 if w.pressed
            return 0
EOF

RUN "$STAGE1" -o "$WORK/no_store.o" "$WORK/no_store.elisa" >"$WORK/no_store.log" 2>&1
rc=$?
if [ "$rc" -eq 0 ]; then
    echo "packed_store_context_smoke FAIL: stage1 compiled a common write with no store in scope"
    echo "  (rc 0). Either the guard in codegen_stmt_assign_flow regressed, or stage1 grew a way"
    echo "  to reach the store from a global -- if the latter, this gate needs rewriting, not"
    echo "  deleting."
    exit 1
fi
if ! grep -q "declined" "$WORK/no_store.log"; then
    echo "packed_store_context_smoke FAIL: stage1 rejected the program (rc=$rc) but not as a decline:"
    sed 's/^/    /' "$WORK/no_store.log" | head -5
    exit 1
fi

# The SAME write, with a Widget parameter putting the store in scope, must still compile:
# the guard has to reject the storeless shape without taking the working one with it.
cat > "$WORK/with_store.elisa" <<'EOF'
enum Widget:
    common:
        @storage(inline)
        pressed: mutable bool
    pass

enum Control is Widget:
    Button(size: f32)

global mutable active: Widget? = null

def release(root: Widget) -> void:
    if active is held:
        held.pressed <- false
    active <- null

def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        region ui(65536):
            w: Widget = Control.Button(pressed: true, size: 1.0)
            active <- w
            release(w)
            return 1 if w.pressed
            return 0
EOF

RUN "$STAGE1" -o "$WORK/with_store.o" "$WORK/with_store.elisa" >"$WORK/with_store.log" 2>&1
if [ $? -ne 0 ]; then
    echo "packed_store_context_smoke FAIL: the guard also rejected the shape that HAS a store:"
    sed 's/^/    /' "$WORK/with_store.log" | head -5
    exit 1
fi

echo "packed_store_context_smoke OK: storeless common write declines, stored one compiles"
