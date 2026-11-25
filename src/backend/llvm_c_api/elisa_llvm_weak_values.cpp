// llvm::WeakTrackingVH lists behind the C API declared in elisa_llvm_weak_values.h.
#include "elisa_llvm_weak_values.h"

#include <llvm/ADT/SmallVector.h>
#include <llvm/IR/ValueHandle.h>
#include <llvm/Support/CBindingWrapping.h>

using namespace llvm;

using WeakValues = SmallVector<WeakTrackingVH, 8>;

DEFINE_SIMPLE_CONVERSION_FUNCTIONS(WeakValues, ElisaWeakValuesRef)

extern "C" {

ElisaWeakValuesRef ElisaLLVMCreateWeakValues(void) { return wrap(new WeakValues()); }

void ElisaLLVMDisposeWeakValues(ElisaWeakValuesRef values) { delete unwrap(values); }

void ElisaLLVMWeakValuesPush(ElisaWeakValuesRef values, LLVMValueRef value) {
  unwrap(values)->push_back(unwrap(value));
}

uint32_t ElisaLLVMWeakValuesCount(ElisaWeakValuesRef values) {
  return static_cast<uint32_t>(unwrap(values)->size());
}

LLVMValueRef ElisaLLVMWeakValueAt(ElisaWeakValuesRef values, uint32_t index) {
  return wrap(static_cast<Value *>((*unwrap(values))[index]));
}

} // extern "C"
