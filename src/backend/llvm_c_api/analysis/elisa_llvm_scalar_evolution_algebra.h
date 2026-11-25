/* C API for scalar evolution's algebra and its knowledge queries, which LLVM's C API does
 * not expose: building sums, differences, products, negations and add recurrences of
 * expressions, and asking what scalar evolution knows about them (an order at an
 * instruction, a nonzero or nonnegative value, loop invariance, a loop's symbolic maximum
 * backedge-taken count, a recurrence's step, a type's width).
 *
 * Expressions are ElisaScalarEvolutionExpressionRef handles from
 * elisa_llvm_scalar_evolution_expressions.h, uniqued by the analyses' scalar evolution, so
 * equal handles are equal expressions.
 */
#ifndef ELISA_LLVM_SCALAR_EVOLUTION_ALGEBRA_H
#define ELISA_LLVM_SCALAR_EVOLUTION_ALGEBRA_H

#include "elisa_llvm_scalar_evolution_expressions.h"

#ifdef __cplusplus
extern "C" {
#endif

/* getAddExpr(left, right), getMinusSCEV(left, right), getMulExpr(left, right) and
 * getNegativeSCEV(value), with no wrap flags. */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionAdd(ElisaFunctionAnalysesRef analyses,
                                                              ElisaScalarEvolutionExpressionRef left,
                                                              ElisaScalarEvolutionExpressionRef right);
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionMinus(ElisaFunctionAnalysesRef analyses,
                                                                ElisaScalarEvolutionExpressionRef left,
                                                                ElisaScalarEvolutionExpressionRef right);
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionMultiply(ElisaFunctionAnalysesRef analyses,
                                                                   ElisaScalarEvolutionExpressionRef left,
                                                                   ElisaScalarEvolutionExpressionRef right);
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionNegate(ElisaFunctionAnalysesRef analyses,
                                                                 ElisaScalarEvolutionExpressionRef value);
/* getAddExpr over COUNT terms at once (a SmallVector of SCEVUse), with no wrap flags. */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionAddTerms(ElisaFunctionAnalysesRef analyses,
                                                                   ElisaScalarEvolutionExpressionRef *terms,
                                                                   uint32_t count);
/* getAddRecExpr(start, step, loop, FlagNUW when no_unsigned_wrap is nonzero). */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionAddRecurrence(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef start,
    ElisaScalarEvolutionExpressionRef step, ElisaLoopRef loop, int no_unsigned_wrap);
/* SCEVAddRecExpr::getStepRecurrence of an add recurrence. */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionStepRecurrence(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef recurrence);
/* getSymbolicMaxBackedgeTakenCount(loop): may be a COULD_NOT_COMPUTE node. */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionSymbolicMaxBackedgeTakenCount(
    ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop);
/* isKnownPredicateAt(predicate, left, right, at). */
int ElisaLLVMScalarEvolutionIsKnownPredicateAt(ElisaFunctionAnalysesRef analyses, LLVMIntPredicate predicate,
                                               ElisaScalarEvolutionExpressionRef left,
                                               ElisaScalarEvolutionExpressionRef right, LLVMValueRef at);
/* isKnownNonZero, isKnownNonNegative and isLoopInvariant(expression, loop). */
int ElisaLLVMScalarEvolutionIsKnownNonZero(ElisaFunctionAnalysesRef analyses,
                                           ElisaScalarEvolutionExpressionRef expression);
int ElisaLLVMScalarEvolutionIsKnownNonNegative(ElisaFunctionAnalysesRef analyses,
                                               ElisaScalarEvolutionExpressionRef expression);
int ElisaLLVMScalarEvolutionIsLoopInvariant(ElisaFunctionAnalysesRef analyses,
                                            ElisaScalarEvolutionExpressionRef expression, ElisaLoopRef loop);
/* getTypeSizeInBits of a SCEVable type (an integer's width, or the pointer index width). */
uint32_t ElisaLLVMScalarEvolutionTypeSizeInBits(ElisaFunctionAnalysesRef analyses, LLVMTypeRef type);

#ifdef __cplusplus
}
#endif

#endif
