#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -x "$STAGE1" ]]; then
    echo "pymodule-so smoke SKIP (Python 3.14/Homebrew clang/stage1 unavailable)"
    exit 0
fi

PYTHON_CONFIG_NAME="$(basename -- "$PYTHON_CONFIG")"
PYTHON_EXT_SUFFIX="$($PYTHON_BIN -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
CLI_PYTHON_LOG="$WORK/python-cli-wrapper.log"
CLI_PYTHON_WRAPPER="$WORK/python-cli-wrapper"
NESTED_WORK="$WORK/nested/build"
{
    printf '%s\n' '#!/usr/bin/env bash'
    printf 'printf "cli-python-wrapper-used\\n" >> %q\n' "$CLI_PYTHON_LOG"
    printf 'exec %q "$@"\n' "$PYTHON_BIN"
} > "$CLI_PYTHON_WRAPPER"
chmod +x "$CLI_PYTHON_WRAPPER"
PATH="$(dirname -- "$PYTHON_CONFIG"):${PATH}" \
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG_NAME" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" \
    --python "$CLI_PYTHON_WRAPPER" --python-config "$PYTHON_CONFIG" -emit pymodule-so \
    -o "$NESTED_WORK/fastmath.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_export.elisa" >/dev/null
test "$(wc -l < "$CLI_PYTHON_LOG" | tr -d ' ')" -gt 1
test -f "$NESTED_WORK/fastmath.pyi"
"$PYTHON_BIN" -m py_compile "$NESTED_WORK/fastmath.pyi"

PYTHONPATH="$NESTED_WORK" "$PYTHON_BIN" - <<'PY'
import fastmath
assert fastmath.add(2, 3) == 5
assert fastmath.negate(False) is True
assert fastmath.negate(True) is False
assert fastmath.ping() == 42
PY

if PATH="$(dirname -- "$PYTHON_CONFIG"):${PATH}" \
    PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG_NAME" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/not_fastmath" \
    "$ROOT/test/repro/pymodule_export.elisa" >"$WORK/mismatch.log" 2>&1; then
    echo "pymodule-so accepted an output filename that cannot be imported" >&2
    exit 1
fi
grep -Fq "output filename 'not_fastmath${PYTHON_EXT_SUFFIX}' must be named 'fastmath'" "$WORK/mismatch.log"

PLAIN_WORK="$WORK/plain"
mkdir -p "$PLAIN_WORK"
PATH="$(dirname -- "$PYTHON_CONFIG"):${PATH}" \
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG_NAME" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$PLAIN_WORK/fastmath" \
    "$ROOT/test/repro/pymodule_export.elisa" >/dev/null
test -f "$PLAIN_WORK/fastmath${PYTHON_EXT_SUFFIX}"
test -f "$PLAIN_WORK/fastmath.pyi"
PYTHONPATH="$PLAIN_WORK" "$PYTHON_BIN" - <<'PY'
import fastmath
assert fastmath.add(4, 5) == 9
PY

DERIVED_WORK="$WORK/derived"
mkdir -p "$DERIVED_WORK"
(
    cd "$DERIVED_WORK"
    PATH="$(dirname -- "$PYTHON_CONFIG"):${PATH}" \
    PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG_NAME" ELISA_CLANG="$CLANG" \
        bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
        "$ROOT/test/repro/pymodule_export.elisa" >/dev/null
)
test -f "$DERIVED_WORK/fastmath${PYTHON_EXT_SUFFIX}"
test -f "$DERIVED_WORK/fastmath.pyi"
PYTHONPATH="$DERIVED_WORK" "$PYTHON_BIN" - <<'PY'
import fastmath
assert fastmath.add(8, 9) == 17
PY

AUTO_WORK="$WORK/auto-runtime"
mkdir -p "$AUTO_WORK"
PATH="$(dirname -- "$PYTHON_CONFIG"):${PATH}" \
ELISA_STAGE1_BIN="$STAGE1" ELISA_RUNTIME_OBJ="$AUTO_WORK/runtime.o" \
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG_NAME" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$AUTO_WORK/fastmath" \
    "$ROOT/test/repro/pymodule_export.elisa" >/dev/null
test -f "$AUTO_WORK/runtime.o"
test -f "$AUTO_WORK/fastmath${PYTHON_EXT_SUFFIX}"
PYTHONPATH="$AUTO_WORK" "$PYTHON_BIN" - <<'PY'
import fastmath
assert fastmath.add(6, 7) == 13
PY

echo "pymodule-so smoke OK"
