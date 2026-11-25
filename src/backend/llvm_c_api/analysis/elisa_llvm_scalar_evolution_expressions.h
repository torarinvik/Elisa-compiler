/* C API for the expressions of llvm::ScalarEvolution, which LLVM's C API does not expose:
 * a loop exit's count as an expression tree whose nodes a pass can walk, and the unsigned
 * range scalar evolution knows for any node.
 *
 * An ElisaScalarEvolutionExpressionRef is a `const SCEV *`, owned by the scalar evolution
 * of the ElisaFunctionAnalysesRef it came from and valid until those analyses are
 * invalidated or disposed.
 */
#ifndef ELISA_LLVM_SCALAR_EVOLUTION_EXPRESSIONS_H
#define ELISA_LLVM_SCALAR_EVOLUTION_EXPRESSIONS_H

#include "elisa_llvm_analysis.h"
#include "../constants/elisa_llvm_constant_range.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ElisaOpaqueScalarEvolutionExpression *ElisaScalarEvolutionExpressionRef;

/* The kinds of node a pass distinguishes; the rest are OTHER_CAST (a pointer-to-integer
 * cast), OTHER_OPERATION (sequential umin) and OTHER (vscale). */
enum ElisaScalarEvolutionKind {
  ELISA_SCEV_COULD_NOT_COMPUTE = 0,
  ELISA_SCEV_CONSTANT = 1,
  ELISA_SCEV_UNKNOWN = 2,
  ELISA_SCEV_TRUNCATE = 3,
  ELISA_SCEV_ZERO_EXTEND = 4,
  ELISA_SCEV_SIGN_EXTEND = 5,
  ELISA_SCEV_OTHER_CAST = 6,
  ELISA_SCEV_ADD = 7,
  ELISA_SCEV_MULTIPLY = 8,
  ELISA_SCEV_UNSIGNED_MINIMUM = 9,
  ELISA_SCEV_UNSIGNED_MAXIMUM = 10,
  ELISA_SCEV_SIGNED_MINIMUM = 11,
  ELISA_SCEV_SIGNED_MAXIMUM = 12,
  ELISA_SCEV_OTHER_OPERATION = 13,
  ELISA_SCEV_OTHER = 14,
  ELISA_SCEV_ADD_RECURRENCE = 15,
  ELISA_SCEV_UNSIGNED_DIVIDE = 16
};

/* ScalarEvolution::getExitCount(loop, exiting_block): the backedges taken before the
 * block's exit is first taken (exact), or a COULD_NOT_COMPUTE node. */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionExitCount(ElisaFunctionAnalysesRef analyses,
                                                                    ElisaLoopRef loop,
                                                                    LLVMBasicBlockRef exiting_block);
/* The node's kind, as an ElisaScalarEvolutionKind. */
uint32_t ElisaLLVMScalarEvolutionExpressionKind(ElisaScalarEvolutionExpressionRef expression);
/* SCEV::getType of a node other than COULD_NOT_COMPUTE. */
LLVMTypeRef ElisaLLVMScalarEvolutionExpressionType(ElisaScalarEvolutionExpressionRef expression);
/* SCEV::operands: the node's operands, in order (none for a constant or unknown). */
uint32_t ElisaLLVMScalarEvolutionExpressionOperandCount(ElisaScalarEvolutionExpressionRef expression);
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionExpressionOperandAt(
    ElisaScalarEvolutionExpressionRef expression, uint32_t index);
/* The ConstantInt of a CONSTANT node, or the IR value of an UNKNOWN one. */
LLVMValueRef ElisaLLVMScalarEvolutionExpressionValue(ElisaScalarEvolutionExpressionRef expression);
/* ScalarEvolution::getSCEV of a value whose type is SCEVable. */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionOfValue(ElisaFunctionAnalysesRef analyses,
                                                                  LLVMValueRef value);
/* ScalarEvolution::getConstant(type, value): VALUE as a constant of the integer TYPE. */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionConstantOf(ElisaFunctionAnalysesRef analyses,
                                                                     LLVMTypeRef type, uint64_t value);
/* SCEVParameterRewriter::rewrite(expression, {value: replacement}): the expression with each
 * unknown node of VALUE replaced. */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionRewriteValue(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef expression, LLVMValueRef value,
    ElisaScalarEvolutionExpressionRef replacement);
/* The loop of an add recurrence (SCEVAddRecExpr::getLoop), or null for any other node. */
ElisaLoopRef ElisaLLVMScalarEvolutionRecurrenceLoop(ElisaScalarEvolutionExpressionRef expression);
/* SCEVAddRecExpr::evaluateAtIteration(iteration) of an add recurrence. */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionEvaluateAtIteration(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef recurrence,
    ElisaScalarEvolutionExpressionRef iteration);
/* ScalarEvolution::applyLoopGuards(expression, loop). */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionApplyLoopGuards(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef expression, ElisaLoopRef loop);
/* ScalarEvolution::getPointerBase and removePointerBase of a pointer expression. */
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionPointerBase(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef expression);
ElisaScalarEvolutionExpressionRef ElisaLLVMScalarEvolutionRemovePointerBase(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef expression);
/* ScalarEvolution::getUnsignedRange of a node other than COULD_NOT_COMPUTE. */
ElisaConstantRangeRef ElisaLLVMScalarEvolutionExpressionUnsignedRange(
    ElisaFunctionAnalysesRef analyses, ElisaScalarEvolutionExpressionRef expression);

#ifdef __cplusplus
}
#endif

#endif
