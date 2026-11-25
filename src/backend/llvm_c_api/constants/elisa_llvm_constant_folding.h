/* C API for llvm/Analysis/ConstantFolding.h, which LLVM's C API does not expose: folding an
 * instruction, an intrinsic or a load over constant operands with the module's data layout.
 * Each returns null when the operands do not fold.
 */
#ifndef ELISA_LLVM_CONSTANT_FOLDING_H
#define ELISA_LLVM_CONSTANT_FOLDING_H

#include <llvm-c/Core.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ConstantFoldInstOperands(instruction, operands, layout, no TargetLibraryInfo,
 * allow_non_deterministic): INSTRUCTION evaluated with its operands replaced by the
 * COUNT constants at OPERANDS. */
LLVMValueRef ElisaLLVMConstantFoldInstructionOperands(LLVMValueRef instruction, LLVMValueRef *operands,
                                                      uint32_t count, LLVMModuleRef module,
                                                      int allow_non_deterministic);
/* ConstantFoldIntrinsic(id, operands, type): the intrinsic ID over constant OPERANDS. */
LLVMValueRef ElisaLLVMConstantFoldIntrinsic(uint32_t id, LLVMValueRef *operands, uint32_t count,
                                            LLVMTypeRef type);
/* ConstantFoldLoadFromConstPtr(pointer, type, layout): a TYPE load from a constant POINTER
 * into constant memory. */
LLVMValueRef ElisaLLVMConstantFoldLoad(LLVMValueRef pointer, LLVMTypeRef type, LLVMModuleRef module);

#ifdef __cplusplus
}
#endif

#endif
