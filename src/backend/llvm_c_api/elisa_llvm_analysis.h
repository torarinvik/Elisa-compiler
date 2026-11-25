/* C API for the LLVM analyses the Elisa-hosted passes need and LLVM's own
 * C API does not offer: dominator trees, loop nests, scalar evolution and
 * the value facts of llvm/Analysis/ValueTracking.h.
 *
 * One `ElisaFunctionAnalysesRef` owns every analysis of one function. The
 * analyses describe the function as it was when they were built (or last
 * invalidated); a pass that edits the IR calls
 * `ElisaLLVMInvalidateFunctionAnalyses` before querying again.
 */
#ifndef ELISA_LLVM_ANALYSIS_H
#define ELISA_LLVM_ANALYSIS_H

#include <llvm-c/Core.h>
#include <llvm-c/TargetMachine.h>

#include "elisa_llvm_constant_range.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ElisaOpaqueFunctionAnalyses *ElisaFunctionAnalysesRef;
typedef struct ElisaOpaqueLoop *ElisaLoopRef;

/* --- analysis lifetime ------------------------------------------------ */
ElisaFunctionAnalysesRef ElisaLLVMCreateFunctionAnalyses(LLVMValueRef function);
void ElisaLLVMDisposeFunctionAnalyses(ElisaFunctionAnalysesRef analyses);
void ElisaLLVMInvalidateFunctionAnalyses(ElisaFunctionAnalysesRef analyses);
/* Drops the lazy value info, scalar evolution and assumption cache, keeping the
 * dominator tree and loop info: the next query builds them fresh, as a pass that
 * constructs them per query sees the instructions it has rewritten since. */
void ElisaLLVMForgetValueAnalyses(ElisaFunctionAnalysesRef analyses);

/* --- dominance -------------------------------------------------------- */
int ElisaLLVMBlockDominates(ElisaFunctionAnalysesRef analyses, LLVMBasicBlockRef dominator,
                            LLVMBasicBlockRef dominated);
int ElisaLLVMInstructionDominates(ElisaFunctionAnalysesRef analyses, LLVMValueRef definition,
                                  LLVMValueRef user);
LLVMBasicBlockRef ElisaLLVMImmediateDominator(ElisaFunctionAnalysesRef analyses,
                                              LLVMBasicBlockRef block);
/* DominatorTree::dominates(BasicBlockEdge(from, to), use): every path to
 * `use` takes the edge from `from` to its successor `to`. */
int ElisaLLVMEdgeDominates(ElisaFunctionAnalysesRef analyses, LLVMBasicBlockRef from,
                           LLVMBasicBlockRef to, LLVMBasicBlockRef use);

/* --- loops (preorder: every loop precedes the loops nested in it) ------ */
uint32_t ElisaLLVMLoopCount(ElisaFunctionAnalysesRef analyses);
ElisaLoopRef ElisaLLVMLoopAt(ElisaFunctionAnalysesRef analyses, uint32_t index);
ElisaLoopRef ElisaLLVMLoopForBlock(ElisaFunctionAnalysesRef analyses, LLVMBasicBlockRef block);
ElisaLoopRef ElisaLLVMLoopParent(ElisaLoopRef loop);
uint32_t ElisaLLVMLoopDepth(ElisaLoopRef loop);
uint32_t ElisaLLVMLoopSubLoopCount(ElisaLoopRef loop);
uint32_t ElisaLLVMLoopBlockCount(ElisaLoopRef loop);
LLVMBasicBlockRef ElisaLLVMLoopBlockAt(ElisaLoopRef loop, uint32_t index);
int ElisaLLVMLoopContainsBlock(ElisaLoopRef loop, LLVMBasicBlockRef block);
LLVMBasicBlockRef ElisaLLVMLoopHeader(ElisaLoopRef loop);
LLVMBasicBlockRef ElisaLLVMLoopLatch(ElisaLoopRef loop);
LLVMBasicBlockRef ElisaLLVMLoopPreheader(ElisaLoopRef loop);
LLVMBasicBlockRef ElisaLLVMLoopPredecessor(ElisaLoopRef loop);
int ElisaLLVMLoopIsInvariant(ElisaLoopRef loop, LLVMValueRef value);
LLVMMetadataRef ElisaLLVMLoopGetLoopID(ElisaLoopRef loop);
void ElisaLLVMLoopSetLoopID(ElisaLoopRef loop, LLVMMetadataRef loop_id);

/* A distinct loop ID `!{self, properties...}`, as loop metadata requires. */
LLVMMetadataRef ElisaLLVMCreateLoopID(LLVMContextRef context, LLVMMetadataRef *properties,
                                      uint32_t count);

/* --- target triple ------------------------------------------------------ */
/* Triple::isAArch64(): any AArch64 architecture, including big-endian and
 * ILP32. */
