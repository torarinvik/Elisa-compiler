#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_project_driver_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
mkdir -p "$ROOT/build"
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$ROOT/build/easm_project_driver.o" "$ROOT/test/breadth/easm_project_driver.elisa" 2>"$ROOT/build/easm_project_driver.log"; then
    echo "easm_project_driver_smoke FAILED: project driver did not compile"
    sed -n '1,30p' "$ROOT/build/easm_project_driver.log"
    exit 1
fi
if ! clang -o "$ROOT/build/easm_project_driver" "$ROOT/build/easm_project_driver.o" -L"$("$LLVM_CONFIG" --libdir)" -lLLVM -Wl,-rpath,"$("$LLVM_CONFIG" --libdir)"; then
    echo "easm_project_driver_smoke FAILED: project driver did not link"
    exit 1
fi
fixture="$ROOT/build/easm_project_driver_fixture"
rm -rf "$fixture"
mkdir -p "$fixture/deps"
cp "$ROOT/test/fixtures/easm/template_thunk.easm" "$fixture/deps/one.easm"
cp "$ROOT/test/fixtures/easm/template_thunk.easm" "$fixture/deps/two.easm"
report=$(python3 "$ROOT/scripts/easm_project_driver.py" "$fixture" --driver "$ROOT/build/easm_project_driver" --mode report)
case "$report" in
    *"Modules:"*"Issue duplicate-project-module"*) : ;;
    *) echo "easm_project_driver_smoke FAILED: unexpected report"; printf '%s\n' "$report"; exit 1 ;;
esac
single="$ROOT/build/easm_project_driver_single"
rm -rf "$single"
mkdir -p "$single"
cp "$ROOT/test/fixtures/easm/project_export.easm" "$single/one.easm"
assembly=$(python3 "$ROOT/scripts/easm_project_driver.py" "$single" --driver "$ROOT/build/easm_project_driver" --mode assembly)
case "$assembly" in
    *".globl"*"finish"*) : ;;
    *) echo "easm_project_driver_smoke FAILED: unexpected native assembly"; printf '%s\n' "$assembly"; exit 1 ;;
esac
invalid="$ROOT/build/easm_project_driver_invalid"
rm -rf "$invalid"
mkdir -p "$invalid"
cp "$ROOT/test/fixtures/easm/lockstep_invalid_target.easm" "$invalid/invalid.easm"
invalid_report=$(python3 "$ROOT/scripts/easm_project_driver.py" "$invalid" --driver "$ROOT/build/easm_project_driver" --mode report)
case "$invalid_report" in
    *"Issue missing-capability"*) : ;;
    *) echo "easm_project_driver_smoke FAILED: lockstep target bypassed full verifier"; printf '%s\n' "$invalid_report"; exit 1 ;;
esac
artifact_root="$ROOT/build/easm_project_driver_artifact"
rm -rf "$artifact_root"
mkdir -p "$artifact_root"
cp "$ROOT/test/fixtures/easm/template_thunk.easm" "$artifact_root/template.easm"
cp "$ROOT/test/fixtures/easm/project_export.easm" "$artifact_root/export.easm"
cp "$ROOT/test/fixtures/easm/lockstep_equiv.easm" "$artifact_root/lockstep.easm"
artifact=$(python3 "$ROOT/scripts/easm_project_driver.py" "$artifact_root" --driver "$ROOT/build/easm_project_driver" --mode artifact --llvm-mc "${LLVM_MC:-/opt/homebrew/opt/llvm/bin/llvm-mc}" --lockstep-symbolic)
python3 -c 'import json,sys; a=json.loads(sys.argv[1]); assert "template" in a["report"]; assert "finish" in a["assembly"] or ".text" in a["assembly"]; assert a["templates"] and a["templates"][0]["image"]["patches"]' "$artifact" || {
    echo "easm_project_driver_smoke FAILED: template artifact integration was incomplete"
    exit 1
}
python3 -c 'import json,sys; a=json.loads(sys.argv[1]); assert any(r["status"] == "proved" for r in a["lockstep"])' "$artifact" || {
    echo "easm_project_driver_smoke FAILED: lockstep proof was not integrated"
    exit 1
}
echo "easm_project_driver_smoke OK"
