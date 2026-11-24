/* C API for the IR edits the Elisa-hosted passes need that LLVM's own C
 * API does not offer, and reading a module from an IR file. Each is a thin
 * wrapper of one LLVM C++ utility, so a pass written in Elisa edits the IR
 * exactly as its C++ original did. */
#ifndef ELISA_LLVM_IR_EDITS_H
#define ELISA_LLVM_IR_EDITS_H

#include <llvm-c/Core.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* PHINode::setIncomingBlock: the phi's incoming edge `index` now comes from
 * `block`; its value is unchanged. */
void ElisaLLVMSetIncomingBlock(LLVMValueRef phi, uint32_t index, LLVMBasicBlockRef block);

/* PHINode::removeIncomingValue(block, false): drops the phi's edge from the
 * block and keeps the phi even when no edge is left. */
void ElisaLLVMRemoveIncomingForBlock(LLVMValueRef phi, LLVMBasicBlockRef block);

/* llvm::DeleteDeadBlocks: deletes the blocks, which may branch to each
 * other, after removing their edges from the phis of surviving successors. */
void ElisaLLVMDeleteDeadBlocks(LLVMBasicBlockRef *blocks, uint32_t count);

/* llvm::RecursivelyDeleteTriviallyDeadInstructions: deletes the value if it
 * is an unused instruction without side effects, then every operand that
 * becomes one. */
void ElisaLLVMRecursivelyDeleteTriviallyDeadInstructions(LLVMValueRef value);

/* llvm::removeUnreachableBlocks: deletes the blocks the function's entry
 * cannot reach; whether any was deleted. */
int ElisaLLVMRemoveUnreachableBlocks(LLVMValueRef function);

/* ICmpInst::setPredicate: `predicate` is an LLVMIntPredicate. */
void ElisaLLVMSetICmpPredicate(LLVMValueRef compare, LLVMIntPredicate predicate);

#ifdef __cplusplus
}
#endif
#endif
