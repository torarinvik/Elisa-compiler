// Implementation of elisa_llvm_instruction_queries.h.
#include "elisa_llvm_instruction_queries.h"

#include <llvm/Analysis/MemoryLocation.h>
#include <llvm/Analysis/ValueTracking.h>
#include <llvm/IR/InstrTypes.h>
#include <llvm/IR/Instruction.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/IR/Operator.h>
#include <llvm/Support/CBindingWrapping.h>

using namespace llvm;

extern "C" {

int ElisaLLVMMayHaveSideEffects(LLVMValueRef instruction) {
  return cast<Instruction>(unwrap(instruction))->mayHaveSideEffects();
}

int ElisaLLVMMayReadOrWriteMemory(LLVMValueRef instruction) {
  return cast<Instruction>(unwrap(instruction))->mayReadOrWriteMemory();
}

int ElisaLLVMMayReadFromMemory(LLVMValueRef instruction) {
  return cast<Instruction>(unwrap(instruction))->mayReadFromMemory();
}

int ElisaLLVMMayWriteToMemory(LLVMValueRef instruction) {
  return cast<Instruction>(unwrap(instruction))->mayWriteToMemory();
}

int ElisaLLVMIsSafeToSpeculativelyExecuteAt(LLVMValueRef instruction, LLVMValueRef context) {
  return isSafeToSpeculativelyExecute(cast<Instruction>(unwrap(instruction)),
                                      cast<Instruction>(unwrap(context)));
}

int ElisaLLVMCallOnlyReadsMemory(LLVMValueRef call) { return cast<CallBase>(unwrap(call))->onlyReadsMemory(); }

int ElisaLLVMCallOnlyAccessesInaccessibleMemory(LLVMValueRef call) {
  return cast<CallBase>(unwrap(call))->onlyAccessesInaccessibleMemory();
}

unsigned ElisaLLVMMemoryIntrinsicDestinationAlignment(LLVMValueRef intrinsic) {
  MaybeAlign Alignment = cast<MemIntrinsic>(unwrap(intrinsic))->getDestAlign();
  return Alignment ? static_cast<unsigned>(Alignment->value()) : 0;
}

int ElisaLLVMGEPConstantOffset(LLVMValueRef gep, int64_t *offset) {
  auto *Address = cast<GEPOperator>(unwrap(gep));
  const DataLayout &Layout = cast<Instruction>(Address)->getDataLayout();
  APInt Offset(Layout.getIndexTypeSizeInBits(Address->getType()), 0);
  if (!Address->accumulateConstantOffset(Layout, Offset)) return 0;
  *offset = Offset.getSExtValue();
  return 1;
}

LLVMValueRef ElisaLLVMWrittenLocationPointer(LLVMValueRef instruction) {
  auto *Writer = cast<Instruction>(unwrap(instruction));
  std::optional<MemoryLocation> Location = MemoryLocation::getOrNone(Writer);
  if (!Location) {
    auto *Fill = dyn_cast<AnyMemIntrinsic>(Writer);
    if (!Fill) return nullptr;
    Location = MemoryLocation::getForDest(Fill);
  }
  return wrap(const_cast<Value *>(Location->Ptr));
}

LLVMValueRef ElisaLLVMFirstInsertionPoint(LLVMBasicBlockRef block) {
  BasicBlock *Block = unwrap(block);
  auto Point = Block->getFirstInsertionPt();
  return Point == Block->end() ? nullptr : wrap(&*Point);
}

} // extern "C"
