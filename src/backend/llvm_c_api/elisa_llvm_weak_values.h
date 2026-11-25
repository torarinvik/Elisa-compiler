/* C API for a list of llvm::WeakTrackingVH, which LLVM's C API does not expose: values
 * collected before a rewrite that may erase some of them, each read back as null once
 * erased (or as its replacement after replaceAllUsesWith).
 *
 * The caller disposes a list with ElisaLLVMDisposeWeakValues.
 */
#ifndef ELISA_LLVM_WEAK_VALUES_H
#define ELISA_LLVM_WEAK_VALUES_H

#include <llvm-c/Core.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ElisaOpaqueWeakValues *ElisaWeakValuesRef;

ElisaWeakValuesRef ElisaLLVMCreateWeakValues(void);
void ElisaLLVMDisposeWeakValues(ElisaWeakValuesRef values);
void ElisaLLVMWeakValuesPush(ElisaWeakValuesRef values, LLVMValueRef value);
uint32_t ElisaLLVMWeakValuesCount(ElisaWeakValuesRef values);
/* The value the handle at INDEX tracks now; null once that value was deleted. */
LLVMValueRef ElisaLLVMWeakValueAt(ElisaWeakValuesRef values, uint32_t index);

#ifdef __cplusplus
}
#endif

#endif
