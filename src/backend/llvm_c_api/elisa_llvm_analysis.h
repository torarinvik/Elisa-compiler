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

/* --- IR facts the C API lacks ------------------------------------------ */
/* Whether a `blockaddress` constant refers to the block. */
int ElisaLLVMBlockHasAddressTaken(LLVMBasicBlockRef block);
/* Whether the instruction carries metadata other than its debug location. */
int ElisaLLVMHasMetadataOtherThanDebugLoc(LLVMValueRef instruction);
/* PatternMatch's m_One() and m_Zero(): an integer constant, or a vector
 * of them (a splat, or lanes that are all the value or poison). */
int ElisaLLVMIsConstantOne(LLVMValueRef value);
int ElisaLLVMIsConstantZero(LLVMValueRef value);
/* PatternMatch's m_SpecificInt(value): an integer constant, or a splat vector of
 * one, equal to `value` at any width. */
int ElisaLLVMIsSpecificInt(LLVMValueRef value, uint64_t expected);
/* Instruction::mayHaveSideEffects. */
int ElisaLLVMMayHaveSideEffects(LLVMValueRef instruction);
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
/* A floating-point constant that is negative, finite and not zero. */
int ElisaLLVMConstantFloatIsNegativeFiniteNonzero(LLVMValueRef constant);
/* llvm::isGuaranteedNotToBeUndefOrPoison with no context instruction. */
int ElisaLLVMIsGuaranteedNotToBeUndefOrPoison(LLVMValueRef value);

/* --- scalar evolution --------------------------------------------------- */
/* The constant maximum backedge-taken count of the loop; returns 0 when it
 * is not a constant of at most 64 bits. */
int ElisaLLVMConstantMaxBackedgeTakenCount(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop,
                                           uint64_t *count);

#ifdef __cplusplus
}
#endif
#endif
