// C entry points for each pass of the late scalar cleanup, so its sequence
// (pass order, cleanup pipelines, status) lives in Elisa
// (`llvm_passes/late_cleanup/late_scalar_cleanup.elisa`) while the passes themselves are
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
ELISA_MODULE_PASS_ENTRY(elisacoreFoldRecursiveArgumentBounds, foldRecursiveArgumentBounds)


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
