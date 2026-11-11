//go:build cgo
#include <llvm/Config/llvm-config.h>
#include <llvm-c/Core.h>
#include <llvm-c/TargetMachine.h>
#if LLVM_VERSION_MAJOR == 23
#include <llvm/ADT/APInt.h>
#include <llvm/ADT/DenseMap.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/Instructions.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/IR/Intrinsics.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/Transforms/Utils/Mem2Reg.h>
#include <llvm/IR/Module.h>
#include <llvm/Passes/PassBuilder.h>
#include <llvm/Analysis/AssumptionCache.h>
#include <llvm/Analysis/CaptureTracking.h>
#include <llvm/Analysis/ValueTracking.h>
#include <llvm/Analysis/CFG.h>
#include <llvm/IR/ConstantRange.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/Analysis/OptimizationRemarkEmitter.h>
#include <llvm/Analysis/TargetTransformInfo.h>
#include <llvm/Analysis/ScalarEvolution.h>
#include <llvm/Support/CBindingWrapping.h>
#include <llvm/MC/MCSubtargetInfo.h>
#include <llvm/MC/TargetRegistry.h>
#include <llvm/Target/TargetMachine.h>
#include <llvm/ADT/SmallVector.h>
#include <llvm/Transforms/Utils/Cloning.h>
#include <llvm/Transforms/Utils/LoopPeel.h>
#include <llvm/Transforms/Utils/LoopSimplify.h>
#include <llvm/Transforms/Utils/LoopUtils.h>
#include <llvm/Transforms/Utils/UnrollLoop.h>
#include <llvm/Transforms/Utils/Local.h>

using namespace llvm;
#include "llvm_validation_loop_passes.h"
#include "llvm_validation_bounded_division.h"

#else
extern "C" unsigned elisacoreElideBoundedDivisionSums(LLVMModuleRef) {
  return 0;
}
extern "C" unsigned elisacorePredicatePrivateBitUpdates(LLVMModuleRef) { return 0; }
extern "C" unsigned elisacoreSinkPrivateInitializations(LLVMModuleRef) { return 0; }
extern "C" unsigned elisacoreInlineSmallRecursion(LLVMModuleRef) { return 0; }
extern "C" unsigned elisacoreUnrollNestedScans(LLVMModuleRef) { return 0; }
extern "C" unsigned elisacorePeelSmallValidationLoops(LLVMModuleRef) { return 0; }
extern "C" unsigned elisacoreCsscAbsoluteRangeChecks(LLVMModuleRef, LLVMTargetMachineRef) { return 0; }
#endif

// Keep Apple ARM layout policy identical to Stage0's O3 emitter.
#include <llvm-c/Support.h>
#include <llvm-c/Transforms/PassBuilder.h>
#include <llvm-c/Error.h>
#include "llvm_selective_scheduler.cpp"
// Install before the first optimization, independent of optimization-level
// ordering. Linux retains its faster Stage1 bounded-loop policy from LLVM.
extern "C" void elisacoreConfigureBoundedUnroll() {
#if defined(__APPLE__) && defined(__aarch64__)
  static bool installed = false;
  if (installed) return;
  installed = true;
  const char *args[] = {"elisac", "-unroll-max-upperbound=4"};
  LLVMParseCommandLineOptions(2, args, nullptr);
#endif
}
extern "C" void elisacoreConfigureAppleCodeLayout() {
#if defined(__APPLE__) && defined(__aarch64__)
  static bool installed = false;
  if (installed) return;
  installed = true;
  const char *args[] = {"elisac", "-enable-ext-tsp-block-placement=true",
                        "-aarch64-enable-early-ifcvt=false"};
  LLVMParseCommandLineOptions(3, args, nullptr);
#elif defined(__aarch64__)
  static bool installed = false;
  if (installed) return;
  installed = true;
#if LLVM_VERSION_MAJOR == 23 && defined(__linux__)
  // Respect an explicitly selected scheduler; otherwise use a selector that
  // delegates unmarked functions to the target's unchanged default.
  auto &registered = llvm::cl::getRegisteredOptions();
  auto scheduler = registered.find("misched");
  if (scheduler != registered.end() && scheduler->second->getNumOccurrences() == 0) {
    const char *args[] = {"elisac", "-aarch64-enable-early-ifcvt=false",
                          "-misched=elisa-ordered-selective"};
    LLVMParseCommandLineOptions(3, args, nullptr);
    return;
  }
#endif
  const char *args[] = {"elisac", "-aarch64-enable-early-ifcvt=false"};
  LLVMParseCommandLineOptions(2, args, nullptr);
#endif
}
#include "llvm_checked_mul.cpp"
extern "C" unsigned elisacoreBoundedLoopUnswitch(LLVMModuleRef);
#include "llvm_shared_reciprocal.cpp"
#include "llvm_bounded_factorial.cpp"
extern "C" unsigned elisacoreElideArrayRoundTrips(LLVMModuleRef);
extern "C" unsigned elisacoreOptimizeSqrtNonNaN(LLVMModuleRef, LLVMTargetMachineRef);
extern "C" unsigned elisacoreOptimizeBoundedSums(LLVMModuleRef, LLVMTargetMachineRef);
extern "C" unsigned elisacoreOptimizeIndexBounds(LLVMModuleRef, LLVMTargetMachineRef);
#include "llvm_validation_layout.cpp"
#include "llvm_guarded_increment.cpp"
#include "llvm_guarded_counter.cpp"
#include "llvm_nonnegative_remainder.cpp"
#include "llvm_ordered_vector.cpp"
#include "llvm_special_epilogue.cpp"
#include "llvm_even_range.cpp"
#if LLVM_VERSION_MAJOR >= 23
#include "llvm_ring_index_bounds.cpp"
#include "llvm_guarded_counter_bounds.cpp"
#include "llvm_decimal_digit_count.cpp"
#include "llvm_halving_runs.cpp"
#endif

