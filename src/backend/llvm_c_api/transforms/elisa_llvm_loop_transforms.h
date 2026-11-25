/* C API for LLVM's loop transformation utilities, which the C API does not offer:
 * loop-simplify and LCSSA forms, peeling and unrolling. Each works on a loop of a
 * function's analyses (elisa_llvm_analysis.h) and keeps those analyses up to date as
 * the C++ utility does; a caller that changed the loop structure invalidates them. */
#ifndef ELISA_LLVM_LOOP_TRANSFORMS_H
#define ELISA_LLVM_LOOP_TRANSFORMS_H

#include "../analysis/elisa_llvm_analysis.h"
#include "elisa_llvm_ir_edits.h"

#ifdef __cplusplus
extern "C" {
#endif

/* The function's top-level loops in LoopInfo's order, and a loop's direct subloops. */
uint32_t ElisaLLVMTopLevelLoopCount(ElisaFunctionAnalysesRef analyses);
ElisaLoopRef ElisaLLVMTopLevelLoopAt(ElisaFunctionAnalysesRef analyses, uint32_t index);
ElisaLoopRef ElisaLLVMLoopSubLoopAt(ElisaLoopRef loop, uint32_t index);

/* ScalarEvolution::forgetLoop(loop), when the analyses have built ScalarEvolution. */
void ElisaLLVMForgetLoop(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop);
/* AssumptionCache::registerAssumption of the `llvm.assume` call, when the analyses have
 * built the cache (one built later finds it anyway). */
void ElisaLLVMRegisterAssumption(ElisaFunctionAnalysesRef analyses, LLVMValueRef assume);

/* Loop::makeLoopInvariant(value, changed, insert_before) without MemorySSA or scalar
 * evolution: whether the value is now invariant in the loop, its instructions (and theirs)
 * moved before `insert_before` where that is safe. A partial move stays when it fails. */
int ElisaLLVMMakeLoopInvariant(ElisaLoopRef loop, LLVMValueRef value, LLVMValueRef insert_before);
/* Loop::isLoopSimplifyForm. */
int ElisaLLVMLoopIsSimplifyForm(ElisaLoopRef loop);
/* simplifyLoop(L, DT, LI, SE, AC, nullptr, preserve_lcssa): whether it changed the IR. */
int ElisaLLVMSimplifyLoop(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop, int preserve_lcssa);
/* formLCSSA(L, DT, LI, SE): whether it changed the IR. */
int ElisaLLVMFormLCSSA(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop);
/* canPeel(L). */
int ElisaLLVMCanPeelLoop(ElisaLoopRef loop);
/* peelLoop(L, count, peel_last, LI, SE, DT, AC, preserve_lcssa, map). */
void ElisaLLVMPeelLoop(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop, uint32_t count,
                       int peel_last, int preserve_lcssa);

/* SplitBlock(block of `instruction`, instruction, DT, LI, nullptr, name): the new block
 * holds the instruction and everything after it. Updates the dominator tree and loop
 * info. */
LLVMBasicBlockRef ElisaLLVMSplitBlockKeepingLoops(ElisaFunctionAnalysesRef analyses,
                                                  LLVMValueRef instruction, const char *name);
/* cloneLoopWithPreheader(before, loop_dominator, loop, map, suffix, LI, DT, blocks), then
 * remapInstructionsInBlocks(blocks, map): a copy of the loop and its preheader placed
 * before `before`, dominated by `loop_dominator`. Returns the copied loop. */
ElisaLoopRef ElisaLLVMCloneLoopWithPreheader(ElisaFunctionAnalysesRef analyses,
                                             LLVMBasicBlockRef before,
                                             LLVMBasicBlockRef loop_dominator, ElisaLoopRef loop,
                                             ElisaValueMapRef map, const char *suffix);

/* UnrollLoopOptions flags; the options without a flag take the values below. */
enum {
  ElisaUnrollForce = 1,
  ElisaUnrollRuntime = 2,
  ElisaUnrollAllowExpensiveTripCount = 4,
  ElisaUnrollRemainder = 8,
  ElisaUnrollForgetAllSCEV = 16,
  ElisaUnrollRuntimeMultiExit = 32,
  ElisaUnrollAddAdditionalAccumulators = 64,
  ElisaUnrollPreserveLCSSA = 128
};
/* UnrollLoop with UnrollLoopOptions{count, flags..., Heart = nullptr,
 * SCEVExpansionBudget = expansion_budget} and the analyses' LoopInfo, ScalarEvolution,
 * DominatorTree, AssumptionCache, TargetTransformInfo and remark emitter. Returns the
 * LoopUnrollResult: 0 unmodified, 1 partially unrolled, 2 fully unrolled. */
uint32_t ElisaLLVMUnrollLoop(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop, uint32_t count,
                             uint32_t flags, uint32_t expansion_budget);

#ifdef __cplusplus
}
#endif

#endif
