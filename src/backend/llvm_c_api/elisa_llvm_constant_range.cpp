// llvm::ConstantRange behind the C API declared in elisa_llvm_constant_range.h.
#include "elisa_llvm_constant_range.h"

#include <llvm/IR/ConstantRange.h>
#include <llvm/IR/Constants.h>
#include <llvm/IR/InstrTypes.h>
#include <llvm/Support/CBindingWrapping.h>

using namespace llvm;

DEFINE_SIMPLE_CONVERSION_FUNCTIONS(ConstantRange, ElisaConstantRangeRef)

static const APInt &constantValue(LLVMValueRef constant) {
  return cast<ConstantInt>(unwrap(constant))->getValue();
}

extern "C" {

ElisaConstantRangeRef ElisaLLVMConstantRangeAllowedByCompare(LLVMIntPredicate predicate,
                                                             LLVMValueRef constant) {
  auto compare = static_cast<CmpInst::Predicate>(predicate);
  return wrap(new ConstantRange(
      ConstantRange::makeAllowedICmpRegion(compare, ConstantRange(constantValue(constant)))));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeSubtract(ElisaConstantRangeRef range,
                                                     LLVMValueRef constant) {
  return wrap(new ConstantRange(unwrap(range)->sub(ConstantRange(constantValue(constant)))));
}

int ElisaLLVMConstantRangeIsEmpty(ElisaConstantRangeRef range) {
  return unwrap(range)->isEmptySet();
}

int ElisaLLVMConstantRangeReachesSignedMax(ElisaConstantRangeRef range) {
  return unwrap(range)->getSignedMax().isMaxSignedValue();
}

int ElisaLLVMConstantRangeSignedMinIsNegative(ElisaConstantRangeRef range) {
  return unwrap(range)->getSignedMin().isNegative();
}

int ElisaLLVMConstantRangeContains(ElisaConstantRangeRef range, uint64_t value) {
  return unwrap(range)->contains(APInt(unwrap(range)->getBitWidth(), value));
}

int ElisaLLVMConstantRangeUnsignedMaxAtMost(ElisaConstantRangeRef range, LLVMValueRef constant) {
  return unwrap(range)->getUnsignedMax().ule(constantValue(constant));
}

void ElisaLLVMDisposeConstantRange(ElisaConstantRangeRef range) { delete unwrap(range); }

} // extern "C"
