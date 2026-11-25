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

/* ConstantRange::makeSatisfyingICmpRegion(predicate, right).contains(left):
 * whether every value of LEFT compares true with every value of RIGHT. */
int ElisaLLVMConstantRangeSatisfiesCompare(LLVMIntPredicate predicate, ElisaConstantRangeRef left,
                                           ElisaConstantRangeRef right);
/* getConstantRangeFromMetadata of the instruction's `!range`; null without one. */
ElisaConstantRangeRef ElisaLLVMConstantRangeOfRangeMetadata(LLVMValueRef instruction);

/* ConstantRange::makeAllowedICmpRegion(predicate, range): every value `x` for
 * which `x <predicate> y` can hold for some `y` in RANGE. */
ElisaConstantRangeRef ElisaLLVMConstantRangeAllowedByCompareWith(LLVMIntPredicate predicate,
                                                                 ElisaConstantRangeRef range);

/* ConstantRange::sub with the single value `constant`: `range - constant`. */
ElisaConstantRangeRef ElisaLLVMConstantRangeSubtract(ElisaConstantRangeRef range,
                                                     LLVMValueRef constant);
/* ConstantRange::getFull(width): every value of the width. */
ElisaConstantRangeRef ElisaLLVMConstantRangeFull(uint32_t width);
/* ConstantRange(constant): the single value. */
ElisaConstantRangeRef ElisaLLVMConstantRangeOfConstant(LLVMValueRef constant);
/* ConstantRange::makeExactICmpRegion(predicate, constant): every value `x` for which
 * `x <predicate> constant` holds. */
ElisaConstantRangeRef ElisaLLVMConstantRangeExactByCompare(LLVMIntPredicate predicate,
                                                           LLVMValueRef constant);
/* ConstantRange::intersectWith(second), preferring the smallest range. */
ElisaConstantRangeRef ElisaLLVMConstantRangeIntersect(ElisaConstantRangeRef first,
                                                      ElisaConstantRangeRef second);
/* Whether getSignedMin() of the range is signed-less than the constant, of the same width. */
int ElisaLLVMConstantRangeSignedMinBelow(ElisaConstantRangeRef range, LLVMValueRef constant);
/* Whether getSignedMin() of the range is signed-at-most the constant, of the same width. */
int ElisaLLVMConstantRangeSignedMinAtMost(ElisaConstantRangeRef range, LLVMValueRef constant);
int ElisaLLVMConstantRangeIsEmpty(ElisaConstantRangeRef range);
/* Whether getSignedMax() of the range is the width's signed maximum. */
int ElisaLLVMConstantRangeReachesSignedMax(ElisaConstantRangeRef range);
/* Whether getSignedMin() of the range is negative. */
int ElisaLLVMConstantRangeSignedMinIsNegative(ElisaConstantRangeRef range);
/* ConstantRange::contains of `value` at the range's width. */
int ElisaLLVMConstantRangeContains(ElisaConstantRangeRef range, uint64_t value);
/* Whether getUnsignedMax() of the range is at most the constant, of the same width. */
int ElisaLLVMConstantRangeUnsignedMaxAtMost(ElisaConstantRangeRef range, LLVMValueRef constant);
/* getUnsignedMax() of the range as APInt::getLimitedValue: exact up to 64 bits, and
 * UINT64_MAX for a wider maximum that does not fit. */
uint64_t ElisaLLVMConstantRangeUnsignedMax(ElisaConstantRangeRef range);
/* A copy of the range, disposed separately. */
ElisaConstantRangeRef ElisaLLVMConstantRangeCopy(ElisaConstantRangeRef range);
/* ConstantRange(lower, upper): the wrapping interval [lower, upper) of two constants of
 * one width. */
ElisaConstantRangeRef ElisaLLVMConstantRangeFromBounds(LLVMValueRef lower, LLVMValueRef upper);
/* ConstantRange::binaryOp for an integer binary opcode (add, sub, mul, the divisions and
 * remainders, shifts and bitwise operators); the full range for any other opcode. */
ElisaConstantRangeRef ElisaLLVMConstantRangeBinaryOperation(LLVMOpcode opcode,
                                                           ElisaConstantRangeRef left,
                                                           ElisaConstantRangeRef right);
/* ConstantRange::smul_fast: the signed product, cheaply over-approximated. */
ElisaConstantRangeRef ElisaLLVMConstantRangeSignedMultiplyFast(ElisaConstantRangeRef left,
                                                              ElisaConstantRangeRef right);
