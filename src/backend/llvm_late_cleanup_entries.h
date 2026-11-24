// C entry points for each pass of the late scalar cleanup, so its sequence
// (pass order, cleanup pipelines, status) lives in Elisa
// (`llvm_passes/late_scalar_cleanup.elisa`) while the passes themselves are
// still C++. Included at the end of llvm_validation_peel.cpp, the
// translation unit that defines every pass named here.
//
// Passes that report functions back fill a caller-owned buffer of
// `capacity` handles in module order and return how many they wrote; the
// caller sizes the buffer to the module's function count.

namespace ElisaLateCleanupEntries {
// The functions of Module that Selected contains, in module order.
template <typename Set>
static unsigned writeFunctions(Module &Module, const Set &Selected, LLVMValueRef *Functions,
                               unsigned Capacity) {
  unsigned Count = 0;
  for (Function &F : Module)
    if (Selected.contains(&F) && Count < Capacity) Functions[Count++] = wrap(&F);
  return Count;
}
} // namespace ElisaLateCleanupEntries

#define ELISA_MODULE_PASS_ENTRY(EntryName, Pass)                                          \
  extern "C" unsigned EntryName(LLVMModuleRef Module) { return Pass(*unwrap(Module)); }
#define ELISA_TARGET_PASS_ENTRY(EntryName, Pass)                                          \
  extern "C" unsigned EntryName(LLVMModuleRef Module, LLVMTargetMachineRef Target) {      \
    return Pass(*unwrap(Module), Target);                                                 \
  }

extern "C" unsigned elisacoreShouldRevisitNestedVectorLoops(LLVMModuleRef Module) {
  return shouldRevisitNestedVectorLoops(*unwrap(Module));
}
extern "C" unsigned elisacoreOptimizeOrderedConversionsEntry(LLVMModuleRef Module,
                                                            LLVMTargetMachineRef Target) {
  return elisacoreOptimizeOrderedConversions(Module, Target);
}

// Writes the functions whose checked-counter exits were removed (the
// reductions they may expose need the vectorizer again) to Functions.
extern "C" unsigned elisacoreFoldGuardedCounters(LLVMModuleRef Module, LLVMValueRef *Functions,
                                                 unsigned Capacity, unsigned *FunctionCount) {
  SmallVector<Function *, 8> Vectorizable;
  unsigned Changed = foldGuardedCounters(*unwrap(Module), Vectorizable);
  // Kept in the pass's own order, repeats included, as the C++ loop ran.
  unsigned Count = 0;
  for (Function *F : Vectorizable)
    if (Count < Capacity) Functions[Count++] = wrap(F);
  *FunctionCount = Count;
  return Changed;
}

ELISA_MODULE_PASS_ENTRY(elisacoreEliminateCopiedScratch, ElisaCopiedScratch::eliminate)
ELISA_MODULE_PASS_ENTRY(elisacoreEliminateFullArrayInitializers,
                        ElisaCopiedScratch::eliminateFullArrayInitializers)
ELISA_MODULE_PASS_ENTRY(elisacoreForwardLoopLoads, ElisaCopiedScratch::forwardLoopLoads)
ELISA_MODULE_PASS_ENTRY(elisacoreAnnotateArrayValueRangesEntry,
                        ElisaArrayRanges::annotateArrayValueRanges)
ELISA_MODULE_PASS_ENTRY(elisacoreRemoveDeadTrapExitsEntry, ElisaDeadTrapExits::removeDeadTrapExits)
ELISA_MODULE_PASS_ENTRY(elisacoreRemoveIndexedPrefixFillsOnly,
                        ElisaIndexedPrefix::removeIndexedPrefixFills)
