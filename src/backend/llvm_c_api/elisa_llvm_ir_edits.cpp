// Implementation of elisa_llvm_ir_edits.h over LLVM's C++ utilities.
#include "elisa_llvm_ir_edits.h"

#include <llvm/ADT/SmallVector.h>
#include <llvm/IR/BasicBlock.h>
#include <llvm/IR/Instructions.h>
#include <llvm/IR/Module.h>
#include <llvm/Support/raw_ostream.h>
#include <llvm/Transforms/Utils/BasicBlockUtils.h>
#include <llvm/Transforms/Utils/Local.h>

using namespace llvm;

extern "C" {

void ElisaLLVMSetIncomingBlock(LLVMValueRef phi, uint32_t index, LLVMBasicBlockRef block) {
  cast<PHINode>(unwrap(phi))->setIncomingBlock(index, unwrap(block));
}

void ElisaLLVMRemoveIncomingForBlock(LLVMValueRef phi, LLVMBasicBlockRef block) {
  cast<PHINode>(unwrap(phi))->removeIncomingValue(unwrap(block), false);
}

void ElisaLLVMDeleteDeadBlocks(LLVMBasicBlockRef *blocks, uint32_t count) {
  SmallVector<BasicBlock *, 64> Dead;
  for (uint32_t I = 0; I < count; ++I) Dead.push_back(unwrap(blocks[I]));
  DeleteDeadBlocks(Dead);
}

void ElisaLLVMRecursivelyDeleteTriviallyDeadInstructions(LLVMValueRef value) {
  RecursivelyDeleteTriviallyDeadInstructions(unwrap(value));
}

int ElisaLLVMRemoveUnreachableBlocks(LLVMValueRef function) {
  return removeUnreachableBlocks(*cast<Function>(unwrap(function)));
}

void ElisaLLVMSetICmpPredicate(LLVMValueRef compare, LLVMIntPredicate predicate) {
  cast<ICmpInst>(unwrap(compare))->setPredicate(static_cast<CmpInst::Predicate>(predicate));
}

} // extern "C"