int ElisaLLVMModuleTargetIsAArch64(LLVMModuleRef module);
/* Triple::getArch() == Triple::aarch64: little-endian 64-bit AArch64 only. */
int ElisaLLVMModuleTargetArchIsAArch64(LLVMModuleRef module);
/* Triple::isOSDarwin(). */
int ElisaLLVMModuleTargetIsDarwin(LLVMModuleRef module);
/* Triple::isOSLinux(). */
int ElisaLLVMModuleTargetIsLinux(LLVMModuleRef module);
/* Triple::isMacOSX(). */
int ElisaLLVMModuleTargetIsMacOSX(LLVMModuleRef module);
/* The same queries on a target machine's triple. */
int ElisaLLVMTargetMachineIsAArch64(LLVMTargetMachineRef machine);
int ElisaLLVMTargetMachineIsMacOSX(LLVMTargetMachineRef machine);
/* MCSubtargetInfo::checkFeatures for the machine's CPU and features, for example "+cssc". */
int ElisaLLVMTargetMachineChecksFeatures(LLVMTargetMachineRef machine, const char *features);

/* --- IR facts the C API lacks ------------------------------------------ */
/* Whether a `blockaddress` constant refers to the block. */
int ElisaLLVMBlockHasAddressTaken(LLVMBasicBlockRef block);
/* Whether the instruction carries metadata other than its debug location. */
int ElisaLLVMHasMetadataOtherThanDebugLoc(LLVMValueRef instruction);
/* llvm::FindInsertedValue(aggregate, {index}): the value inserted at the top-level
 * index, or null when it is not known (or the value is not a struct or array). */
LLVMValueRef ElisaLLVMFindInsertedValue(LLVMValueRef aggregate, uint32_t index);
/* GlobalVariable::hasDefinitiveInitializer: an initializer no other definition can replace. */
int ElisaLLVMGlobalHasDefinitiveInitializer(LLVMValueRef global);
/* PatternMatch's m_One() and m_Zero(): an integer constant, or a vector
 * of them (a splat, or lanes that are all the value or poison). */
int ElisaLLVMIsConstantOne(LLVMValueRef value);
int ElisaLLVMIsConstantZero(LLVMValueRef value);
/* PatternMatch's m_SpecificInt(value): an integer constant, or a splat vector of
 * one, equal to `value` at any width. */
int ElisaLLVMIsSpecificInt(LLVMValueRef value, uint64_t expected);
/* Instruction::mayHaveSideEffects. */
int ElisaLLVMMayHaveSideEffects(LLVMValueRef instruction);
/* Instruction::mayReadOrWriteMemory. */
int ElisaLLVMMayReadOrWriteMemory(LLVMValueRef instruction);
/* Value::stripPointerCasts: the value with pointer casts and zero GEPs removed. */
LLVMValueRef ElisaLLVMStripPointerCasts(LLVMValueRef value);
/* Instruction::mayReadFromMemory. */
int ElisaLLVMMayReadFromMemory(LLVMValueRef instruction);
/* llvm::getUnderlyingObjects(pointer, objects, no loop info, no lookup limit) found at
 * least one object, and every one is an alloca. */
int ElisaLLVMUnderlyingObjectsAreAllocas(LLVMValueRef pointer);
/* GetPointerBaseWithConstantOffset under the module's data layout: the base, with the byte
 * offset stored through `offset`. */
LLVMValueRef ElisaLLVMPointerBaseWithConstantOffset(LLVMValueRef pointer, LLVMModuleRef module,
                                                    int64_t *offset);
/* AllocaInst::isStaticAlloca, isUsedWithInAlloca and isSwiftError. */
int ElisaLLVMIsStaticAlloca(LLVMValueRef alloca);
int ElisaLLVMAllocaIsUsedWithInAlloca(LLVMValueRef alloca);
int ElisaLLVMAllocaIsSwiftError(LLVMValueRef alloca);
/* Byte INDEX (little-endian order) of a ConstantInt of any width. */
unsigned ElisaLLVMConstantIntByte(LLVMValueRef constant, unsigned index);
/* BasicBlock::getNumber: the block's number, below its function's
 * ElisaLLVMFunctionMaxBlockNumber, for indexing per-block arrays. */
unsigned ElisaLLVMBlockNumber(LLVMBasicBlockRef block);
/* Function::getMaxBlockNumber. */
unsigned ElisaLLVMFunctionMaxBlockNumber(LLVMValueRef function);
/* CallBase::hasFnAttr(kind): the call site or its callee has the function
 * attribute; `kind` is an enum attribute kind (LLVMGetEnumAttributeKindForName). */