int ElisaLLVMConstantRangeIsFull(ElisaConstantRangeRef range);
/* isWrappedSet(): the range wraps past the unsigned maximum (and is not full or empty). */
int ElisaLLVMConstantRangeIsWrapped(ElisaConstantRangeRef range);
/* isSingleElement(): the range holds exactly one value, of any width. */
int ElisaLLVMConstantRangeIsSingleElement(ElisaConstantRangeRef range);
int ElisaLLVMConstantRangeIsAllNonNegative(ElisaConstantRangeRef range);
int ElisaLLVMConstantRangeIsAllNegative(ElisaConstantRangeRef range);
/* getSignedMin() / getSignedMax() sign-extended; the range is at most 64 bits wide. */
int64_t ElisaLLVMConstantRangeSignedMin(ElisaConstantRangeRef range);
int64_t ElisaLLVMConstantRangeSignedMax(ElisaConstantRangeRef range);
/* getSignedMin() / getSignedMax() as ConstantInts of the range's width, any width. */
LLVMValueRef ElisaLLVMConstantRangeSignedMinimum(ElisaConstantRangeRef range, LLVMContextRef context);
LLVMValueRef ElisaLLVMConstantRangeSignedMaximum(ElisaConstantRangeRef range, LLVMContextRef context);
/* getUnsignedMin() as APInt::getLimitedValue. */
uint64_t ElisaLLVMConstantRangeUnsignedMin(ElisaConstantRangeRef range);
/* getLower() and getUpper() of a range at most 64 bits wide, zero-extended. */
uint64_t ElisaLLVMConstantRangeLower(ElisaConstantRangeRef range);
uint64_t ElisaLLVMConstantRangeUpper(ElisaConstantRangeRef range);
/* getLower() and getUpper() as constants of the range's width, at any width. */
LLVMValueRef ElisaLLVMConstantRangeLowerBound(ElisaConstantRangeRef range, LLVMContextRef context);
LLVMValueRef ElisaLLVMConstantRangeUpperBound(ElisaConstantRangeRef range, LLVMContextRef context);
/* getEmpty(width) and getNonEmpty(lower, upper): the full range when lower == upper. */
ElisaConstantRangeRef ElisaLLVMConstantRangeEmpty(uint32_t width);
ElisaConstantRangeRef ElisaLLVMConstantRangeNonEmpty(LLVMValueRef lower, LLVMValueRef upper);
/* intersectWith and unionWith, preferring the smaller unsigned range. */
ElisaConstantRangeRef ElisaLLVMConstantRangeIntersectUnsigned(ElisaConstantRangeRef first, ElisaConstantRangeRef second);
ElisaConstantRangeRef ElisaLLVMConstantRangeUnionUnsigned(ElisaConstantRangeRef first, ElisaConstantRangeRef second);
/* zeroExtend(width). */
ElisaConstantRangeRef ElisaLLVMConstantRangeZeroExtend(ElisaConstantRangeRef range, uint32_t width);
uint32_t ElisaLLVMConstantRangeBitWidth(ElisaConstantRangeRef range);
/* getUnsignedMin() / getUnsignedMax() as ConstantInts of the range's width, any width. */
LLVMValueRef ElisaLLVMConstantRangeUnsignedMinimum(ElisaConstantRangeRef range, LLVMContextRef context);
LLVMValueRef ElisaLLVMConstantRangeUnsignedMaximum(ElisaConstantRangeRef range, LLVMContextRef context);
/* APInt operations on ConstantInts of any width, which the C API's constant
 * expressions no longer fold: shl and lshr by AMOUNT (below the width), and, or,
 * and whether ushl_ov / umul_ov overflow. */
LLVMValueRef ElisaLLVMConstantIntShiftLeft(LLVMValueRef constant, uint32_t amount);
LLVMValueRef ElisaLLVMConstantIntLogicalShiftRight(LLVMValueRef constant, uint32_t amount);
LLVMValueRef ElisaLLVMConstantIntAnd(LLVMValueRef first, LLVMValueRef second);
LLVMValueRef ElisaLLVMConstantIntOr(LLVMValueRef first, LLVMValueRef second);
int ElisaLLVMConstantIntShiftLeftOverflows(LLVMValueRef constant, uint32_t amount);
int ElisaLLVMConstantIntMultiplyOverflows(LLVMValueRef first, LLVMValueRef second);
/* signedAddMayOverflow(second) == NeverOverflows. */
int ElisaLLVMConstantRangeSignedAddNeverOverflows(ElisaConstantRangeRef first, ElisaConstantRangeRef second);
/* Whether FIRST OPCODE SECOND never overflows, signed when IS_SIGNED: the add and sub
 * tests of either kind and unsignedMulMayOverflow. 0 for any other operation. */
