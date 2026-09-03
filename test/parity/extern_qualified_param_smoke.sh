#!/usr/bin/env bash
# `extern f(r: Module::Struct&)` must resolve its referent.
#
# The extern side table keeps only the type's HEAD name, and the scanner took the
# first identifier after the colon -- which for a qualified type is the MODULE.
# Structs are registered under their bare name with the module as owner, so the
# lookup found nothing, the parameter fell back to `void&`, and every call site
# declined because a real struct cannot coerce into it. The function was silently
# dropped from the object; the first symptom was an undefined symbol at link.
#
# Not a differential case: the program needs a definition for the extern symbol to
# link and run, which a self-contained fixture cannot supply. This checks the
# emitted object instead.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
[ -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ] || { echo "extern_qualified_param_smoke SKIP: no stage1 binary"; exit 0; }
command -v nm >/dev/null 2>&1 || { echo "extern_qualified_param_smoke SKIP: no nm"; exit 0; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/qualified.elisa" <<'EOF'
struct Plain:
    kind: i32

module M:
    public:
        struct Rec:
            kind: i32

extern take_plain(r: Plain&) -> void
extern take_qualified(r: M::Rec&) -> void

def send_plain() -> void:
    value: mutable Plain = Plain{kind: 1}
    take_plain(value)

def send_qualified() -> void:
    value: mutable M::Rec = M::Rec{kind: 1}
    take_qualified(value)

def main() -> i64:
    return 0
EOF

"$STAGE1" -o "$WORK/qualified.o" "$WORK/qualified.elisa" >"$WORK/log" 2>&1 || {
    echo "extern_qualified_param_smoke FAIL: the fixture did not compile"; sed 's/^/    /' "$WORK/log" | head -5; exit 1; }

missing=0
for fn in send_plain send_qualified; do
    nm "$WORK/qualified.o" | grep -q "_$fn\$" || { echo "  MISSING $fn"; missing=1; }
done
if [ "$missing" -ne 0 ]; then
    echo "extern_qualified_param_smoke FAIL: a caller was dropped from the object."
    echo "  An extern parameter whose referent does not resolve becomes void&, which no"
    echo "  struct can coerce into, so the call declines and the function is stripped."
    exit 1
fi
echo "extern_qualified_param_smoke OK: plain and module-qualified extern referents both resolve"
