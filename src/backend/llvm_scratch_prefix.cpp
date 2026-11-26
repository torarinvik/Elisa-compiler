//go:build cgo
// The preparing phase of the scratch-prefix sequence: covered and counted array
// initializers. The rest of the sequence, including the scratch fills this phase
// prepares for, lives in Elisa (llvm_passes/scratch_prefix/).
#include <llvm/ADT/SmallPtrSet.h>
#include <llvm/ADT/SmallVector.h>
#include <llvm/Analysis/CFG.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/IR/Dominators.h>
#include <llvm/Analysis/ValueTracking.h>
#include <llvm/IR/Constants.h>
#include <llvm/IR/DerivedTypes.h>
#include <llvm/IR/InstIterator.h>
#include <llvm/IR/Instructions.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/IR/Metadata.h>
#include <llvm/IR/ValueHandle.h>
#include <llvm/Config/llvm-config.h>
#include <llvm/Analysis/AssumptionCache.h>
#include <llvm/Analysis/OptimizationRemarkEmitter.h>
#include <llvm/Analysis/TargetLibraryInfo.h>
#include <llvm/Passes/PassBuilder.h>
#include <llvm/Support/CBindingWrapping.h>
#include <llvm/Transforms/Utils/SimplifyLibCalls.h>
#include <llvm/IR/Module.h>
#include <llvm/IR/CFG.h>
#include <llvm/ADT/PostOrderIterator.h>
#include <algorithm>
#include <cstdint>
#include <deque>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>
using namespace llvm;

#if LLVM_VERSION_MAJOR >= 23
#include "llvm_array_coverage.h"
#include "llvm_counted_prefix.h"

// The scratch-prefix sequence runs before O3 from Elisa
// (llvm_passes/scratch_prefix/scratch_prefix_sequence.elisa): this phase first, then the
// indexed-prefix, validated-read, bisection-check, view-fill and scratch-fill passes.
namespace ElisaScratchPrefix {
// The analysis managers one phase builds over the module.
struct PhaseAnalyses {
  PassBuilder PB;
  LoopAnalysisManager LAM;
  FunctionAnalysisManager FAM;
  CGSCCAnalysisManager CGAM;
  ModuleAnalysisManager MAM;
  PhaseAnalyses() {
    PB.registerModuleAnalyses(MAM);
    PB.registerCGSCCAnalyses(CGAM);
    PB.registerFunctionAnalyses(FAM);
    PB.registerLoopAnalyses(LAM);
    PB.crossRegisterProxies(LAM, FAM, CGAM, MAM);
  }
};
} // namespace ElisaScratchPrefix

// Covered and counted array initializers.
extern "C" unsigned elisacorePrepareScratchPrefixArrays(LLVMModuleRef Ref) {
  Module &M = *unwrap(Ref);
  ElisaScratchPrefix::PhaseAnalyses Phase;
  unsigned Removed = prepareCoveredArrayInitializers(M, Phase.FAM, Phase.PB);
  Removed += removeCountedPrefixInitializers(M, Phase.FAM, Phase.PB);
  return Removed;
}

extern "C" unsigned elisacoreScratchPrefixSupported(void) { return 1; }
#else
extern "C" unsigned elisacorePrepareScratchPrefixArrays(LLVMModuleRef) { return 0; }
extern "C" unsigned elisacoreScratchPrefixSupported(void) { return 0; }
#endif
