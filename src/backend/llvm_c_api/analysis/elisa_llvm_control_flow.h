/* C API for control-flow questions LLVM's C API does not answer: whether one point can
 * reach another (llvm::isPotentiallyReachable, whose answer depends on the analyses it is
 * given, since its search stops early and answers "reachable" past a block limit), and
 * whether an instruction runs on every iteration of a loop.
 */
#ifndef ELISA_LLVM_CONTROL_FLOW_H
#define ELISA_LLVM_CONTROL_FLOW_H

#include "elisa_llvm_analysis.h"

#ifdef __cplusplus
extern "C" {
#endif

/* isPotentiallyReachable from one instruction to another, without analyses. */
int ElisaLLVMInstructionIsPotentiallyReachable(LLVMValueRef from, LLVMValueRef to);
/* isPotentiallyReachable(from, to, nullptr, DT, nullptr) between instructions, with the
 * analyses' dominator tree. */
int ElisaLLVMInstructionIsPotentiallyReachableWithin(ElisaFunctionAnalysesRef analyses, LLVMValueRef from,
                                                     LLVMValueRef to);
/* isPotentiallyReachable(from, to, nullptr, DT, LI) between instructions, with the
 * analyses' dominator tree and loop info. */
int ElisaLLVMInstructionIsPotentiallyReachableInLoops(ElisaFunctionAnalysesRef analyses, LLVMValueRef from,
                                                      LLVMValueRef to);
/* isPotentiallyReachable(from, to, nullptr, DT, LI) between blocks, with the analyses'
 * dominator tree, and their loop info when USE_LOOPS is set. */
int ElisaLLVMBlockIsPotentiallyReachableWithin(ElisaFunctionAnalysesRef analyses, LLVMBasicBlockRef from,
                                               LLVMBasicBlockRef to, int use_loops);
/* ICFLoopSafetyInfo::isGuaranteedToExecute(instruction, DT, loop), with the safety info
 * computed for the loop as it is now. */
int ElisaLLVMLoopIsGuaranteedToExecute(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop,
                                       LLVMValueRef instruction);

#ifdef __cplusplus
}
#endif

#endif
