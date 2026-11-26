/* C API for LLVM's default optimization pipeline as PassBuilder builds it.
 *
 * LLVMRunPasses only takes pipeline text, and the text `default<O3>` does not run the
 * same pipeline as PassBuilder::buildPerModuleDefaultPipeline(O3): on LLVM 23 the two
 * vectorize the same module differently. The passes ported from C++ that ran the
 * built pipelines run them through these shims. */
#ifndef ELISA_LLVM_PASS_PIPELINES_H
#define ELISA_LLVM_PASS_PIPELINES_H

#include <llvm-c/Core.h>
#include <llvm-c/TargetMachine.h>

#ifdef __cplusplus
extern "C" {
#endif

/* buildPerModuleDefaultPipeline(O3) of a PassBuilder for `target` (NULL: none), run
 * over the module with fresh analysis managers and no pass instrumentation. */
void ElisaLLVMRunDefaultO3Pipeline(LLVMModuleRef module, LLVMTargetMachineRef target);

/* buildFunctionSimplificationPipeline(O1, no LTO phase) of a PassBuilder without a
 * target machine, run over one function with fresh analysis managers. No pipeline text
 * names this pipeline, so LLVMRunPassesOnFunction cannot run it. */
void ElisaLLVMRunO1FunctionSimplificationPipeline(LLVMValueRef function);

#ifdef __cplusplus
}
#endif

#endif
