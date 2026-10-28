#!/usr/bin/env bash
# Direct LLVM-C safety probes: rejected memory/poison cases must not rewrite.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
source "$ROOT/scripts/platform.sh"
TIMEOUT=$(command -v gtimeout || command -v timeout)
run() { "$TIMEOUT" -k 1s 29s "$@"; }
major=$("$LLVM_CONFIG" --version | cut -d. -f1)
[[ "$major" == 23 && "$ELISA_HOST_OS" == Darwin ]] || { echo 'split-half raw probes require qualified Darwin and LLVM 23'; exit 0; }
T=$(mktemp -d "${TMPDIR:-/tmp}/stage1-split-raw.XXXXXX")
trap 'rm -rf "$T"' EXIT
export ELISA_RUNTIME_OBJ=none
python3 - "$ROOT" "$T" <<'PY'
import pathlib,sys
root,out=map(pathlib.Path,sys.argv[1:]); template=(root/'test/parity/stage1_split_half_raw_template.elisa.in').read_text()
base={'@STORE_A@':'    _ = LLVMBuildStore(builder, a, aslot)', '@LOAD_A@':'    av1: LLVMValueRef = LLVMBuildLoad2(builder, ty, aslot, "a1")', '@SHIFT_A@':'    ah: LLVMValueRef = LLVMBuildLShr(builder, av2, shift, "ah")', '@SHIFT_HIGH@':'    shifted: LLVMValueRef = LLVMBuildShl(builder, hm, shift, "shifted")', '@EXPECTED@':'0'}
cases={'positive':{'@EXPECTED@':'1'}, 'multiple_store':{'@STORE_A@':base['@STORE_A@']+'\n    _ = LLVMBuildStore(builder, b, aslot)'}, 'volatile':{'@STORE_A@':'    bad_store: LLVMValueRef = LLVMBuildStore(builder, a, aslot)\n    LLVMSetVolatile(bad_store, 1)'}, 'atomic':{'@STORE_A@':'    bad_store: LLVMValueRef = LLVMBuildStore(builder, a, aslot)\n    LLVMSetOrdering(bad_store, 2)\n    LLVMSetAlignment(bad_store, 8)'}, 'escape':{'@STORE_A@':'    _ = LLVMBuildPtrToInt(builder, aslot, ty, "escape")\n'+base['@STORE_A@']}, 'cross_block':{'@LOAD_A@':'    other: LLVMBasicBlockRef = LLVMAppendBasicBlockInContext(ctx, fn_value, "other")\n    _ = LLVMBuildBr(builder, other)\n    LLVMPositionBuilderAtEnd(builder, other)\n'+base['@LOAD_A@']}, 'exact':{'@SHIFT_A@':base['@SHIFT_A@']+'\n    LLVMSetExact(ah, 1)'}, 'nuw':{'@SHIFT_HIGH@':base['@SHIFT_HIGH@']+'\n    LLVMSetNUW(shifted, 1)'}, 'before_store':{'@STORE_A@':'    av1: LLVMValueRef = LLVMBuildLoad2(builder, ty, aslot, "a1")\n'+base['@STORE_A@'], '@LOAD_A@':''}}
for name,changes in cases.items():
    values=base|changes; text=template.replace('@BACKEND@',str(root/'src/backend'))
    for key,value in values.items(): text=text.replace(key,value)
    (out/f'{name}.elisa').write_text(text)
PY
for test_case in positive multiple_store volatile atomic escape cross_block exact nuw before_store; do
  run "$ROOT/scripts/elisac_stage1.sh" -O0 -o "$T/$test_case.o" "$T/$test_case.elisa"
  run "${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}" "$T/$test_case.o" "$ROOT/build/runtime/elisacore_runtime.o" -L"$ELISA_LLVM_LIBDIR" $ELISA_LLVM_LIBS $ELISA_LINK_EXE_FLAGS -Wl,-rpath,"$ELISA_LLVM_LIBDIR" -o "$T/$test_case"
  run "$T/$test_case"
done
echo 'stage1 split-half raw safety probes passed'
