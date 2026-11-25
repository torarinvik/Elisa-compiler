// Implementation of elisa_llvm_scalar_evolution_expressions.h.
#include "elisa_llvm_scalar_evolution_expressions.h"
#include "elisa_llvm_function_analyses.h"

#include <llvm/Analysis/ScalarEvolutionExpressions.h>
#include <llvm/IR/ConstantRange.h>
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
} // namespace

extern "C" {

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionExitCount(ElisaFunctionAnalysesRef analyses,
                                                                    ElisaLoopRef loop,
                                                                    LLVMBasicBlockRef exiting_block) {
  return wrapExpression(unwrapAnalyses(analyses)->scalarEvolution().getExitCount(
      unwrapLoop(loop), unwrap(exiting_block)));
}

uint32_t ElisaLLVMScalarEvolutionExpressionKind(ElisaScalarEvolutionExpressionRef expression) {
  switch (unwrapExpression(expression)->getSCEVType()) {
  case scCouldNotCompute: return ELISA_SCEV_COULD_NOT_COMPUTE;
  case scConstant: return ELISA_SCEV_CONSTANT;
  case scUnknown: return ELISA_SCEV_UNKNOWN;
  case scTruncate: return ELISA_SCEV_TRUNCATE;
  case scZeroExtend: return ELISA_SCEV_ZERO_EXTEND;
  case scSignExtend: return ELISA_SCEV_SIGN_EXTEND;
  case scAddExpr: return ELISA_SCEV_ADD;
  case scMulExpr: return ELISA_SCEV_MULTIPLY;
  case scUMinExpr: return ELISA_SCEV_UNSIGNED_MINIMUM;
  case scUMaxExpr: return ELISA_SCEV_UNSIGNED_MAXIMUM;
  case scSMinExpr: return ELISA_SCEV_SIGNED_MINIMUM;
  case scSMaxExpr: return ELISA_SCEV_SIGNED_MAXIMUM;
  case scAddRecExpr: return ELISA_SCEV_ADD_RECURRENCE;
  case scUDivExpr: return ELISA_SCEV_UNSIGNED_DIVIDE;
  default: break;
  }
  if (isa<SCEVCastExpr>(unwrapExpression(expression))) return ELISA_SCEV_OTHER_CAST;
  if (isa<SCEVNAryExpr>(unwrapExpression(expression))) return ELISA_SCEV_OTHER_OPERATION;
  return ELISA_SCEV_OTHER;
}

LLVMTypeRef ElisaLLVMScalarEvolutionExpressionType(ElisaScalarEvolutionExpressionRef expression) {
  return wrap(unwrapExpression(expression)->getType());
}

uint32_t ElisaLLVMScalarEvolutionExpressionOperandCount(ElisaScalarEvolutionExpressionRef expression) {
  return static_cast<uint32_t>(unwrapExpression(expression)->operands().size());
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionExpressionOperandAt(
    ElisaScalarEvolutionExpressionRef expression, uint32_t index) {
  return wrapExpression(unwrapExpression(expression)->operands()[index]);
}

LLVMValueRef ElisaLLVMScalarEvolutionExpressionValue(ElisaScalarEvolutionExpressionRef expression) {
  const SCEV *Expression = unwrapExpression(expression);
  if (auto *Constant = dyn_cast<SCEVConstant>(Expression)) return wrap(Constant->getValue());
  if (auto *Unknown = dyn_cast<SCEVUnknown>(Expression)) return wrap(Unknown->getValue());
  return nullptr;
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionOfValue(ElisaFunctionAnalysesRef analyses,
                                                                  LLVMValueRef value) {
  return wrapExpression(unwrapAnalyses(analyses)->scalarEvolution().getSCEV(unwrap(value)));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionConstantOf(ElisaFunctionAnalysesRef analyses,
                                                                     LLVMTypeRef type, uint64_t value) {
  return wrapExpression(unwrapAnalyses(analyses)->scalarEvolution().getConstant(unwrap(type), value));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionRewriteValue(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef expression, LLVMValueRef value,
    ElisaScalarEvolutionExpressionRef replacement) {
  ValueToSCEVMapTy Bindings;
  Bindings[unwrap(value)] = unwrapExpression(replacement);
  return wrapExpression(SCEVParameterRewriter::rewrite(
      unwrapExpression(expression), unwrapAnalyses(analyses)->scalarEvolution(), Bindings));
}

ElisaLoopRef ElisaLLVMScalarEvolutionRecurrenceLoop(ElisaScalarEvolutionExpressionRef expression) {
  auto *Recurrence = dyn_cast<SCEVAddRecExpr>(unwrapExpression(expression));
  return Recurrence ? wrapLoop(const_cast<Loop *>(Recurrence->getLoop())) : nullptr;
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionEvaluateAtIteration(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef recurrence,
    ElisaScalarEvolutionExpressionRef iteration) {
  return wrapExpression(cast<SCEVAddRecExpr>(unwrapExpression(recurrence))
                            ->evaluateAtIteration(unwrapExpression(iteration),
                                                  unwrapAnalyses(analyses)->scalarEvolution()));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionApplyLoopGuards(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef expression, ElisaLoopRef loop) {
  return wrapExpression(unwrapAnalyses(analyses)->scalarEvolution().applyLoopGuards(
      unwrapExpression(expression), unwrapLoop(loop)));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionPointerBase(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef expression) {
  return wrapExpression(unwrapAnalyses(analyses)->scalarEvolution().getPointerBase(
      unwrapExpression(expression)));
}

ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionRemovePointerBase(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef expression) {
  return wrapExpression(unwrapAnalyses(analyses)->scalarEvolution().removePointerBase(
      unwrapExpression(expression)));
}

ElisaConstantRangeRef ElisaLLVMScalarEvolutionExpressionUnsignedRange(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef expression) {
  ConstantRange Range =
      unwrapAnalyses(analyses)->scalarEvolution().getUnsignedRange(unwrapExpression(expression));
  return reinterpret_cast<ElisaConstantRangeRef>(new ConstantRange(std::move(Range)));
}

} // extern "C"
