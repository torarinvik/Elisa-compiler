// Implementation of elisa_llvm_instruction_queries.h.
#include "elisa_llvm_instruction_queries.h"

#include <llvm/Analysis/ValueTracking.h>
#include <llvm/IR/InstrTypes.h>
#include <llvm/IR/Instruction.h>
#include <llvm/IR/IntrinsicInst.h>
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

} // extern "C"
