/* C API for llvm::ConstantRange, which LLVM's C API does not expose: the
 * wrapping interval of integer values a comparison admits, at any width.
 *
 * Every function that returns a range allocates it; the caller disposes it
 * with ElisaLLVMDisposeConstantRange. Constants are ConstantInt values.
 */
#ifndef ELISA_LLVM_CONSTANT_RANGE_H
#define ELISA_LLVM_CONSTANT_RANGE_H

#include <llvm-c/Core.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ElisaOpaqueConstantRange *ElisaConstantRangeRef;

/* ConstantRange::makeAllowedICmpRegion(predicate, {constant}): every value
 * `x` for which `x <predicate> constant` can hold. */
ElisaConstantRangeRef ElisaLLVMConstantRangeAllowedByCompare(LLVMIntPredicate predicate,
                                                             LLVMValueRef constant);
/* ConstantRange::sub with the single value `constant`: `range - constant`. */
ElisaConstantRangeRef ElisaLLVMConstantRangeSubtract(ElisaConstantRangeRef range,
                                                     LLVMValueRef constant);
int ElisaLLVMConstantRangeIsEmpty(ElisaConstantRangeRef range);
/* Whether getSignedMax() of the range is the width's signed maximum. */
int ElisaLLVMConstantRangeReachesSignedMax(ElisaConstantRangeRef range);
/* Whether getSignedMin() of the range is negative. */
int ElisaLLVMConstantRangeSignedMinIsNegative(ElisaConstantRangeRef range);
/* ConstantRange::contains of `value` at the range's width. */
int ElisaLLVMConstantRangeContains(ElisaConstantRangeRef range, uint64_t value);
/* Whether getUnsignedMax() of the range is at most the constant, of the same width. */
int ElisaLLVMConstantRangeUnsignedMaxAtMost(ElisaConstantRangeRef range, LLVMValueRef constant);
void ElisaLLVMDisposeConstantRange(ElisaConstantRangeRef range);

#ifdef __cplusplus
}
#endif

#endif