int ElisaLLVMCallHasFunctionAttribute(LLVMValueRef call, unsigned kind);
/* isa<MemIntrinsic>: a call of llvm.memcpy, memmove, memset or their inline forms. */
int ElisaLLVMIsMemIntrinsic(LLVMValueRef value);
/* isa<MemSetInst>: a call of llvm.memset or llvm.memset.inline. */
int ElisaLLVMIsMemSet(LLVMValueRef value);
/* Value::isUsedByMetadata. */
int ElisaLLVMIsUsedByMetadata(LLVMValueRef value);
/* DataLayout::getIndexSizeInBits of the module's layout for the address space. */
uint32_t ElisaLLVMDataLayoutIndexSizeInBits(LLVMModuleRef module, uint32_t address_space);
/* APInt::slt of two ConstantInt values of the same width. */
int ElisaLLVMConstantIntSignedLess(LLVMValueRef first, LLVMValueRef second);
/* containsIrreducibleCFG over a reverse post-order of the function and its loops. */
int ElisaLLVMFunctionHasIrreducibleControlFlow(ElisaFunctionAnalysesRef analyses);
/* llvm::getUnderlyingObject(value) with its default lookup limit of 6. */
LLVMValueRef ElisaLLVMUnderlyingObject(LLVMValueRef value);
/* BasicBlock::isEHPad. */
int ElisaLLVMBlockIsEHPad(LLVMBasicBlockRef block);
/* Use::getOperandNo: the use's operand index in its user. */
unsigned ElisaLLVMUseOperandNumber(LLVMUseRef use);
/* CallBase::doesNotAccessMemory. */
int ElisaLLVMCallDoesNotAccessMemory(LLVMValueRef call);
/* Whether Function::getEntryCount() has a value (a profile entry count). */
int ElisaLLVMFunctionHasEntryCount(LLVMValueRef function);
/* The sign bit of an integer constant of any width. */
int ElisaLLVMConstantIntIsNegative(LLVMValueRef constant);
/* A ConstantInt that is a positive power of two, at any width. */
int ElisaLLVMConstantIntIsPositivePowerOfTwo(LLVMValueRef constant);
/* ConstantInt::equalsInt: whether the constant's value, at any width, is `value`. */
int ElisaLLVMConstantIntEquals(LLVMValueRef constant, uint64_t value);
/* APInt::getActiveBits of a ConstantInt: the bits up to its highest set bit. */
unsigned ElisaLLVMConstantIntActiveBits(LLVMValueRef constant);
/* The width of a ConstantInt that is a low-bit mask (APInt::isMask: 2^n - 1, n >= 1), else 0. */
unsigned ElisaLLVMConstantIntMaskWidth(LLVMValueRef constant);
/* APInt::ugt of two ConstantInts of one width. */
int ElisaLLVMConstantIntUnsignedGreater(LLVMValueRef first, LLVMValueRef second);
/* APInt::countr_zero of a ConstantInt: its trailing zero bits (the width for 0). */
unsigned ElisaLLVMConstantIntTrailingZeros(LLVMValueRef constant);
/* The ConstantInt shifted right past its trailing zeros, of the same type. */
LLVMValueRef ElisaLLVMConstantIntOddPart(LLVMValueRef constant);
/* APInt::getLowBitsSet(width of `type`, bits) as a ConstantInt of the integer `type`. */
LLVMValueRef ElisaLLVMConstantIntLowBits(LLVMTypeRef type, unsigned bits);
/* Whether two ConstantInts of one width agree in their low `bits` bits. */
int ElisaLLVMConstantIntsAgreeInLowBits(LLVMValueRef first, LLVMValueRef second, unsigned bits);
/* A floating-point constant that is negative, finite and not zero. */
int ElisaLLVMConstantFloatIsNegativeFiniteNonzero(LLVMValueRef constant);
/* The product of two ConstantInts of one width, wrapping (APInt::operator*). */
LLVMValueRef ElisaLLVMConstantIntMultiply(LLVMValueRef left, LLVMValueRef right);
/* The IEEE bits of a `double` ConstantFP (APFloat::bitcastToAPInt). */
uint64_t ElisaLLVMConstantDoubleBits(LLVMValueRef constant);
/* Whether some strongly connected component of the function's control flow graph has a
 * cycle (scc_iterator::hasCycle): a loop or a self-edge. */
int ElisaLLVMFunctionHasCycle(LLVMValueRef function);
/* The FPClassTest bits of a ConstantFP's value (APFloat::classify): 1 signaling NaN,
 * 2 quiet NaN, 4 -inf, 8 -normal, 16 -subnormal, 32 -0, 64 +0, 128 +subnormal,
 * 256 +normal, 512 +inf. */
unsigned ElisaLLVMConstantFloatClass(LLVMValueRef constant);
/* computeKnownFPClass of `value` at the instruction `context`, with the dominator tree and
 * no library info or assumption cache, as facts: 1 never NaN, 2 never infinite or NaN,
 * 4 never NaN or negative (isKnownNever(fcNan | fcNegative)). */
