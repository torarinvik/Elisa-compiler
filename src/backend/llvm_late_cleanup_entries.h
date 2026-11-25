// C entry points for each pass of the late scalar cleanup and of the scratch-prefix
// sequence, so their order (and the late cleanup's pipelines and status) lives in Elisa
// (`llvm_passes/late_cleanup/late_scalar_cleanup.elisa` and
// `llvm_passes/scratch_prefix/scratch_prefix_sequence.elisa`) while the passes themselves
// are still C++. Included at the end of llvm_validation_peel.cpp, the
// translation unit that defines every pass named here.

#define ELISA_MODULE_PASS_ENTRY(EntryName, Pass)                                          \
  extern "C" unsigned EntryName(LLVMModuleRef Module) { return Pass(*unwrap(Module)); }

ELISA_MODULE_PASS_ENTRY(elisacoreRemoveIndexedPrefixFillsOnly,
                        ElisaIndexedPrefix::removeIndexedPrefixFills)

#undef ELISA_MODULE_PASS_ENTRY
