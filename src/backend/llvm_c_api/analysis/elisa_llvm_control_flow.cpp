// Implementation of elisa_llvm_control_flow.h.
#include "elisa_llvm_control_flow.h"
#include "elisa_llvm_function_analyses.h"

#include <llvm/Analysis/CFG.h>
#include <llvm/Analysis/MustExecute.h>
#include <llvm/Support/CBindingWrapping.h>

using namespace llvm;
using namespace elisa_llvm;

extern "C" {

int ElisaLLVMInstructionIsPotentiallyReachable(LLVMValueRef from, LLVMValueRef to) {
  return isPotentiallyReachable(cast<Instruction>(unwrap(from)), cast<Instruction>(unwrap(to)));
}

int ElisaLLVMInstructionIsPotentiallyReachableWithin(ElisaFunctionAnalysesRef analyses, LLVMValueRef from,
                                                     LLVMValueRef to) {
  return isPotentiallyReachable(cast<Instruction>(unwrap(from)), cast<Instruction>(unwrap(to)), nullptr,
                                unwrapAnalyses(analyses)->dominators.get(), nullptr);
}

int ElisaLLVMInstructionIsPotentiallyReachableInLoops(ElisaFunctionAnalysesRef analyses, LLVMValueRef from,
                                                      LLVMValueRef to) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  return isPotentiallyReachable(cast<Instruction>(unwrap(from)), cast<Instruction>(unwrap(to)), nullptr,
                                A->dominators.get(), &A->loops());
}

int ElisaLLVMBlockIsPotentiallyReachableWithin(ElisaFunctionAnalysesRef analyses, LLVMBasicBlockRef from,
                                               LLVMBasicBlockRef to, int use_loops) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  return isPotentiallyReachable(unwrap(from), unwrap(to), nullptr, A->dominators.get(),
                                use_loops ? &A->loops() : nullptr);
}

int ElisaLLVMLoopIsGuaranteedToExecute(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop,
                                       LLVMValueRef instruction) {
  ICFLoopSafetyInfo Safety;
  Safety.computeLoopSafetyInfo(unwrapLoop(loop));
  return Safety.isGuaranteedToExecute(*cast<Instruction>(unwrap(instruction)),
                                      unwrapAnalyses(analyses)->dominators.get(), unwrapLoop(loop));
}

} // extern "C"
