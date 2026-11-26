/* C API for questions about one instruction that LLVM's C API does not answer: what it
 * may do to memory, and whether it may run speculatively at another point.
 */
#ifndef ELISA_LLVM_INSTRUCTION_QUERIES_H
#define ELISA_LLVM_INSTRUCTION_QUERIES_H

#include <llvm-c/Core.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Instruction::mayHaveSideEffects. */
int ElisaLLVMMayHaveSideEffects(LLVMValueRef instruction);
/* Instruction::mayReadOrWriteMemory. */
int ElisaLLVMMayReadOrWriteMemory(LLVMValueRef instruction);
/* Instruction::mayReadFromMemory. */
int ElisaLLVMMayReadFromMemory(LLVMValueRef instruction);
/* Instruction::mayWriteToMemory. */
int ElisaLLVMMayWriteToMemory(LLVMValueRef instruction);
/* llvm::isSafeToSpeculativelyExecute(instruction, context) with no assumption cache,
 * dominator tree or library info: the instruction cannot trap or have side effects when it
 * runs before `context`, a terminator or other instruction. */
int ElisaLLVMIsSafeToSpeculativelyExecuteAt(LLVMValueRef instruction, LLVMValueRef context);
/* CallBase::onlyReadsMemory: the call, by its own or its callee's attributes, at most reads memory. */
int ElisaLLVMCallOnlyReadsMemory(LLVMValueRef call);
/* CallBase::onlyAccessesInaccessibleMemory: the call touches only memory no program code
 * reads (a trap's). */
int ElisaLLVMCallOnlyAccessesInaccessibleMemory(LLVMValueRef call);
/* MemIntrinsic::getDestAlign in bytes, or 0 when the destination carries no alignment. */
unsigned ElisaLLVMMemoryIntrinsicDestinationAlignment(LLVMValueRef intrinsic);
/* GEPOperator::accumulateConstantOffset of one GEP under its data layout: nonzero, with the
 * byte offset (at the index width, sign-extended to 64 bits) in *offset, when every index is
 * constant. */
int ElisaLLVMGEPConstantOffset(LLVMValueRef gep, int64_t *offset);
/* The pointer of MemoryLocation::getOrNone(instruction), or of getForDest for a memory
 * intrinsic: the memory a write through the instruction lands in, or null when it is
 * not one location (a call). */
LLVMValueRef ElisaLLVMWrittenLocationPointer(LLVMValueRef instruction);
/* BasicBlock::getFirstInsertionPt: the first instruction after the phis and any
 * landing pad, or null when the block has no place to insert. */
LLVMValueRef ElisaLLVMFirstInsertionPoint(LLVMBasicBlockRef block);

#ifdef __cplusplus
}
#endif

#endif