static bool shouldRevisitNestedVectorLoops(Module &M) {
  if (M.getNamedMetadata("llvm.dbg.cu") || !M.getTargetTriple().isAArch64())
    return false;
  unsigned Functions = 0, Instructions = 0;
  for (Function &F : M) {
    if (F.isDeclaration()) continue;
    if (++Functions > 4 || (Instructions += F.getInstructionCount()) > 2000 ||
        F.hasOptNone() || F.hasOptSize() || F.hasMinSize() ||
        F.hasFnAttribute(Attribute::SanitizeAddress) ||
        F.hasFnAttribute(Attribute::SanitizeMemory) ||
        F.hasFnAttribute(Attribute::SanitizeThread) ||
        F.hasFnAttribute(Attribute::SanitizeHWAddress)) return false;
  }
  for (Function &F : M) {
    if (F.isDeclaration()) continue;
    DominatorTree DT(F); LoopInfo LI(DT);
    for (Loop *L : LI.getLoopsInPreorder()) {
      if (!L->getParentLoop()) continue;
      for (BasicBlock *B : L->blocks())
        for (Instruction &I : *B)
          if (auto *Load = dyn_cast<LoadInst>(&I))
            if (Load->getType()->isVectorTy()) return true;
    }
  }
  return false;
}

extern "C" unsigned elisacoreLateScalarCleanup(LLVMModuleRef module,
                                              LLVMTargetMachineRef target) {
  elisacoreElideArrayRoundTrips(module);
  unsigned scans = elisacorePredicatePrivateBitUpdates(module);
  scans += elisacoreInlineSmallRecursion(module);
  scans += elisacoreUnrollNestedScans(module);
#if defined(__aarch64__) && !defined(__APPLE__)
  if (scans) {
    auto options = LLVMCreatePassBuilderOptions();
    auto error = LLVMRunPasses(module,
      "function(early-cse,instcombine<max-iterations=8;no-verify-fixpoint>,loop-simplify,lcssa,loop(indvars),gvn,instcombine<max-iterations=8;no-verify-fixpoint>,simplifycfg)", target, options);
    LLVMDisposePassBuilderOptions(options);
    if (error) { LLVMConsumeError(error); return 2; }
  }
#endif
#if defined(__APPLE__) && defined(__aarch64__)
  auto options = LLVMCreatePassBuilderOptions();
  auto error = LLVMRunPasses(module,
      "function(early-cse,instcombine<max-iterations=8;no-verify-fixpoint>,loop-simplify,lcssa,loop(indvars),gvn,instcombine<max-iterations=8;no-verify-fixpoint>,simplifycfg)",
      target, options);
  LLVMDisposePassBuilderOptions(options);
  if (error) {
    LLVMConsumeError(error);
    return 2;
  }
#endif
  unsigned sharedReciprocals = elisacoreShareReciprocals(module);
  unsigned status = elisacoreFastCheckedMul(module, target);
  if (sharedReciprocals && status == 0) status = 1;
  if (status == 2) return 2;
  unsigned boundedDivisionLoops = elisacoreUnrollBoundedDivisionLoops(module);
  if (boundedDivisionLoops) {
    auto options = LLVMCreatePassBuilderOptions();
    auto error = LLVMRunPasses(module, "function(correlated-propagation,instcombine<no-verify-fixpoint>,simplifycfg)", target, options);
    LLVMDisposePassBuilderOptions(options);
    if (error) { LLVMConsumeError(error); return 2; }
    status = 1;
  }
  if (elisacoreBoundedFactorials(module)) {
    auto options = LLVMCreatePassBuilderOptions();
    auto error = LLVMRunPasses(module, "function(correlated-propagation,instcombine<no-verify-fixpoint>,simplifycfg,loop-simplify,lcssa,indvars,loop-vectorize,instcombine<no-verify-fixpoint>,simplifycfg)", target, options);
    LLVMDisposePassBuilderOptions(options);
    if (error) { LLVMConsumeError(error); return 2; }
    status = 1;
  }
  if (elisacoreUnrollLaggedRecurrences(module)) {
    auto options = LLVMCreatePassBuilderOptions();
    auto error = LLVMRunPasses(module, "function(instcombine<no-verify-fixpoint>,simplifycfg)", target, options);
    LLVMDisposePassBuilderOptions(options);
    if (error) { LLVMConsumeError(error); return 2; }
    status = 1;
  }
  if (elisacoreBoundedProducts(module)) {
    // Revisit reductions made vectorizable by the product proof. The first
    // O3 vectorizer saw their checked-arithmetic side exits. The Darwin/ARM64
    // ordering is qualified; retain Linux's measured scalar ordering.
    const auto &triple = unwrap(module)->getTargetTriple();
    const char *cleanup = triple.isOSDarwin() && triple.getArch() == Triple::aarch64
        ? "function(correlated-propagation,instcombine<no-verify-fixpoint>,simplifycfg,"
          "loop-simplify,lcssa,loop-vectorize,instcombine<no-verify-fixpoint>,simplifycfg)"
        : "function(correlated-propagation,instcombine<no-verify-fixpoint>,simplifycfg)";
    auto options = LLVMCreatePassBuilderOptions();
    auto error = LLVMRunPasses(module, cleanup, target, options);
    LLVMDisposePassBuilderOptions(options);
    if (error) { LLVMConsumeError(error); return 2; }
    status = 1;
  }
#if defined(__APPLE__) && defined(__aarch64__)
  // The linked macOS benchmark qualifies this late versioning. Keep Linux's
  // existing output until the matching-PIE comparison demonstrates a gain.
  if (elisacoreBoundedLoopUnswitch(module)) status = 1;
#endif
  if (elisacoreSinkPrivateInitializations(module)) status = 1;
  unsigned sqrtStatus = elisacoreOptimizeSqrtNonNaN(module, target);
  if (sqrtStatus == 2) return 2;
  if (sqrtStatus) status = 1;
  unsigned sumStatus = elisacoreOptimizeBoundedSums(module, target);
  if (sumStatus == 2) return 2;
  if (sumStatus) status = 1;
#if defined(__APPLE__) && defined(__aarch64__)
  // This shortens the self-hosted Darwin entry sequence. On Linux the
  // bounded-sum output is faster without another layout-changing cleanup.
  if (unwrap(module)->getTargetTriple().isOSDarwin() &&
      unwrap(module)->getTargetTriple().getArch() == Triple::aarch64) {
    unsigned indexStatus = elisacoreOptimizeIndexBounds(module, target);
    if (indexStatus == 2) return 2;
    if (indexStatus) status = 1;
  }
#endif
  // Late scalar rewrites can expose outer-loop unrolling around an already
  // vectorized inner loop. Keep this second full O3 pipeline bounded to small
  // modules, so normal self-host builds do not pay its compile-time cost.
  if (shouldRevisitNestedVectorLoops(*unwrap(module))) {
    auto opts = LLVMCreatePassBuilderOptions();
    auto err = LLVMRunPasses(module, "default<O3>", target, opts);
    LLVMDisposePassBuilderOptions(opts);
    if (err) { LLVMConsumeError(err); return 2; }
    status = 1;
  }
  unsigned guarded = foldGuardedIncrements(*unwrap(module));
  SmallVector<Function *, 8> boundedCounterFunctions;
  guarded += foldGuardedCounters(*unwrap(module), boundedCounterFunctions);
  guarded += foldNonnegativeRemainders(*unwrap(module));
  if (guarded) {
    auto opts = LLVMCreatePassBuilderOptions();
    auto err = LLVMRunPasses(module,
      "function(instcombine<no-verify-fixpoint>,simplifycfg,loop-simplify,lcssa,loop(indvars),instcombine<no-verify-fixpoint>,simplifycfg)", target, opts);
    LLVMDisposePassBuilderOptions(opts);
    if (err) { LLVMConsumeError(err); return 2; }
    status = 1;
  }
  // Removing checked-counter exits can expose reductions to the vectorizer.
  for (Function *F : boundedCounterFunctions) {
    auto opts = LLVMCreatePassBuilderOptions();
    auto err = LLVMRunPassesOnFunction(wrap(F),
        "loop-simplify,lcssa,loop-vectorize,instcombine<no-verify-fixpoint>,simplifycfg",
        target, opts);
    LLVMDisposePassBuilderOptions(opts);
    if (err) { LLVMConsumeError(err); return 2; }
  }
  unsigned orderedVector = elisacoreOptimizeOrderedConversions(module, target);
  if (orderedVector == 2) return 2;
  if (orderedVector) status = 1;
  unsigned finalSimplifications = elisacoreSpecializeValidationEpilogues(module);
  finalSimplifications += elisacoreFoldShiftParityLoops(*unwrap(module));
  finalSimplifications += elisacoreFoldShiftBitReverseLoops(*unwrap(module));
  finalSimplifications += elisacoreFoldPowerPosition(*unwrap(module));
#if LLVM_VERSION_MAJOR >= 23
  finalSimplifications += elisacoreFoldRingIndexBounds(*unwrap(module));
  finalSimplifications += elisacoreFoldGuardedCounterBounds(*unwrap(module));
  finalSimplifications += elisacoreFoldDecimalDigitCounts(*unwrap(module));
  finalSimplifications += elisacoreFoldHalvingRuns(*unwrap(module));
  finalSimplifications += elisacoreFoldRangeAndLoops(*unwrap(module));
  finalSimplifications += elisacoreFoldScalarLoopIdioms(*unwrap(module));
  finalSimplifications += elisacoreFoldMaskedSingleBits(*unwrap(module));
  finalSimplifications += elisacoreFoldShiftXorLoops(*unwrap(module));
#endif
  if (finalSimplifications) {
    auto opts = LLVMCreatePassBuilderOptions();
    auto err = LLVMRunPasses(module, "function(instcombine<no-verify-fixpoint>,simplifycfg)", target, opts);
    LLVMDisposePassBuilderOptions(opts);
    if (err) { LLVMConsumeError(err); return 2; }
    status = 1;
  }
  if (elisacoreCompactEvenRanges(module)) status = 1;
  if (elisacoreBiasValidationReturns(module)) status = 1;
  if (elisacoreReuseEdgeDivisions(*unwrap(module))) status = 1;
  if (elisacoreSplitFactoredDivisions(*unwrap(module))) status = 1;
  if (elisacoreSplitRemainderRecurrences(*unwrap(module))) status = 1;
#if LLVM_VERSION_MAJOR >= 23
  if (elisacoreFoldConstantIntegerPaths(*unwrap(module))) status = 1;
  if (elisacoreNarrowBoundedCarries(*unwrap(module))) status = 1;
  if (elisacoreFoldConditionalDoubling(*unwrap(module))) status = 1;
  unsigned specialized = elisacoreSpecializeLiteralDivisors(*unwrap(module), target);
  if (specialized == 2) return 2;
  if (specialized) status = 1;
  unsigned stackViews = elisacoreInlineStackViewHelpers(*unwrap(module), target);
  if (stackViews == 2) return 2;
  if (stackViews) status = 1;
  if (elisacoreVersionBoundedQuotientSums(*unwrap(module))) status = 1;
#endif
  return status;
}
