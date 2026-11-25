/* C API for the IR edits the Elisa-hosted passes need that LLVM's own C
 * API does not offer, and reading a module from an IR file. Each is a thin
 * wrapper of one LLVM C++ utility, so a pass written in Elisa edits the IR
 * exactly as its C++ original did. */
#ifndef ELISA_LLVM_IR_EDITS_H
#define ELISA_LLVM_IR_EDITS_H

#include <llvm-c/Core.h>
#include <llvm-c/TargetMachine.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* An llvm::ValueToValueMapTy: what the block cloning below maps each
 * original value (blocks included, as LLVMBasicBlockAsValue) to. */
typedef struct ElisaOpaqueValueMap *ElisaValueMapRef;

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
/* ConstantFoldTerminator(block, delete_dead_conditions): folds the block's
 * terminator when its condition is a constant; whether it changed. */
int ElisaLLVMConstantFoldTerminator(LLVMBasicBlockRef block, int delete_dead_conditions);

/* llvm::CloneFunction with an empty value map: a copy of the function,
 * appended to its module. */
LLVMValueRef ElisaLLVMCloneFunction(LLVMValueRef function);

/* Moves the body of `donor`, a copy of `function` with the same signature, into
 * `function`: the donor's arguments and uses become the function's, the function's old
 * blocks are deleted, the donor's blocks are spliced in and the empty donor is erased. */
void ElisaLLVMAdoptFunctionBody(LLVMValueRef function, LLVMValueRef donor);

/* llvm::InlineFunction of the call with default InlineFunctionInfo; whether
 * the call was inlined. */
int ElisaLLVMInlineCall(LLVMValueRef call);

/* llvm::isInlineViable: whether the function's body can be inlined at all
 * (no indirect branches, no `returns_twice` calls, no dynamic stack recovery). */
int ElisaLLVMIsInlineViable(LLVMValueRef function);
/* llvm::getAttributeBasedInliningDecision for the direct call, with the callee's
 * TargetTransformInfo and the TargetLibraryInfo of a PassBuilder for `machine` (NULL:
 * none): 0 when the attributes forbid inlining, 1 when they allow it or do not decide. */
int ElisaLLVMAttributesAllowInlining(LLVMValueRef call, LLVMTargetMachineRef machine);

/* llvm::SplitBlockAndInsertIfThenElse(condition, before): splits the block before
 * `before` and branches on `condition` to a new then block and else block that both
 * fall through to it; stores their terminators. */
void ElisaLLVMSplitBlockAndInsertIfThenElse(LLVMValueRef condition, LLVMValueRef before,
                                            LLVMValueRef *then_terminator, LLVMValueRef *else_terminator);

/* ICmpInst::setPredicate: `predicate` is an LLVMIntPredicate. */
void ElisaLLVMSetICmpPredicate(LLVMValueRef compare, LLVMIntPredicate predicate);

/* PHINode::removeIncomingValue(index, false): drops the phi's edge `index`
 * and keeps the phi even when no edge is left. */
void ElisaLLVMRemoveIncomingValue(LLVMValueRef phi, uint32_t index);

/* BasicBlock::splitBasicBlock(instruction, name): the new block holds INSTRUCTION
 * and everything after it, and the old block branches to it. */
LLVMBasicBlockRef ElisaLLVMSplitBasicBlock(LLVMValueRef instruction, const char *name);
/* llvm::SplitBlock(parent, instruction) without analyses: moves the
 * instruction and everything after it into a new block named
 * "<parent>.split", placed after the parent, which now branches to it. */
LLVMBasicBlockRef ElisaLLVMSplitBlock(LLVMValueRef instruction);
/* llvm::SplitEdge(from, to) without analyses: the block placed on the edge. */
LLVMBasicBlockRef ElisaLLVMSplitEdge(LLVMBasicBlockRef from, LLVMBasicBlockRef to);
/* llvm::SplitCriticalEdge(terminator, successor) with default options and no analyses:
 * the block named `name` placed on the edge, or null when the edge is not critical. */
