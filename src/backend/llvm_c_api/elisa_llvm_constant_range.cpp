// llvm::ConstantRange behind the C API declared in elisa_llvm_constant_range.h.
#include "elisa_llvm_constant_range.h"

#include <llvm/IR/ConstantRange.h>
#include <llvm/IR/Constants.h>
#include <llvm/IR/InstrTypes.h>
#include <llvm/IR/Instructions.h>
#include <llvm/Support/CBindingWrapping.h>

#include <optional>

using namespace llvm;

DEFINE_SIMPLE_CONVERSION_FUNCTIONS(ConstantRange, ElisaConstantRangeRef)

static const APInt &constantValue(LLVMValueRef constant) {
  return cast<ConstantInt>(unwrap(constant))->getValue();
}

extern "C" {

ElisaConstantRangeRef ElisaLLVMConstantRangeAllowedByCompare(LLVMIntPredicate predicate,
                                                             LLVMValueRef constant) {
  auto compare = static_cast<CmpInst::Predicate>(predicate);
  return wrap(new ConstantRange(
      ConstantRange::makeAllowedICmpRegion(compare, ConstantRange(constantValue(constant)))));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeSubtract(ElisaConstantRangeRef range,
                                                     LLVMValueRef constant) {
  return wrap(new ConstantRange(unwrap(range)->sub(ConstantRange(constantValue(constant)))));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeFull(uint32_t width) {
  return wrap(new ConstantRange(ConstantRange::getFull(width)));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeOfConstant(LLVMValueRef constant) {
  return wrap(new ConstantRange(constantValue(constant)));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeExactByCompare(LLVMIntPredicate predicate,
                                                           LLVMValueRef constant) {
  auto compare = static_cast<CmpInst::Predicate>(predicate);
  return wrap(new ConstantRange(ConstantRange::makeExactICmpRegion(compare, constantValue(constant))));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeIntersect(ElisaConstantRangeRef first,
                                                      ElisaConstantRangeRef second) {
  return wrap(new ConstantRange(unwrap(first)->intersectWith(*unwrap(second))));
}

int ElisaLLVMConstantRangeSignedMinBelow(ElisaConstantRangeRef range, LLVMValueRef constant) {
  return unwrap(range)->getSignedMin().slt(constantValue(constant));
}

int ElisaLLVMConstantRangeSignedMinAtMost(ElisaConstantRangeRef range, LLVMValueRef constant) {
  return unwrap(range)->getSignedMin().sle(constantValue(constant));
}

int ElisaLLVMConstantRangeIsEmpty(ElisaConstantRangeRef range) {
  return unwrap(range)->isEmptySet();
}

int ElisaLLVMConstantRangeReachesSignedMax(ElisaConstantRangeRef range) {
  return unwrap(range)->getSignedMax().isMaxSignedValue();
}

int ElisaLLVMConstantRangeSignedMinIsNegative(ElisaConstantRangeRef range) {
  return unwrap(range)->getSignedMin().isNegative();
}

int ElisaLLVMConstantRangeContains(ElisaConstantRangeRef range, uint64_t value) {
  return unwrap(range)->contains(APInt(unwrap(range)->getBitWidth(), value));
}

int ElisaLLVMConstantRangeUnsignedMaxAtMost(ElisaConstantRangeRef range, LLVMValueRef constant) {
  return unwrap(range)->getUnsignedMax().ule(constantValue(constant));
}

uint64_t ElisaLLVMConstantRangeUnsignedMax(ElisaConstantRangeRef range) {
  return unwrap(range)->getUnsignedMax().getLimitedValue();
}

ElisaConstantRangeRef ElisaLLVMConstantRangeCopy(ElisaConstantRangeRef range) {
  return wrap(new ConstantRange(*unwrap(range)));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeFromBounds(LLVMValueRef lower, LLVMValueRef upper) {
  return wrap(new ConstantRange(constantValue(lower), constantValue(upper)));
}

// The integer binary operators ConstantRange::binaryOp models; any other opcode has no
// integer range rule.
static std::optional<Instruction::BinaryOps> integerBinaryOperator(LLVMOpcode opcode) {
  switch (opcode) {
  case LLVMAdd: return Instruction::Add;
  case LLVMSub: return Instruction::Sub;
  case LLVMMul: return Instruction::Mul;
  case LLVMUDiv: return Instruction::UDiv;
  case LLVMSDiv: return Instruction::SDiv;
  case LLVMURem: return Instruction::URem;
  case LLVMSRem: return Instruction::SRem;
  case LLVMShl: return Instruction::Shl;
  case LLVMLShr: return Instruction::LShr;
  case LLVMAShr: return Instruction::AShr;
  case LLVMAnd: return Instruction::And;
  case LLVMOr: return Instruction::Or;
  case LLVMXor: return Instruction::Xor;
  default: return std::nullopt;
  }
}

ElisaConstantRangeRef ElisaLLVMConstantRangeBinaryOperation(LLVMOpcode opcode,
                                                           ElisaConstantRangeRef left,
                                                           ElisaConstantRangeRef right) {
  std::optional<Instruction::BinaryOps> Operator = integerBinaryOperator(opcode);
  if (!Operator) return wrap(new ConstantRange(ConstantRange::getFull(unwrap(left)->getBitWidth())));
  return wrap(new ConstantRange(unwrap(left)->binaryOp(*Operator, *unwrap(right))));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeSignedMultiplyFast(ElisaConstantRangeRef left,
                                                              ElisaConstantRangeRef right) {
  return wrap(new ConstantRange(unwrap(left)->smul_fast(*unwrap(right))));
}

int ElisaLLVMConstantRangeIsFull(ElisaConstantRangeRef range) {
  return unwrap(range)->isFullSet();
}

int ElisaLLVMConstantRangeIsWrapped(ElisaConstantRangeRef range) {
  return unwrap(range)->isWrappedSet();
}

int ElisaLLVMConstantRangeIsSingleElement(ElisaConstantRangeRef range) {
  return unwrap(range)->isSingleElement();
}

int ElisaLLVMConstantRangeIsAllNonNegative(ElisaConstantRangeRef range) {
  return unwrap(range)->isAllNonNegative();
}

int64_t ElisaLLVMConstantRangeSignedMin(ElisaConstantRangeRef range) {
  return unwrap(range)->getSignedMin().getSExtValue();
}

int64_t ElisaLLVMConstantRangeSignedMax(ElisaConstantRangeRef range) {
  return unwrap(range)->getSignedMax().getSExtValue();
}

LLVMValueRef ElisaLLVMConstantRangeSignedMinimum(ElisaConstantRangeRef range, LLVMContextRef context) {
  return wrap(ConstantInt::get(*unwrap(context), unwrap(range)->getSignedMin()));
}

LLVMValueRef ElisaLLVMConstantRangeSignedMaximum(ElisaConstantRangeRef range, LLVMContextRef context) {
  return wrap(ConstantInt::get(*unwrap(context), unwrap(range)->getSignedMax()));
}

uint64_t ElisaLLVMConstantRangeUnsignedMin(ElisaConstantRangeRef range) {
  return unwrap(range)->getUnsignedMin().getLimitedValue();
}

uint64_t ElisaLLVMConstantRangeLower(ElisaConstantRangeRef range) { return unwrap(range)->getLower().getZExtValue(); }

uint64_t ElisaLLVMConstantRangeUpper(ElisaConstantRangeRef range) { return unwrap(range)->getUpper().getZExtValue(); }

ElisaConstantRangeRef ElisaLLVMConstantRangeEmpty(uint32_t width) {
  return wrap(new ConstantRange(ConstantRange::getEmpty(width)));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeNonEmpty(LLVMValueRef lower, LLVMValueRef upper) {
  return wrap(new ConstantRange(ConstantRange::getNonEmpty(constantValue(lower), constantValue(upper))));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeIntersectUnsigned(ElisaConstantRangeRef first,
                                                              ElisaConstantRangeRef second) {
  return wrap(new ConstantRange(unwrap(first)->intersectWith(*unwrap(second), ConstantRange::Unsigned)));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeUnionUnsigned(ElisaConstantRangeRef first,
                                                          ElisaConstantRangeRef second) {
  return wrap(new ConstantRange(unwrap(first)->unionWith(*unwrap(second), ConstantRange::Unsigned)));
}

ElisaConstantRangeRef ElisaLLVMConstantRangeZeroExtend(ElisaConstantRangeRef range, uint32_t width) {
  return wrap(new ConstantRange(unwrap(range)->zeroExtend(width)));
}

uint32_t ElisaLLVMConstantRangeBitWidth(ElisaConstantRangeRef range) { return unwrap(range)->getBitWidth(); }

LLVMValueRef ElisaLLVMConstantRangeUnsignedMinimum(ElisaConstantRangeRef range, LLVMContextRef context) {
  return wrap(ConstantInt::get(*unwrap(context), unwrap(range)->getUnsignedMin()));
}

LLVMValueRef ElisaLLVMConstantRangeUnsignedMaximum(ElisaConstantRangeRef range, LLVMContextRef context) {
  return wrap(ConstantInt::get(*unwrap(context), unwrap(range)->getUnsignedMax()));
}

static LLVMValueRef constantOf(LLVMValueRef like, const APInt &Value) {
  return wrap(ConstantInt::get(cast<ConstantInt>(unwrap(like))->getContext(), Value));
}

LLVMValueRef ElisaLLVMConstantIntShiftLeft(LLVMValueRef constant, uint32_t amount) {
  return constantOf(constant, constantValue(constant).shl(amount));
}

LLVMValueRef ElisaLLVMConstantIntLogicalShiftRight(LLVMValueRef constant, uint32_t amount) {
  return constantOf(constant, constantValue(constant).lshr(amount));
}

LLVMValueRef ElisaLLVMConstantIntAnd(LLVMValueRef first, LLVMValueRef second) {
  return constantOf(first, constantValue(first) & constantValue(second));
}

LLVMValueRef ElisaLLVMConstantIntOr(LLVMValueRef first, LLVMValueRef second) {
  return constantOf(first, constantValue(first) | constantValue(second));
}

int ElisaLLVMConstantIntShiftLeftOverflows(LLVMValueRef constant, uint32_t amount) {
  bool Overflow = false;
  (void)constantValue(constant).ushl_ov(amount, Overflow);
  return Overflow;
}

int ElisaLLVMConstantIntMultiplyOverflows(LLVMValueRef first, LLVMValueRef second) {
  bool Overflow = false;
  (void)constantValue(first).umul_ov(constantValue(second), Overflow);
  return Overflow;
}

int ElisaLLVMConstantRangeSignedAddNeverOverflows(ElisaConstantRangeRef first, ElisaConstantRangeRef second) {
  return unwrap(first)->signedAddMayOverflow(*unwrap(second)) == ConstantRange::OverflowResult::NeverOverflows;
}

LLVMValueRef ElisaLLVMConstantIntSignExtend(LLVMValueRef constant, uint32_t width) {
  return constantOf(constant, constantValue(constant).sext(width));
}

LLVMValueRef ElisaLLVMConstantIntTruncate(LLVMValueRef constant, uint32_t width) {
  return constantOf(constant, constantValue(constant).trunc(width));
}

int ElisaLLVMConstantIntIsSignedIntN(LLVMValueRef constant, uint32_t bits) {
  return constantValue(constant).isSignedIntN(bits);
}

int ElisaLLVMConstantIntCompare(LLVMIntPredicate predicate, LLVMValueRef first, LLVMValueRef second) {
  return ICmpInst::compare(constantValue(first), constantValue(second),
                           static_cast<CmpInst::Predicate>(predicate));
}

LLVMValueRef ElisaLLVMConstantIntUnsignedDivide(LLVMValueRef first, LLVMValueRef second) {
  return constantOf(first, constantValue(first).udiv(constantValue(second)));
}

void ElisaLLVMDisposeConstantRange(ElisaConstantRangeRef range) { delete unwrap(range); }

} // extern "C"