ELISA_MODULE_PASS_ENTRY(elisacoreShrinkViewFills, ElisaViewBounds::shrinkViewFills)
ELISA_MODULE_PASS_ENTRY(elisacoreRemoveProvenChecksEntry, ElisaProvenChecks::removeProvenChecks)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldBoundedTripChecks, ElisaBoundedTripRanges::foldBoundedTripChecks)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldShiftParityLoopsEntry, elisacoreFoldShiftParityLoops)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldShiftBitReverseLoopsEntry, elisacoreFoldShiftBitReverseLoops)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldRingIndexBoundsEntry, elisacoreFoldRingIndexBounds)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldGuardedCounterBoundsEntry, elisacoreFoldGuardedCounterBounds)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldHalvingRunsEntry, elisacoreFoldHalvingRuns)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldRangeAndLoopsEntry, elisacoreFoldRangeAndLoops)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldScalarLoopIdiomsEntry, elisacoreFoldScalarLoopIdioms)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldShiftXorLoopsEntry, elisacoreFoldShiftXorLoops)
ELISA_MODULE_PASS_ENTRY(elisacoreReuseEdgeDivisionsEntry, elisacoreReuseEdgeDivisions)
ELISA_MODULE_PASS_ENTRY(elisacoreSplitFactoredDivisionsEntry, elisacoreSplitFactoredDivisions)
ELISA_MODULE_PASS_ENTRY(elisacoreSplitRemainderRecurrencesEntry, elisacoreSplitRemainderRecurrences)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldConstantIntegerPathsEntry, elisacoreFoldConstantIntegerPaths)
ELISA_MODULE_PASS_ENTRY(elisacoreNarrowBoundedCarriesEntry, elisacoreNarrowBoundedCarries)
ELISA_TARGET_PASS_ENTRY(elisacoreSpecializeLiteralDivisorsEntry, elisacoreSpecializeLiteralDivisors)
ELISA_TARGET_PASS_ENTRY(elisacoreInlineStackViewHelpersEntry, elisacoreInlineStackViewHelpers)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldReverseByteReductionsEntry, elisacoreFoldReverseByteReductions)
ELISA_MODULE_PASS_ENTRY(elisacoreVersionBoundedQuotientSumsEntry, elisacoreVersionBoundedQuotientSums)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldOddTrailingZeroSelectsEntry, elisacoreFoldOddTrailingZeroSelects)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldInterleavedByteStoresEntry, elisacoreFoldInterleavedByteStores)
ELISA_MODULE_PASS_ENTRY(elisacoreFoldRecursiveArgumentBounds, foldRecursiveArgumentBounds)

extern "C" void elisacoreFoldGuardedUnsignedComparisons(LLVMModuleRef Module) {
  foldGuardedUnsignedComparisons(*unwrap(Module));
}
extern "C" void elisacoreFoldWideVectorOrAccumulators(LLVMModuleRef Module) {
  foldWideVectorOrAccumulators(*unwrap(Module));
}

// Folds proven signed checks across the module and writes the callers that
// had checked helpers inlined into them, in module order.
extern "C" unsigned elisacoreFoldProvenSignedChecks(LLVMModuleRef Module,
                                                    LLVMTargetMachineRef Target,
                                                    LLVMValueRef *Functions, unsigned Capacity,
                                                    unsigned *FunctionCount) {
  SmallPtrSet<Function *, 4> Inlined;
  unsigned Changed = foldProvenSignedChecks(*unwrap(Module),
                                            reinterpret_cast<TargetMachine *>(Target), &Inlined);
  *FunctionCount = ElisaLateCleanupEntries::writeFunctions(*unwrap(Module), Inlined, Functions,
                                                           Capacity);
  return Changed;
}

// The per-function follow-up after a caller's cleanup pipeline ran.
extern "C" void elisacoreRefoldProvenSignedChecks(LLVMModuleRef Module, LLVMTargetMachineRef Target,
                                                  LLVMValueRef Function) {
  auto &F = *cast<llvm::Function>(unwrap(Function));
  stabilizeGuardedSignedOperands(F);
  foldProvenSignedChecks(*unwrap(Module), reinterpret_cast<TargetMachine *>(Target), nullptr, &F);
}

#undef ELISA_MODULE_PASS_ENTRY
#undef ELISA_TARGET_PASS_ENTRY
