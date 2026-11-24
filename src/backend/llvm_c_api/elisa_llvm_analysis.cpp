// Implementation of elisa_llvm_analysis.h over LLVM's C++ analyses.
#include "elisa_llvm_analysis.h"

#include <llvm/Analysis/AssumptionCache.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/Analysis/ScalarEvolution.h>
#include <llvm/Analysis/ScalarEvolutionExpressions.h>
#include <llvm/Analysis/TargetLibraryInfo.h>
#include <llvm/Analysis/ValueTracking.h>
#include <llvm/IR/Constants.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/InstrTypes.h>
#include <llvm/IR/Function.h>
#include <llvm/IR/Metadata.h>
#include <llvm/IR/Module.h>
#include <llvm/IR/PatternMatch.h>
#include <llvm/TargetParser/Triple.h>

#include <memory>
#include <vector>

using namespace llvm;

namespace {
// The analyses of one function. The dominator tree is built at once; loop
// info and scalar evolution on first use, so a pass that only asks about
// dominance pays for nothing else. Invalidation drops them all.
struct FunctionAnalyses {
  explicit FunctionAnalyses(Function &F) : function(F) { build(); }

  void build() {
    evolution.reset();
    assumptions.reset();
    libraryInfo.reset();
    libraryInfoImpl.reset();
    loopInfo.reset();
    preorder.clear();
    dominators = std::make_unique<DominatorTree>(function);
  }

  LoopInfo &loops() {
    if (!loopInfo) {
      loopInfo = std::make_unique<LoopInfo>(*dominators);
      for (Loop *L : loopInfo->getLoopsInPreorder()) preorder.push_back(L);
    }
    return *loopInfo;
  }

  ScalarEvolution &scalarEvolution() {
    if (!evolution) {
      libraryInfoImpl = std::make_unique<TargetLibraryInfoImpl>(function.getParent()->getTargetTriple());
      libraryInfo = std::make_unique<TargetLibraryInfo>(*libraryInfoImpl);
      assumptions = std::make_unique<AssumptionCache>(function);
      evolution = std::make_unique<ScalarEvolution>(function, *libraryInfo, *assumptions,
                                                    *dominators, loops());
    }
    return *evolution;
  }

  Function &function;
  std::unique_ptr<DominatorTree> dominators;
  std::unique_ptr<LoopInfo> loopInfo;
  std::unique_ptr<TargetLibraryInfoImpl> libraryInfoImpl;
  std::unique_ptr<TargetLibraryInfo> libraryInfo;
  std::unique_ptr<AssumptionCache> assumptions;
  std::unique_ptr<ScalarEvolution> evolution;
  std::vector<Loop *> preorder;
};

FunctionAnalyses *unwrapAnalyses(ElisaFunctionAnalysesRef analyses) {
  return reinterpret_cast<FunctionAnalyses *>(analyses);
}

Loop *unwrapLoop(ElisaLoopRef loop) { return reinterpret_cast<Loop *>(loop); }

ElisaLoopRef wrapLoop(Loop *loop) { return reinterpret_cast<ElisaLoopRef>(loop); }
} // namespace

extern "C" {

ElisaFunctionAnalysesRef ElisaLLVMCreateFunctionAnalyses(LLVMValueRef function) {
  auto *F = dyn_cast_or_null<Function>(unwrap(function));
  if (!F || F->isDeclaration()) return nullptr;
  return reinterpret_cast<ElisaFunctionAnalysesRef>(new FunctionAnalyses(*F));
}

void ElisaLLVMDisposeFunctionAnalyses(ElisaFunctionAnalysesRef analyses) {
  delete unwrapAnalyses(analyses);
}

void ElisaLLVMInvalidateFunctionAnalyses(ElisaFunctionAnalysesRef analyses) {
  unwrapAnalyses(analyses)->build();
}

int ElisaLLVMBlockDominates(ElisaFunctionAnalysesRef analyses, LLVMBasicBlockRef dominator,
                            LLVMBasicBlockRef dominated) {
  return unwrapAnalyses(analyses)->dominators->dominates(unwrap(dominator), unwrap(dominated));
}

int ElisaLLVMInstructionDominates(ElisaFunctionAnalysesRef analyses, LLVMValueRef definition,
                                  LLVMValueRef user) {
  auto *Use = dyn_cast<Instruction>(unwrap(user));
  return Use && unwrapAnalyses(analyses)->dominators->dominates(unwrap(definition), Use);
}

LLVMBasicBlockRef ElisaLLVMImmediateDominator(ElisaFunctionAnalysesRef analyses,
                                              LLVMBasicBlockRef block) {
  DomTreeNode *Node = unwrapAnalyses(analyses)->dominators->getNode(unwrap(block));
  return Node && Node->getIDom() ? wrap(Node->getIDom()->getBlock()) : nullptr;
}

uint32_t ElisaLLVMLoopCount(ElisaFunctionAnalysesRef analyses) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  A->loops();
  return A->preorder.size();
}

ElisaLoopRef ElisaLLVMLoopAt(ElisaFunctionAnalysesRef analyses, uint32_t index) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  A->loops();
  return index < A->preorder.size() ? wrapLoop(A->preorder[index]) : nullptr;
}

ElisaLoopRef ElisaLLVMLoopForBlock(ElisaFunctionAnalysesRef analyses, LLVMBasicBlockRef block) {
  return wrapLoop(unwrapAnalyses(analyses)->loops().getLoopFor(unwrap(block)));
}

ElisaLoopRef ElisaLLVMLoopParent(ElisaLoopRef loop) {
  return wrapLoop(unwrapLoop(loop)->getParentLoop());
}