unsigned ElisaLLVMKnownFPClassFacts(ElisaFunctionAnalysesRef analyses, LLVMValueRef value,
                                    LLVMValueRef context);
/* DominatorTree::isReachableFromEntry: the block has a dominator tree node. */
int ElisaLLVMIsReachableFromEntry(ElisaFunctionAnalysesRef analyses, LLVMBasicBlockRef block);
/* TargetLibraryInfo::getLibFunc(call) names the library function `name`, and the target
 * has it (TargetLibraryInfo::has). */
int ElisaLLVMCallIsAvailableLibFunction(ElisaFunctionAnalysesRef analyses, LLVMValueRef call,
                                        const char *name);
/* CallBase::isNoBuiltin: `nobuiltin` on the call site or callee without `builtin`. */
int ElisaLLVMCallIsNoBuiltin(LLVMValueRef call);
/* llvm::isGuaranteedNotToBeUndefOrPoison with no context instruction. */
int ElisaLLVMIsGuaranteedNotToBeUndefOrPoison(LLVMValueRef value);
/* llvm::isGuaranteedNotToBeUndefOrPoison at the instruction `context`, with the dominator
 * tree and no assumption cache. */
int ElisaLLVMIsGuaranteedNotToBeUndefOrPoisonAt(ElisaFunctionAnalysesRef analyses, LLVMValueRef value,
                                                LLVMValueRef context);
/* LazyValueInfo::getConstantRange of `value` at the instruction `context`. The caller
 * disposes the range with ElisaLLVMDisposeConstantRange. */
ElisaConstantRangeRef ElisaLLVMLazyValueConstantRange(ElisaFunctionAnalysesRef analyses, LLVMValueRef value,
                                                      LLVMValueRef context, int undef_allowed);
/* llvm::isGuaranteedNotToBeUndefOrPoison at the instruction `context`, with the
 * analyses' assumption cache and dominator tree. */
int ElisaLLVMIsGuaranteedNotToBeUndefOrPoisonAssuming(ElisaFunctionAnalysesRef analyses,
                                                      LLVMValueRef value, LLVMValueRef context);
/* LazyValueInfo::getConstantRangeOnEdge of `value` on the edge from -> to, asked at the
 * instruction `context`, or with no context instruction when it is null. */
ElisaConstantRangeRef ElisaLLVMLazyValueConstantRangeOnEdge(ElisaFunctionAnalysesRef analyses,
                                                            LLVMValueRef value, LLVMBasicBlockRef from,
                                                            LLVMBasicBlockRef to, LLVMValueRef context);
/* LazyValueInfo::getConstantRangeAtUse of operand `operand_index` of `user`. */
ElisaConstantRangeRef ElisaLLVMLazyValueConstantRangeAtUse(ElisaFunctionAnalysesRef analyses,
                                                           LLVMValueRef user, uint32_t operand_index,
                                                           int undef_allowed);
/* llvm::isImpliedCondition with the module's data layout: whether `condition` being
 * `condition_is_true` decides `implied`. 1 implied true, 0 implied false, -1 unknown. */
int ElisaLLVMIsImpliedCondition(LLVMValueRef condition, LLVMValueRef implied, LLVMModuleRef module,
                                int condition_is_true);

/* --- scalar evolution --------------------------------------------------- */
/* The constant maximum backedge-taken count of the loop; returns 0 when it
 * is not a constant of at most 64 bits. */
int ElisaLLVMConstantMaxBackedgeTakenCount(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop,
                                           uint64_t *count);
/* APInt::getActiveBits of the unsigned range maximum scalar evolution proves for an
 * integer value; 0 for a value scalar evolution cannot describe. */
unsigned ElisaLLVMScalarEvolutionUnsignedMaxActiveBits(ElisaFunctionAnalysesRef analyses,
                                                      LLVMValueRef value);
/* ScalarEvolution::getSignedRange(getSCEV(value)) of an integer value. */
ElisaConstantRangeRef ElisaLLVMScalarEvolutionSignedRange(ElisaFunctionAnalysesRef analyses,
                                                          LLVMValueRef value);
/* ScalarEvolution::getSmallConstantTripCount(loop, exiting): the exact trip count of the
 * loop through the exiting block, 0 when unknown or wider than 32 bits. */
uint32_t ElisaLLVMSmallConstantTripCount(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop,
                                         LLVMBasicBlockRef exiting);
/* ScalarEvolution::getSmallConstantMaxTripCount(loop): 0 when unknown. */
uint32_t ElisaLLVMSmallConstantMaxTripCount(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop);

#ifdef __cplusplus
}
#endif
#endif