LLVMBasicBlockRef ElisaLLVMSplitCriticalEdge(LLVMValueRef terminator, uint32_t successor, const char *name);

ElisaValueMapRef ElisaLLVMCreateValueMap(void);
void ElisaLLVMDisposeValueMap(ElisaValueMapRef map);
void ElisaLLVMValueMapSet(ElisaValueMapRef map, LLVMValueRef key, LLVMValueRef value);
/* The value KEY maps to, or NULL. */
LLVMValueRef ElisaLLVMValueMapGet(ElisaValueMapRef map, LLVMValueRef key);

/* llvm::CloneBasicBlock: a copy of the block appended to the function, its
 * name and its instructions' names suffixed; every original instruction is
 * mapped to its copy. Operands still name the original values. */
LLVMBasicBlockRef ElisaLLVMCloneBasicBlock(LLVMBasicBlockRef block, ElisaValueMapRef map,
                                           const char *suffix, LLVMValueRef function);

/* llvm::RemapInstruction with RF_IgnoreMissingLocals: rewrites the
 * instruction's operands and metadata through the map, leaving values the
 * map lacks alone. */
void ElisaLLVMRemapInstruction(LLVMValueRef instruction, ElisaValueMapRef map);
/* The same with RF_NoModuleLevelChanges as well: globals and metadata keep their
 * identity, so distinct metadata is not duplicated. */
void ElisaLLVMRemapInstructionKeepingModule(LLVMValueRef instruction, ElisaValueMapRef map);

/* MDNode::isDistinct. */
int ElisaLLVMMetadataIsDistinct(LLVMMetadataRef node);

/* BasicBlock::removePredecessor: drops the block's phi entries for the edge
 * from `predecessor`; unless `keep_one_input_phis`, a phi left with one
 * value is replaced by it. */
void ElisaLLVMBlockRemovePredecessor(LLVMBasicBlockRef block, LLVMBasicBlockRef predecessor,
                                     int keep_one_input_phis);

/* BasicBlock::dropAllReferences: every instruction of the block drops its
 * operands, so blocks that refer to each other can then be erased in any order. */
void ElisaLLVMBlockDropAllReferences(LLVMBasicBlockRef block);

/* NamedMDNode::eraseFromParent. */
void ElisaLLVMEraseNamedMetadata(LLVMNamedMDNodeRef node);

/* llvm::CloneFunction(function, map): a copy added to the module. An argument the map
 * already maps is replaced by its value and dropped from the copy's parameters. */
LLVMValueRef ElisaLLVMCloneFunctionWithMap(LLVMValueRef function, ElisaValueMapRef map);

/* Instruction::moveBefore(*block, block->end()): moves the instruction, keeping its
 * debug location and metadata, to the end of the block. */
void ElisaLLVMMoveInstructionToBlockEnd(LLVMValueRef instruction, LLVMBasicBlockRef block);

/* Instruction::moveBefore(before): moves the instruction, keeping its debug location and
 * metadata, to just before BEFORE. */
void ElisaLLVMMoveInstructionBefore(LLVMValueRef instruction, LLVMValueRef before);

/* CallBase::setAttributes(function->getAttributes()): the call takes the function's
 * whole attribute list, including its parameter and return attributes. */
void ElisaLLVMSetCallAttributesFromFunction(LLVMValueRef call, LLVMValueRef function);

/* llvm::emitGEPOffset(builder, layout, gep, NoAssumptions = true): the GEP's byte offset
 * from its pointer operand as an index-width integer, built at the builder's position with
 * wrapping arithmetic. Constant offsets fold to a constant. */
LLVMValueRef ElisaLLVMEmitGEPOffset(LLVMBuilderRef builder, LLVMValueRef gep);

#ifdef __cplusplus
}
#endif
#endif
