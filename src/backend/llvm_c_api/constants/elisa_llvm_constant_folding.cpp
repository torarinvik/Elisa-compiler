// llvm/Analysis/ConstantFolding.h behind the C API declared in elisa_llvm_constant_folding.h.
#include "elisa_llvm_constant_folding.h"

#include <llvm/ADT/SmallVector.h>
#include <llvm/Analysis/ConstantFolding.h>
#include <llvm/IR/Constants.h>
#include <llvm/IR/Instruction.h>
#include <llvm/IR/Module.h>
#include <llvm/Support/CBindingWrapping.h>

using namespace llvm;

namespace {
SmallVector<Constant *, 4> constantOperands(LLVMValueRef *operands, uint32_t count) {
  SmallVector<Constant *, 4> Constants;
  for (uint32_t index = 0; index < count; ++index)
    Constants.push_back(unwrap<Constant>(operands[index]));
  return Constants;
}
} // namespace

extern "C" {

LLVMValueRef ElisaLLVMConstantFoldInstructionOperands(LLVMValueRef instruction, LLVMValueRef *operands,
                                                      uint32_t count, LLVMModuleRef module,
                                                      int allow_non_deterministic) {
  return wrap(ConstantFoldInstOperands(unwrap<Instruction>(instruction), constantOperands(operands, count),
                                       unwrap(module)->getDataLayout(), nullptr,
                                       allow_non_deterministic != 0));
}

LLVMValueRef ElisaLLVMConstantFoldIntrinsic(uint32_t id, LLVMValueRef *operands, uint32_t count,
                                            LLVMTypeRef type) {
  return wrap(ConstantFoldIntrinsic(static_cast<Intrinsic::ID>(id), constantOperands(operands, count),
                                    unwrap(type)));
}

LLVMValueRef ElisaLLVMConstantFoldLoad(LLVMValueRef pointer, LLVMTypeRef type, LLVMModuleRef module) {
  return wrap(ConstantFoldLoadFromConstPtr(unwrap<Constant>(pointer), unwrap(type),
                                           unwrap(module)->getDataLayout()));
}

} // extern "C"
