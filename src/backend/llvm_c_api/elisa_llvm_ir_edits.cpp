// Implementation of elisa_llvm_ir_edits.h over LLVM's C++ utilities.
#include "elisa_llvm_ir_edits.h"

#include <llvm/ADT/SmallVector.h>
#include <llvm/Analysis/InlineCost.h>
#include <llvm/Analysis/Utils/Local.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/BasicBlock.h>
#include <llvm/IR/Instructions.h>
#include <llvm/IR/Metadata.h>
#include <llvm/IR/Module.h>
#include <llvm/Support/raw_ostream.h>
#include <llvm/Transforms/Utils/BasicBlockUtils.h>
#include <llvm/Transforms/Utils/Cloning.h>
#include <llvm/Transforms/Utils/Local.h>
#include <llvm/Transforms/Utils/ValueMapper.h>

using namespace llvm;

static ValueToValueMapTy *unwrapMap(ElisaValueMapRef map) {
  return reinterpret_cast<ValueToValueMapTy *>(map);
}

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

LLVMValueRef ElisaLLVMCloneFunction(LLVMValueRef function) {
  ValueToValueMapTy Map;
  return wrap(CloneFunction(cast<Function>(unwrap(function)), Map));
}

void ElisaLLVMAdoptFunctionBody(LLVMValueRef function, LLVMValueRef donor) {
  Function &F = *cast<Function>(unwrap(function));
  Function *Donor = cast<Function>(unwrap(donor));
  for (Argument &Arg : Donor->args()) Arg.replaceAllUsesWith(F.getArg(Arg.getArgNo()));
  Donor->replaceAllUsesWith(&F);
  for (BasicBlock &B : F) B.dropAllReferences();
  F.erase(F.begin(), F.end());
  F.splice(F.end(), Donor);
  Donor->eraseFromParent();
}

int ElisaLLVMInlineCall(LLVMValueRef call) {
  InlineFunctionInfo Info;
  return InlineFunction(*cast<CallBase>(unwrap(call)), Info).isSuccess();
}

int ElisaLLVMIsInlineViable(LLVMValueRef function) {
  return isInlineViable(*cast<Function>(unwrap(function))).isSuccess();
}

void ElisaLLVMSplitBlockAndInsertIfThenElse(LLVMValueRef condition, LLVMValueRef before,
                                            LLVMValueRef *then_terminator, LLVMValueRef *else_terminator) {
  Instruction *Then = nullptr, *Else = nullptr;
  SplitBlockAndInsertIfThenElse(unwrap(condition), cast<Instruction>(unwrap(before))->getIterator(), &Then, &Else);
  *then_terminator = wrap(Then);
  *else_terminator = wrap(Else);
}

void ElisaLLVMSetICmpPredicate(LLVMValueRef compare, LLVMIntPredicate predicate) {
  cast<ICmpInst>(unwrap(compare))->setPredicate(static_cast<CmpInst::Predicate>(predicate));
}

void ElisaLLVMRemoveIncomingValue(LLVMValueRef phi, uint32_t index) {
  cast<PHINode>(unwrap(phi))->removeIncomingValue(index, false);
}

LLVMBasicBlockRef ElisaLLVMSplitEdge(LLVMBasicBlockRef from, LLVMBasicBlockRef to) {
  return wrap(SplitEdge(unwrap(from), unwrap(to)));
}

LLVMBasicBlockRef ElisaLLVMSplitCriticalEdge(LLVMValueRef terminator, uint32_t successor, const char *name) {
  return wrap(SplitCriticalEdge(cast<Instruction>(unwrap(terminator)), successor,
                                CriticalEdgeSplittingOptions(), name));
}

LLVMBasicBlockRef ElisaLLVMSplitBlock(LLVMValueRef instruction) {
  Instruction *At = cast<Instruction>(unwrap(instruction));
  return wrap(SplitBlock(At->getParent(), At));
}

ElisaValueMapRef ElisaLLVMCreateValueMap(void) {
  return reinterpret_cast<ElisaValueMapRef>(new ValueToValueMapTy());
}

void ElisaLLVMDisposeValueMap(ElisaValueMapRef map) { delete unwrapMap(map); }

void ElisaLLVMValueMapSet(ElisaValueMapRef map, LLVMValueRef key, LLVMValueRef value) {
  (*unwrapMap(map))[unwrap(key)] = unwrap(value);
}

LLVMValueRef ElisaLLVMValueMapGet(ElisaValueMapRef map, LLVMValueRef key) {
  ValueToValueMapTy &Map = *unwrapMap(map);
  auto Found = Map.find(unwrap(key));
  return Found == Map.end() ? nullptr : wrap(static_cast<Value *>(Found->second));
}

LLVMBasicBlockRef ElisaLLVMCloneBasicBlock(LLVMBasicBlockRef block, ElisaValueMapRef map,
                                           const char *suffix, LLVMValueRef function) {
  return wrap(CloneBasicBlock(unwrap(block), *unwrapMap(map), suffix,
                              cast<Function>(unwrap(function))));
}

void ElisaLLVMRemapInstruction(LLVMValueRef instruction, ElisaValueMapRef map) {
  RemapInstruction(cast<Instruction>(unwrap(instruction)), *unwrapMap(map), RF_IgnoreMissingLocals);
}

void ElisaLLVMRemapInstructionKeepingModule(LLVMValueRef instruction, ElisaValueMapRef map) {
  RemapInstruction(cast<Instruction>(unwrap(instruction)), *unwrapMap(map),
                   RF_NoModuleLevelChanges | RF_IgnoreMissingLocals);
}

int ElisaLLVMMetadataIsDistinct(LLVMMetadataRef node) {
  return cast<MDNode>(unwrap(node))->isDistinct();
}

void ElisaLLVMBlockRemovePredecessor(LLVMBasicBlockRef block, LLVMBasicBlockRef predecessor,
                                     int keep_one_input_phis) {
  unwrap(block)->removePredecessor(unwrap(predecessor), keep_one_input_phis != 0);
}

void ElisaLLVMBlockDropAllReferences(LLVMBasicBlockRef block) { unwrap(block)->dropAllReferences(); }

void ElisaLLVMEraseNamedMetadata(LLVMNamedMDNodeRef node) {
  unwrap(node)->eraseFromParent();
}

LLVMValueRef ElisaLLVMCloneFunctionWithMap(LLVMValueRef function, ElisaValueMapRef map) {
  return wrap(CloneFunction(cast<Function>(unwrap(function)), *unwrapMap(map)));
}

void ElisaLLVMMoveInstructionToBlockEnd(LLVMValueRef instruction, LLVMBasicBlockRef block) {
  BasicBlock *Destination = unwrap(block);
  unwrap<Instruction>(instruction)->moveBefore(*Destination, Destination->end());
}

void ElisaLLVMMoveInstructionBefore(LLVMValueRef instruction, LLVMValueRef before) {
  unwrap<Instruction>(instruction)->moveBefore(unwrap<Instruction>(before)->getIterator());
}

LLVMValueRef ElisaLLVMEmitGEPOffset(LLVMBuilderRef builder, LLVMValueRef gep) {
  auto *Instruction = cast<GetElementPtrInst>(unwrap(gep));
  return wrap(emitGEPOffset(unwrap(builder), Instruction->getModule()->getDataLayout(), Instruction,
                            /*NoAssumptions=*/true));
}

void ElisaLLVMSetCallAttributesFromFunction(LLVMValueRef call, LLVMValueRef function) {
  cast<CallBase>(unwrap(call))->setAttributes(cast<Function>(unwrap(function))->getAttributes());
}

} // extern "C"
