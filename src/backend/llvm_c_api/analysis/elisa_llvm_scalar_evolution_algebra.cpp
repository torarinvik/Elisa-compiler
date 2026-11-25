// Implementation of elisa_llvm_scalar_evolution_algebra.h.
#include "elisa_llvm_scalar_evolution_algebra.h"
#include "elisa_llvm_function_analyses.h"

#include <llvm/Analysis/ScalarEvolutionExpressions.h>
#include <llvm/Support/CBindingWrapping.h>

using namespace llvm;
using namespace elisa_llvm;

namespace {
const SCEV *unwrapExpression(ElisaScalarEvolutionExpressionRef expression) {
  return reinterpret_cast<const SCEV *>(expression);
}

ElisaScalarEvolutionExpressionRef wrapExpression(const SCEV *expression) {
  return reinterpret_cast<ElisaScalarEvolutionExpressionRef>(const_cast<SCEV *>(expression));
}

ScalarEvolution &evolutionOf(ElisaFunctionAnalysesRef analyses) {
  return unwrapAnalyses(analyses)->scalarEvolution();
}
} // namespace

extern "C" {

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionAdd(ElisaFunctionAnalysesRef analyses,
                                                              ElisaScalarEvolutionExpressionRef left,
                                                              ElisaScalarEvolutionExpressionRef right) {
  return wrapExpression(evolutionOf(analyses).getAddExpr(unwrapExpression(left), unwrapExpression(right)));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionMinus(ElisaFunctionAnalysesRef analyses,
                                                                ElisaScalarEvolutionExpressionRef left,
                                                                ElisaScalarEvolutionExpressionRef right) {
  return wrapExpression(evolutionOf(analyses).getMinusSCEV(unwrapExpression(left), unwrapExpression(right)));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionMultiply(ElisaFunctionAnalysesRef analyses,
                                                                   ElisaScalarEvolutionExpressionRef left,
                                                                   ElisaScalarEvolutionExpressionRef right) {
  return wrapExpression(evolutionOf(analyses).getMulExpr(unwrapExpression(left), unwrapExpression(right)));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionNegate(ElisaFunctionAnalysesRef analyses,
                                                                 ElisaScalarEvolutionExpressionRef value) {
  return wrapExpression(evolutionOf(analyses).getNegativeSCEV(unwrapExpression(value)));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionAddTerms(ElisaFunctionAnalysesRef analyses,
                                                                   ElisaScalarEvolutionExpressionRef *terms,
                                                                   uint32_t count) {
  SmallVector<SCEVUse, 4> Terms;
  for (uint32_t Index = 0; Index < count; ++Index) Terms.push_back(unwrapExpression(terms[Index]));
  return wrapExpression(evolutionOf(analyses).getAddExpr(Terms));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionAddRecurrence(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef start,
    ElisaScalarEvolutionExpressionRef step, ElisaLoopRef loop, int no_unsigned_wrap) {
  return wrapExpression(evolutionOf(analyses).getAddRecExpr(unwrapExpression(start), unwrapExpression(step),
                                                            unwrapLoop(loop),
                                                            no_unsigned_wrap ? SCEV::FlagNUW : SCEV::FlagAnyWrap));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionStepRecurrence(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef recurrence) {
  return wrapExpression(
      cast<SCEVAddRecExpr>(unwrapExpression(recurrence))->getStepRecurrence(evolutionOf(analyses)));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionSymbolicMaxBackedgeTakenCount(
    ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop) {
  return wrapExpression(evolutionOf(analyses).getSymbolicMaxBackedgeTakenCount(unwrapLoop(loop)));
}

int ElisaLLVMScalarEvolutionIsKnownPredicateAt(ElisaFunctionAnalysesRef analyses, LLVMIntPredicate predicate,
                                               ElisaScalarEvolutionExpressionRef left,
                                               ElisaScalarEvolutionExpressionRef right, LLVMValueRef at) {
  return evolutionOf(analyses).isKnownPredicateAt(static_cast<ICmpInst::Predicate>(predicate),
                                                  unwrapExpression(left), unwrapExpression(right),
                                                  cast<Instruction>(unwrap(at)));
}

int ElisaLLVMScalarEvolutionIsKnownNonZero(ElisaFunctionAnalysesRef analyses,
                                           ElisaScalarEvolutionExpressionRef expression) {
  return evolutionOf(analyses).isKnownNonZero(unwrapExpression(expression));
}

int ElisaLLVMScalarEvolutionIsKnownNonNegative(ElisaFunctionAnalysesRef analyses,
                                               ElisaScalarEvolutionExpressionRef expression) {
  return evolutionOf(analyses).isKnownNonNegative(unwrapExpression(expression));
}

int ElisaLLVMScalarEvolutionIsLoopInvariant(ElisaFunctionAnalysesRef analyses,
                                            ElisaScalarEvolutionExpressionRef expression, ElisaLoopRef loop) {
  return evolutionOf(analyses).isLoopInvariant(unwrapExpression(expression), unwrapLoop(loop));
}

uint32_t ElisaLLVMScalarEvolutionTypeSizeInBits(ElisaFunctionAnalysesRef analyses, LLVMTypeRef type) {
  return static_cast<uint32_t>(evolutionOf(analyses).getTypeSizeInBits(unwrap(type)));
}

} // extern "C"
