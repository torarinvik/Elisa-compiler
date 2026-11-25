// C entry points for each pass of the late scalar cleanup, so its sequence
// (pass order, cleanup pipelines, status) lives in Elisa
// (`llvm_passes/late_cleanup/late_scalar_cleanup.elisa`) while the passes themselves are
// still C++. Included at the end of llvm_validation_peel.cpp, the
// translation unit that defines every pass named here.

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

#undef ELISA_MODULE_PASS_ENTRY
