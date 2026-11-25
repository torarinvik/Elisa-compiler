/* C API for questions about one instruction that LLVM's C API does not answer: what it
 * may do to memory, and whether it may run speculatively at another point.
 */
#ifndef ELISA_LLVM_INSTRUCTION_QUERIES_H
#define ELISA_LLVM_INSTRUCTION_QUERIES_H

#include <llvm-c/Core.h>

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

#ifdef __cplusplus
}
#endif

#endif
