// The C++ object behind ElisaFunctionAnalysesRef, shared by the shim files that query
// (elisa_llvm_analysis.cpp) or transform (elisa_llvm_loop_transforms.cpp) a function
// through it. Not part of the C interface.
#ifndef ELISA_LLVM_FUNCTION_ANALYSES_H
#define ELISA_LLVM_FUNCTION_ANALYSES_H

#include "elisa_llvm_analysis.h"

#include <llvm/Analysis/AssumptionCache.h>
#include <llvm/Analysis/LazyValueInfo.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/Analysis/OptimizationRemarkEmitter.h>
#include <llvm/Analysis/ScalarEvolution.h>
#include <llvm/Analysis/TargetLibraryInfo.h>
#include <llvm/Analysis/TargetTransformInfo.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/Function.h>
#include <llvm/IR/Module.h>

#include <memory>
#include <vector>

namespace elisa_llvm {

// The analyses of one function, built as a function analysis manager without a target
// machine builds them. The dominator tree is built at once; the rest on first use, so a
// pass that only asks about dominance pays for nothing else. Invalidation drops them all.
struct FunctionAnalyses {
  explicit FunctionAnalyses(llvm::Function &F) : function(F) { build(); }

  void build() {
    remarks.reset();
    transformInfo.reset();
    lazyValues.reset();
    evolution.reset();
    assumptions.reset();
    libraryInfo.reset();
    libraryInfoImpl.reset();
    loopInfo.reset();
    preorder.clear();
    dominators = std::make_unique<llvm::DominatorTree>(function);
  }

  llvm::LoopInfo &loops() {
    if (!loopInfo) {
      loopInfo = std::make_unique<llvm::LoopInfo>(*dominators);
      for (llvm::Loop *L : loopInfo->getLoopsInPreorder()) preorder.push_back(L);
    }
    return *loopInfo;
  }

  llvm::AssumptionCache &assumptionCache() {
    if (!assumptions) assumptions = std::make_unique<llvm::AssumptionCache>(function);
    return *assumptions;
  }

  // As TargetLibraryAnalysis builds it: the module's triple and the function's
  // `no-builtin` attributes.
  llvm::TargetLibraryInfo &targetLibraryInfo() {
    if (!libraryInfo) {
      libraryInfoImpl = std::make_unique<llvm::TargetLibraryInfoImpl>(
          function.getParent()->getTargetTriple());
      libraryInfo = std::make_unique<llvm::TargetLibraryInfo>(*libraryInfoImpl, &function);
    }
    return *libraryInfo;
  }

  llvm::ScalarEvolution &scalarEvolution() {
    if (!evolution)
      evolution = std::make_unique<llvm::ScalarEvolution>(function, targetLibraryInfo(),
                                                          assumptionCache(), *dominators, loops());
    return *evolution;
  }

  // As LazyValueAnalysis builds it: the function and its assumption cache.
  llvm::LazyValueInfo &lazyValueInfo() {
    if (!lazyValues)
      lazyValues = std::make_unique<llvm::LazyValueInfo>(&function, &assumptionCache());
    return *lazyValues;
  }

  // TargetIRAnalysis without a target machine: the data layout's default costs.
  llvm::TargetTransformInfo &targetTransformInfo() {
    if (!transformInfo)
      transformInfo = std::make_unique<llvm::TargetTransformInfo>(function.getDataLayout());
    return *transformInfo;
  }

  llvm::OptimizationRemarkEmitter &remarkEmitter() {
    if (!remarks) remarks = std::make_unique<llvm::OptimizationRemarkEmitter>(&function);
    return *remarks;
  }

  llvm::Function &function;
  std::unique_ptr<llvm::DominatorTree> dominators;
  std::unique_ptr<llvm::LoopInfo> loopInfo;
  std::unique_ptr<llvm::TargetLibraryInfoImpl> libraryInfoImpl;
  std::unique_ptr<llvm::TargetLibraryInfo> libraryInfo;
  std::unique_ptr<llvm::AssumptionCache> assumptions;
  std::unique_ptr<llvm::ScalarEvolution> evolution;
  std::unique_ptr<llvm::LazyValueInfo> lazyValues;
  std::unique_ptr<llvm::TargetTransformInfo> transformInfo;
  std::unique_ptr<llvm::OptimizationRemarkEmitter> remarks;
  std::vector<llvm::Loop *> preorder;
};

inline FunctionAnalyses *unwrapAnalyses(ElisaFunctionAnalysesRef analyses) {
  return reinterpret_cast<FunctionAnalyses *>(analyses);
}

inline llvm::Loop *unwrapLoop(ElisaLoopRef loop) { return reinterpret_cast<llvm::Loop *>(loop); }

inline ElisaLoopRef wrapLoop(llvm::Loop *loop) { return reinterpret_cast<ElisaLoopRef>(loop); }

} // namespace elisa_llvm

#endif