int ElisaLLVMConstantRangeNeverOverflows(LLVMOpcode opcode, int is_signed, ElisaConstantRangeRef first,
                                         ElisaConstantRangeRef second);
/* APInt sext / trunc to WIDTH, and isSignedIntN(bits), on ConstantInts. */
LLVMValueRef ElisaLLVMConstantIntSignExtend(LLVMValueRef constant, uint32_t width);
LLVMValueRef ElisaLLVMConstantIntTruncate(LLVMValueRef constant, uint32_t width);
int ElisaLLVMConstantIntIsSignedIntN(LLVMValueRef constant, uint32_t bits);
/* ICmpInst::compare(first, second, predicate) and the unsigned quotient, on
 * ConstantInts of one width (elisa_llvm_analysis has the active bits and product). */
int ElisaLLVMConstantIntCompare(LLVMIntPredicate predicate, LLVMValueRef first, LLVMValueRef second);
LLVMValueRef ElisaLLVMConstantIntUnsignedDivide(LLVMValueRef first, LLVMValueRef second);
/* APInt::sdiv and APInt::srem on ConstantInts of one width (second nonzero). */
LLVMValueRef ElisaLLVMConstantIntSignedDivide(LLVMValueRef first, LLVMValueRef second);
LLVMValueRef ElisaLLVMConstantIntSignedRemainder(LLVMValueRef first, LLVMValueRef second);
/* intersectWith and unionWith preferring the smaller signed range, and unionWith
 * preferring the smallest range. */
ElisaConstantRangeRef ElisaLLVMConstantRangeIntersectSigned(ElisaConstantRangeRef first, ElisaConstantRangeRef second);
ElisaConstantRangeRef ElisaLLVMConstantRangeUnionSigned(ElisaConstantRangeRef first, ElisaConstantRangeRef second);
ElisaConstantRangeRef ElisaLLVMConstantRangeUnion(ElisaConstantRangeRef first, ElisaConstantRangeRef second);
/* ConstantRange::inverse, isSignWrappedSet, and icmp(predicate, right): whether every
 * pair of values compares true. */
ElisaConstantRangeRef ElisaLLVMConstantRangeInverse(ElisaConstantRangeRef range);
int ElisaLLVMConstantRangeIsSignWrapped(ElisaConstantRangeRef range);
int ElisaLLVMConstantRangeComparesTrue(LLVMIntPredicate predicate, ElisaConstantRangeRef left,
                                       ElisaConstantRangeRef right);
/* castOp(opcode, width) for trunc, zext and sext (the full range for any other opcode),
 * and signExtend(width). */
ElisaConstantRangeRef ElisaLLVMConstantRangeCast(LLVMOpcode opcode, ElisaConstantRangeRef range, uint32_t width);
ElisaConstantRangeRef ElisaLLVMConstantRangeSignExtend(ElisaConstantRangeRef range, uint32_t width);
/* umin, umax, smin or smax of two ranges of one width, by `extremum`: 0, 1, 2 or 3. */
ElisaConstantRangeRef ElisaLLVMConstantRangeExtremum(uint32_t extremum, ElisaConstantRangeRef left,
                                                     ElisaConstantRangeRef right);
/* APIntOps::RoundingUDiv(first, second, Rounding::UP) on ConstantInts of one width. */
LLVMValueRef ElisaLLVMConstantIntUnsignedDivideRoundingUp(LLVMValueRef first, LLVMValueRef second);
/* range.addWithNoWrap(ConstantRange(constant), NoUnsignedWrap): the sums that do not wrap. */
ElisaConstantRangeRef ElisaLLVMConstantRangeAddNoUnsignedWrap(ElisaConstantRangeRef range, LLVMValueRef constant);
void ElisaLLVMDisposeConstantRange(ElisaConstantRangeRef range);

#ifdef __cplusplus
}
#endif

#endif
