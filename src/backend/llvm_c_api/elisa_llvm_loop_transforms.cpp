// Implementation of elisa_llvm_loop_transforms.h over LLVM's loop utilities.
#include "elisa_llvm_loop_transforms.h"
#include "elisa_llvm_function_analyses.h"

#include <llvm/IR/IntrinsicInst.h>
#include <llvm/Transforms/Utils/BasicBlockUtils.h>
#include <llvm/Transforms/Utils/Cloning.h>
#include <llvm/Transforms/Utils/LoopPeel.h>
#include <llvm/Transforms/Utils/LoopSimplify.h>
#include <llvm/Transforms/Utils/LoopUtils.h>
#include <llvm/Transforms/Utils/UnrollLoop.h>
#include <llvm/Transforms/Utils/ValueMapper.h>

using namespace llvm;
using namespace elisa_llvm;

extern "C" {

void ElisaLLVMForgetLoop(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  if (A->evolution) A->evolution->forgetLoop(unwrapLoop(loop));
}

void ElisaLLVMRegisterAssumption(ElisaFunctionAnalysesRef analyses, LLVMValueRef assume) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  if (A->assumptions) A->assumptions->registerAssumption(cast<AssumeInst>(unwrap(assume)));
}

uint32_t ElisaLLVMTopLevelLoopCount(ElisaFunctionAnalysesRef analyses) {
  LoopInfo &LI = unwrapAnalyses(analyses)->loops();
  return static_cast<uint32_t>(LI.end() - LI.begin());
}

ElisaLoopRef ElisaLLVMTopLevelLoopAt(ElisaFunctionAnalysesRef analyses, uint32_t index) {
  LoopInfo &LI = unwrapAnalyses(analyses)->loops();
  return index < static_cast<uint32_t>(LI.end() - LI.begin()) ? wrapLoop(LI.begin()[index])
                                                               : nullptr;
}

ElisaLoopRef ElisaLLVMLoopSubLoopAt(ElisaLoopRef loop, uint32_t index) {
  const auto &SubLoops = unwrapLoop(loop)->getSubLoops();
  return index < SubLoops.size() ? wrapLoop(SubLoops[index]) : nullptr;
}

int ElisaLLVMLoopIsSimplifyForm(ElisaLoopRef loop) {
  return unwrapLoop(loop)->isLoopSimplifyForm();
}

int ElisaLLVMSimplifyLoop(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop,
                          int preserve_lcssa) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  return simplifyLoop(unwrapLoop(loop), A->dominators.get(), &A->loops(), &A->scalarEvolution(),
                      &A->assumptionCache(), nullptr, preserve_lcssa != 0);
}

int ElisaLLVMFormLCSSA(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  return formLCSSA(*unwrapLoop(loop), *A->dominators, &A->loops(), &A->scalarEvolution());
}

int ElisaLLVMCanPeelLoop(ElisaLoopRef loop) { return canPeel(unwrapLoop(loop)); }

void ElisaLLVMPeelLoop(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop, uint32_t count,
                       int peel_last, int preserve_lcssa) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  ValueToValueMapTy Map;
  peelLoop(unwrapLoop(loop), count, peel_last != 0, &A->loops(), &A->scalarEvolution(),
           *A->dominators, &A->assumptionCache(), preserve_lcssa != 0, Map);
}

LLVMBasicBlockRef ElisaLLVMSplitBlockKeepingLoops(ElisaFunctionAnalysesRef analyses,
                                                  LLVMValueRef instruction, const char *name) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  Instruction *At = cast<Instruction>(unwrap(instruction));
  return wrap(SplitBlock(At->getParent(), At, A->dominators.get(), &A->loops(), nullptr, name));
}

ElisaLoopRef ElisaLLVMCloneLoopWithPreheader(ElisaFunctionAnalysesRef analyses,
                                             LLVMBasicBlockRef before,
                                             LLVMBasicBlockRef loop_dominator, ElisaLoopRef loop,
                                             ElisaValueMapRef map, const char *suffix) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  ValueToValueMapTy &Map = *reinterpret_cast<ValueToValueMapTy *>(map);
  SmallVector<BasicBlock *, 40> Blocks;
  Loop *Copy = cloneLoopWithPreheader(unwrap(before), unwrap(loop_dominator), unwrapLoop(loop),
                                      Map, suffix, &A->loops(), A->dominators.get(), Blocks);
  remapInstructionsInBlocks(Blocks, Map);
  return wrapLoop(Copy);
}

uint32_t ElisaLLVMUnrollLoop(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop, uint32_t count,
                             uint32_t flags, uint32_t expansion_budget) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  UnrollLoopOptions Options{count,
                            (flags & ElisaUnrollForce) != 0,
                            (flags & ElisaUnrollRuntime) != 0,
                            (flags & ElisaUnrollAllowExpensiveTripCount) != 0,
                            (flags & ElisaUnrollRemainder) != 0,
                            (flags & ElisaUnrollForgetAllSCEV) != 0,
                            nullptr,
                            expansion_budget,
                            (flags & ElisaUnrollRuntimeMultiExit) != 0,
                            (flags & ElisaUnrollAddAdditionalAccumulators) != 0};
  LoopUnrollResult Result =
      UnrollLoop(unwrapLoop(loop), Options, &A->loops(), &A->scalarEvolution(), A->dominators.get(),
                 &A->assumptionCache(), &A->targetTransformInfo(), &A->remarkEmitter(),
                 (flags & ElisaUnrollPreserveLCSSA) != 0);
  return static_cast<uint32_t>(Result);
}

} // extern "C"
