//go:build cgo
#include <llvm/Config/llvm-config.h>
#include <llvm-c/Core.h>
#include <llvm-c/TargetMachine.h>
#if LLVM_VERSION_MAJOR == 23
#include <llvm/ADT/APInt.h>
#include <llvm/ADT/DenseMap.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/Instructions.h>
#include <llvm/IR/InstIterator.h>
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
#include <llvm/Analysis/InlineCost.h>
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
#include <llvm/Transforms/Scalar/DivRemPairs.h>
#include "llvm_array_value_ranges.h"
#include "llvm_dead_trap_exits.h"
#include "llvm_path_ranges.h"
#include "llvm_index_bounds.h"
#include "llvm_view_bounded_fills.h"
#include "llvm_indexed_prefix.h"
#include "llvm_proven_checks.h"
#include "llvm_validated_reads.h"
#include "llvm_bounded_trip_ranges.h"
#include "llvm_bisection_check_versioning.h"

using namespace llvm;

// Also run before O3 (from the scratch-prefix pass), while loops are still
// in source shape: a countdown scan the unroller later splits into a
// prologue and a stride -4 body is a guarded `n - 1` loop there.
extern "C" unsigned elisacoreRemoveIndexedPrefixFills(LLVMModuleRef Module) {
  if (!Module) return 0;
  unsigned Removed = ElisaIndexedPrefix::removeIndexedPrefixFills(*unwrap(Module));
  Removed += ElisaValidatedReads::annotateValidatedReads(*unwrap(Module));
  Removed += ElisaBisectionChecks::versionBisectionChecks(*unwrap(Module));
  return Removed + ElisaViewBounds::shrinkViewFills(*unwrap(Module));
}

extern "C" unsigned elisacorePairEarlyDivisions(LLVMModuleRef moduleRef,
                                                LLVMTargetMachineRef targetRef) {
  auto &module = *unwrap(moduleRef);
  if (!module.getTargetTriple().isAArch64()) return 0;
  PassBuilder builder(reinterpret_cast<TargetMachine *>(targetRef));
  FunctionAnalysisManager analyses;
  builder.registerFunctionAnalyses(analyses);
  FunctionPassManager passes;
  passes.addPass(DivRemPairsPass());
  for (Function &function : module) {
    if (function.isDeclaration() || function.hasOptNone()) continue;
    bool runtimeUnsignedRemainder = false;
    bool otherRemainder = false;
    for (const Instruction &instruction : instructions(function)) {
      if (instruction.getOpcode() == Instruction::URem &&
          instruction.getType()->isIntegerTy() &&
          !isa<ConstantInt>(instruction.getOperand(1))) {
        runtimeUnsignedRemainder = true;
      } else if (instruction.getOpcode() == Instruction::URem ||
                 instruction.getOpcode() == Instruction::SRem) {
        otherRemainder = true;
      }
    }
    // The default pipeline can retain a remainder test until AArch64
    // instruction selection, where it can become MSUB and CBZ/CBNZ.
    if (runtimeUnsignedRemainder && !otherRemainder) continue;
    if (runtimeUnsignedRemainder || otherRemainder) passes.run(function, analyses);
  }
  return 1;
}

unsigned elisacoreFoldConstantIntegerPaths(llvm::Module &);
unsigned elisacoreFoldScalarLoopIdioms(llvm::Module &);
unsigned elisacoreFoldOddTrailingZeroSelects(llvm::Module &);
unsigned elisacoreFoldReverseByteReductions(llvm::Module &);
#include "llvm_guarded_unsigned_compare.h"
#include "llvm_vector_or_accumulators.h"
#include "llvm_bisection_ranges.h"
#include "llvm_checked_signed_ranges.h"
#include "llvm_recursive_argument_bounds.h"
#include "llvm_validation_loop_passes.h"
#include "llvm_copied_scratch.h"
#include "llvm_validation_bounded_division.h"

#else
extern "C" unsigned elisacoreRemoveIndexedPrefixFills(LLVMModuleRef) { return 0; }
extern "C" unsigned elisacorePairEarlyDivisions(LLVMModuleRef, LLVMTargetMachineRef) { return 0; }
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
  // Let PHI elimination move exit-only copies onto loop exit edges.
  static bool installed = false;
  if (installed) return;
  installed = true;
  const char *args[] = {"elisac", "-enable-ext-tsp-block-placement=true",
                        "-aarch64-enable-early-ifcvt=false",
                        "-no-phi-elim-live-out-early-exit"};
  LLVMParseCommandLineOptions(4, args, nullptr);
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
                          "-misched=elisa-ordered-selective",
                          "-no-phi-elim-live-out-early-exit"};
    LLVMParseCommandLineOptions(4, args, nullptr);
    return;
  }
#endif
  const char *args[] = {"elisac", "-aarch64-enable-early-ifcvt=false",
                        "-no-phi-elim-live-out-early-exit"};
  LLVMParseCommandLineOptions(3, args, nullptr);
#endif
}
#include "llvm_checked_mul.cpp"
extern "C" unsigned elisacoreBoundedLoopUnswitch(LLVMModuleRef);
#include "llvm_bounded_factorial.cpp"
extern "C" unsigned elisacoreElideArrayRoundTrips(LLVMModuleRef);
extern "C" unsigned elisacoreOptimizeSqrtNonNaN(LLVMModuleRef, LLVMTargetMachineRef);
extern "C" unsigned elisacoreOptimizeBoundedSums(LLVMModuleRef, LLVMTargetMachineRef);
extern "C" unsigned elisacoreOptimizeIndexBounds(LLVMModuleRef, LLVMTargetMachineRef);
#include "llvm_guarded_counter.cpp"
extern "C" unsigned elisacoreFoldBoundedRemainders(LLVMModuleRef);
extern "C" unsigned elisacoreFoldSignedRangeMasks(LLVMModuleRef);
#include "llvm_ordered_vector.cpp"
#include "llvm_special_epilogue.cpp"
#include "llvm_even_range.cpp"
#if LLVM_VERSION_MAJOR >= 23
#include "llvm_guarded_counter_bounds.cpp"
#endif

#include "llvm_nested_vector_unroll.h"

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
  bool Found = false;
  for (Function &F : M) {
    if (F.isDeclaration()) continue;
    DominatorTree DT(F); LoopInfo LI(DT);
    for (Loop *L : LI.getLoopsInPreorder()) {
      if (!L->getParentLoop()) continue;
      if (M.getTargetTriple().isMacOSX()) unrollNestedVectorRecurrence(*L);
      for (BasicBlock *B : L->blocks())
        for (Instruction &I : *B)
          if (auto *Load = dyn_cast<LoadInst>(&I))
            if (Load->getType()->isVectorTy()) Found = true;
    }
  }
  return Found;
}

// The late scalar cleanup sequence lives in Elisa
// (llvm_passes/late_cleanup/late_scalar_cleanup.elisa); these are its entries.
#include "llvm_late_cleanup_entries.h"