uint32_t ElisaLLVMLoopDepth(ElisaLoopRef loop) { return unwrapLoop(loop)->getLoopDepth(); }

uint32_t ElisaLLVMLoopSubLoopCount(ElisaLoopRef loop) {
  return unwrapLoop(loop)->getSubLoops().size();
}

uint32_t ElisaLLVMLoopBlockCount(ElisaLoopRef loop) { return unwrapLoop(loop)->getNumBlocks(); }

LLVMBasicBlockRef ElisaLLVMLoopBlockAt(ElisaLoopRef loop, uint32_t index) {
  auto Blocks = unwrapLoop(loop)->getBlocks();
  return index < Blocks.size() ? wrap(Blocks[index]) : nullptr;
}

int ElisaLLVMLoopContainsBlock(ElisaLoopRef loop, LLVMBasicBlockRef block) {
  return unwrapLoop(loop)->contains(unwrap(block));
}

LLVMBasicBlockRef ElisaLLVMLoopHeader(ElisaLoopRef loop) {
  return wrap(unwrapLoop(loop)->getHeader());
}

LLVMBasicBlockRef ElisaLLVMLoopLatch(ElisaLoopRef loop) {
  return wrap(unwrapLoop(loop)->getLoopLatch());
}

LLVMBasicBlockRef ElisaLLVMLoopPreheader(ElisaLoopRef loop) {
  return wrap(unwrapLoop(loop)->getLoopPreheader());
}

LLVMBasicBlockRef ElisaLLVMLoopPredecessor(ElisaLoopRef loop) {
  return wrap(unwrapLoop(loop)->getLoopPredecessor());
}

int ElisaLLVMLoopIsInvariant(ElisaLoopRef loop, LLVMValueRef value) {
  return unwrapLoop(loop)->isLoopInvariant(unwrap(value));
}

LLVMMetadataRef ElisaLLVMLoopGetLoopID(ElisaLoopRef loop) {
  return wrap(unwrapLoop(loop)->getLoopID());
}

void ElisaLLVMLoopSetLoopID(ElisaLoopRef loop, LLVMMetadataRef loop_id) {
  unwrapLoop(loop)->setLoopID(cast<MDNode>(unwrap(loop_id)));
}

LLVMMetadataRef ElisaLLVMCreateLoopID(LLVMContextRef context, LLVMMetadataRef *properties,
                                      uint32_t count) {
  SmallVector<Metadata *, 4> Entries{nullptr};
  for (uint32_t I = 0; I < count; ++I) Entries.push_back(unwrap(properties[I]));
  MDNode *ID = MDNode::getDistinct(*unwrap(context), Entries);
  ID->replaceOperandWith(0, ID);
  return wrap(ID);
}

int ElisaLLVMModuleTargetIsAArch64(LLVMModuleRef module) {
  return unwrap(module)->getTargetTriple().isAArch64();
}

int ElisaLLVMModuleTargetArchIsAArch64(LLVMModuleRef module) {
  return unwrap(module)->getTargetTriple().getArch() == Triple::aarch64;
}

int ElisaLLVMModuleTargetIsDarwin(LLVMModuleRef module) {
  return unwrap(module)->getTargetTriple().isOSDarwin();
}

int ElisaLLVMBlockHasAddressTaken(LLVMBasicBlockRef block) {
  return unwrap(block)->hasAddressTaken();
}

int ElisaLLVMHasMetadataOtherThanDebugLoc(LLVMValueRef instruction) {
  return cast<Instruction>(unwrap(instruction))->hasMetadataOtherThanDebugLoc();
}

int ElisaLLVMIsConstantOne(LLVMValueRef value) {
  return PatternMatch::match(unwrap(value), PatternMatch::m_One());
}

int ElisaLLVMIsConstantZero(LLVMValueRef value) {
  return PatternMatch::match(unwrap(value), PatternMatch::m_Zero());
}

int ElisaLLVMMayHaveSideEffects(LLVMValueRef instruction) {
  return cast<Instruction>(unwrap(instruction))->mayHaveSideEffects();
}

int ElisaLLVMCallDoesNotAccessMemory(LLVMValueRef call) {
  return cast<CallBase>(unwrap(call))->doesNotAccessMemory();
}

int ElisaLLVMFunctionHasEntryCount(LLVMValueRef function) {
  return cast<Function>(unwrap(function))->getEntryCount().has_value();
}

int ElisaLLVMConstantIntIsNegative(LLVMValueRef constant) {
  return cast<ConstantInt>(unwrap(constant))->isNegative();
}

int ElisaLLVMConstantFloatIsNegativeFiniteNonzero(LLVMValueRef constant) {
  const APFloat &Value = cast<ConstantFP>(unwrap(constant))->getValueAPF();
  return Value.isNegative() && !Value.isZero() && !Value.isNaN() && !Value.isInfinity();
}

int ElisaLLVMIsGuaranteedNotToBeUndefOrPoison(LLVMValueRef value) {
  return isGuaranteedNotToBeUndefOrPoison(unwrap(value));
}

int ElisaLLVMConstantMaxBackedgeTakenCount(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop,
                                           uint64_t *count) {
  auto *Max = dyn_cast<SCEVConstant>(
      unwrapAnalyses(analyses)->scalarEvolution().getConstantMaxBackedgeTakenCount(unwrapLoop(loop)));
  if (!Max || Max->getAPInt().getActiveBits() > 64) return 0;
  *count = Max->getAPInt().getZExtValue();
  return 1;
}

} // extern "C"
