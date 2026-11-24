// Implementation of elisa_llvm_analysis.h over LLVM's C++ analyses.
#include "elisa_llvm_analysis.h"
#include "elisa_llvm_function_analyses.h"

#include <llvm/ADT/PostOrderIterator.h>
#include <llvm/Analysis/AssumptionCache.h>
#include <llvm/Analysis/CFG.h>
#include <llvm/Analysis/LazyValueInfo.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/Analysis/ScalarEvolution.h>
#include <llvm/Analysis/ScalarEvolutionExpressions.h>
#include <llvm/Analysis/TargetLibraryInfo.h>
#include <llvm/Analysis/ValueTracking.h>
#include <llvm/IR/ConstantRange.h>
#include <llvm/IR/Constants.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/InstrTypes.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/IR/Function.h>
#include <llvm/IR/Metadata.h>
#include <llvm/IR/Module.h>
#include <llvm/IR/PatternMatch.h>
#include <llvm/MC/MCSubtargetInfo.h>
#include <llvm/MC/TargetRegistry.h>
#include <llvm/Target/TargetMachine.h>
#include <llvm/TargetParser/Triple.h>

#include <memory>
#include <optional>
#include <vector>

using namespace llvm;

using namespace elisa_llvm;

extern "C" {

ElisaFunctionAnalysesRef ElisaLLVMCreateFunctionAnalyses(LLVMValueRef function) {
  auto *F = dyn_cast_or_null<Function>(unwrap(function));
  if (!F || F->isDeclaration()) return nullptr;
  return reinterpret_cast<ElisaFunctionAnalysesRef>(new FunctionAnalyses(*F));
}

void ElisaLLVMDisposeFunctionAnalyses(ElisaFunctionAnalysesRef analyses) {
  delete unwrapAnalyses(analyses);
}

void ElisaLLVMInvalidateFunctionAnalyses(ElisaFunctionAnalysesRef analyses) {
  unwrapAnalyses(analyses)->build();
}

void ElisaLLVMForgetValueAnalyses(ElisaFunctionAnalysesRef analyses) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  A->lazyValues.reset();
  A->evolution.reset();
  A->assumptions.reset();
}

int ElisaLLVMBlockDominates(ElisaFunctionAnalysesRef analyses, LLVMBasicBlockRef dominator,
                            LLVMBasicBlockRef dominated) {
  return unwrapAnalyses(analyses)->dominators->dominates(unwrap(dominator), unwrap(dominated));
}

int ElisaLLVMInstructionDominates(ElisaFunctionAnalysesRef analyses, LLVMValueRef definition,
                                  LLVMValueRef user) {
  auto *Use = dyn_cast<Instruction>(unwrap(user));
  return Use && unwrapAnalyses(analyses)->dominators->dominates(unwrap(definition), Use);
}

LLVMBasicBlockRef ElisaLLVMImmediateDominator(ElisaFunctionAnalysesRef analyses,
                                              LLVMBasicBlockRef block) {
  DomTreeNode *Node = unwrapAnalyses(analyses)->dominators->getNode(unwrap(block));
  return Node && Node->getIDom() ? wrap(Node->getIDom()->getBlock()) : nullptr;
}

int ElisaLLVMEdgeDominates(ElisaFunctionAnalysesRef analyses, LLVMBasicBlockRef from,
                           LLVMBasicBlockRef to, LLVMBasicBlockRef use) {
  return unwrapAnalyses(analyses)->dominators->dominates(
      BasicBlockEdge(unwrap(from), unwrap(to)), unwrap(use));
}

uint32_t ElisaLLVMLoopCount(ElisaFunctionAnalysesRef analyses) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  A->loops();
  return A->preorder.size();
}

ElisaLoopRef ElisaLLVMLoopAt(ElisaFunctionAnalysesRef analyses, uint32_t index) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  A->loops();
  return index < A->preorder.size() ? wrapLoop(A->preorder[index]) : nullptr;
}

ElisaLoopRef ElisaLLVMLoopForBlock(ElisaFunctionAnalysesRef analyses, LLVMBasicBlockRef block) {
  return wrapLoop(unwrapAnalyses(analyses)->loops().getLoopFor(unwrap(block)));
}

ElisaLoopRef ElisaLLVMLoopParent(ElisaLoopRef loop) {
  return wrapLoop(unwrapLoop(loop)->getParentLoop());
}

uint32_t ElisaLLVMLoopDepth(ElisaLoopRef loop) { return unwrapLoop(loop)->getLoopDepth(); }

uint32_t ElisaLLVMLoopSubLoopCount(ElisaLoopRef loop) {
  return unwrapLoop(loop)->getSubLoops().size();
}

uint32_t ElisaLLVMLoopBlockCount(ElisaLoopRef loop) { return unwrapLoop(loop)->getNumBlocks(); }

LLVMBasicBlockRef ElisaLLVMLoopBlockAt(ElisaLoopRef loop, uint32_t index) {
  auto Blocks = unwrapLoop(loop)->getBlocks();
  return index < Blocks.size() ? wrap(Blocks[index]) : nullptr;
}

int ElisaLLVMLoopContainsBlock(ElisaLoopRef loop, LLVMBasicBlockRef block) {
  return unwrapLoop(loop)->contains(unwrap(block));
}

LLVMBasicBlockRef ElisaLLVMLoopHeader(ElisaLoopRef loop) {
  return wrap(unwrapLoop(loop)->getHeader());
}

LLVMBasicBlockRef ElisaLLVMLoopLatch(ElisaLoopRef loop) {
  return wrap(unwrapLoop(loop)->getLoopLatch());
}

LLVMBasicBlockRef ElisaLLVMLoopPreheader(ElisaLoopRef loop) {
  return wrap(unwrapLoop(loop)->getLoopPreheader());
}

LLVMBasicBlockRef ElisaLLVMLoopPredecessor(ElisaLoopRef loop) {
  return wrap(unwrapLoop(loop)->getLoopPredecessor());
}

int ElisaLLVMLoopIsInvariant(ElisaLoopRef loop, LLVMValueRef value) {
  return unwrapLoop(loop)->isLoopInvariant(unwrap(value));
}

LLVMMetadataRef ElisaLLVMLoopGetLoopID(ElisaLoopRef loop) {
  return wrap(unwrapLoop(loop)->getLoopID());
}

void ElisaLLVMLoopSetLoopID(ElisaLoopRef loop, LLVMMetadataRef loop_id) {
  unwrapLoop(loop)->setLoopID(cast<MDNode>(unwrap(loop_id)));
}

LLVMMetadataRef ElisaLLVMCreateLoopID(LLVMContextRef context, LLVMMetadataRef *properties,
                                      uint32_t count) {
  SmallVector<Metadata *, 4> Entries{nullptr};
  for (uint32_t I = 0; I < count; ++I) Entries.push_back(unwrap(properties[I]));
  MDNode *ID = MDNode::getDistinct(*unwrap(context), Entries);
  ID->replaceOperandWith(0, ID);
  return wrap(ID);
}

int ElisaLLVMModuleTargetIsAArch64(LLVMModuleRef module) {
  return unwrap(module)->getTargetTriple().isAArch64();
}

int ElisaLLVMModuleTargetIsMacOSX(LLVMModuleRef module) {
  return unwrap(module)->getTargetTriple().isMacOSX();
}

static const TargetMachine &unwrapMachine(LLVMTargetMachineRef machine) {
  return *reinterpret_cast<const TargetMachine *>(machine);
}

int ElisaLLVMTargetMachineIsAArch64(LLVMTargetMachineRef machine) {
  return unwrapMachine(machine).getTargetTriple().isAArch64();
}

int ElisaLLVMTargetMachineIsMacOSX(LLVMTargetMachineRef machine) {
  return unwrapMachine(machine).getTargetTriple().isMacOSX();
}

int ElisaLLVMTargetMachineChecksFeatures(LLVMTargetMachineRef machine, const char *features) {
  const TargetMachine &TM = unwrapMachine(machine);
  std::unique_ptr<MCSubtargetInfo> subtarget(TM.getTarget().createMCSubtargetInfo(
      TM.getTargetTriple(), TM.getTargetCPU(), TM.getTargetFeatureString()));
  return subtarget && subtarget->checkFeatures(features);
}

int ElisaLLVMModuleTargetArchIsAArch64(LLVMModuleRef module) {
  return unwrap(module)->getTargetTriple().getArch() == Triple::aarch64;
}

int ElisaLLVMModuleTargetIsDarwin(LLVMModuleRef module) {
  return unwrap(module)->getTargetTriple().isOSDarwin();
}

int ElisaLLVMModuleTargetIsLinux(LLVMModuleRef module) {
  return unwrap(module)->getTargetTriple().isOSLinux();
}

int ElisaLLVMBlockHasAddressTaken(LLVMBasicBlockRef block) {
  return unwrap(block)->hasAddressTaken();
}

int ElisaLLVMHasMetadataOtherThanDebugLoc(LLVMValueRef instruction) {
  return cast<Instruction>(unwrap(instruction))->hasMetadataOtherThanDebugLoc();
}

int ElisaLLVMIsConstantOne(LLVMValueRef value) {
  return PatternMatch::match(unwrap(value), PatternMatch::m_One());
}

int ElisaLLVMIsConstantZero(LLVMValueRef value) {
  return PatternMatch::match(unwrap(value), PatternMatch::m_Zero());
}

int ElisaLLVMIsSpecificInt(LLVMValueRef value, uint64_t expected) {
  return PatternMatch::match(unwrap(value), PatternMatch::m_SpecificInt(expected));
}

int ElisaLLVMMayHaveSideEffects(LLVMValueRef instruction) {
  return cast<Instruction>(unwrap(instruction))->mayHaveSideEffects();
}

int ElisaLLVMCallDoesNotAccessMemory(LLVMValueRef call) {
  return cast<CallBase>(unwrap(call))->doesNotAccessMemory();
}

int ElisaLLVMFunctionHasEntryCount(LLVMValueRef function) {
  return cast<Function>(unwrap(function))->getEntryCount().has_value();
}

int ElisaLLVMConstantIntIsNegative(LLVMValueRef constant) {
  return cast<ConstantInt>(unwrap(constant))->isNegative();
}

int ElisaLLVMConstantIntIsPositivePowerOfTwo(LLVMValueRef constant) {
  const APInt &value = cast<ConstantInt>(unwrap(constant))->getValue();
  return value.isStrictlyPositive() && value.isPowerOf2();
}

int ElisaLLVMConstantIntEquals(LLVMValueRef constant, uint64_t value) {
  return cast<ConstantInt>(unwrap(constant))->equalsInt(value);
}

unsigned ElisaLLVMConstantIntActiveBits(LLVMValueRef constant) {
  return cast<ConstantInt>(unwrap(constant))->getValue().getActiveBits();
}

unsigned ElisaLLVMConstantIntMaskWidth(LLVMValueRef constant) {
  const APInt &Value = cast<ConstantInt>(unwrap(constant))->getValue();
  return Value.isMask() ? Value.popcount() : 0;
}

int ElisaLLVMConstantIntUnsignedGreater(LLVMValueRef first, LLVMValueRef second) {
  return cast<ConstantInt>(unwrap(first))->getValue().ugt(cast<ConstantInt>(unwrap(second))->getValue());
}

unsigned ElisaLLVMConstantIntTrailingZeros(LLVMValueRef constant) {
  return cast<ConstantInt>(unwrap(constant))->getValue().countr_zero();
}

LLVMValueRef ElisaLLVMConstantIntOddPart(LLVMValueRef constant) {
  auto *Value = cast<ConstantInt>(unwrap(constant));
  const APInt &Bits = Value->getValue();
  return wrap(ConstantInt::get(Value->getType(), Bits.lshr(Bits.countr_zero())));
}

LLVMValueRef ElisaLLVMConstantIntLowBits(LLVMTypeRef type, unsigned bits) {
  auto *Integer = cast<IntegerType>(unwrap(type));
  return wrap(ConstantInt::get(Integer, APInt::getLowBitsSet(Integer->getBitWidth(), bits)));
}

int ElisaLLVMConstantIntsAgreeInLowBits(LLVMValueRef first, LLVMValueRef second, unsigned bits) {
  const APInt &First = cast<ConstantInt>(unwrap(first))->getValue();
  const APInt &Second = cast<ConstantInt>(unwrap(second))->getValue();
  return ((First ^ Second) & APInt::getLowBitsSet(First.getBitWidth(), bits)).isZero();
}

int ElisaLLVMMayReadOrWriteMemory(LLVMValueRef instruction) {
  return cast<Instruction>(unwrap(instruction))->mayReadOrWriteMemory();
}

LLVMValueRef ElisaLLVMStripPointerCasts(LLVMValueRef value) {
  return wrap(unwrap(value)->stripPointerCasts());
}

int ElisaLLVMMayReadFromMemory(LLVMValueRef instruction) {
  return cast<Instruction>(unwrap(instruction))->mayReadFromMemory();
}

int ElisaLLVMUnderlyingObjectsAreAllocas(LLVMValueRef pointer) {
  SmallVector<const Value *, 8> Objects;
  getUnderlyingObjects(unwrap(pointer), Objects, nullptr, 0);
  return !Objects.empty() &&
         llvm::all_of(Objects, [](const Value *Object) { return isa<AllocaInst>(Object); });
}

LLVMValueRef ElisaLLVMPointerBaseWithConstantOffset(LLVMValueRef pointer, LLVMModuleRef module,
                                                    int64_t *offset) {
  return wrap(GetPointerBaseWithConstantOffset(unwrap(pointer), *offset,
                                               unwrap(module)->getDataLayout()));
}

int ElisaLLVMIsStaticAlloca(LLVMValueRef alloca) {
  return cast<AllocaInst>(unwrap(alloca))->isStaticAlloca();
}

int ElisaLLVMAllocaIsUsedWithInAlloca(LLVMValueRef alloca) {
  return cast<AllocaInst>(unwrap(alloca))->isUsedWithInAlloca();
}

int ElisaLLVMAllocaIsSwiftError(LLVMValueRef alloca) {
  return cast<AllocaInst>(unwrap(alloca))->isSwiftError();
}

unsigned ElisaLLVMConstantIntByte(LLVMValueRef constant, unsigned index) {
  return cast<ConstantInt>(unwrap(constant))->getValue().extractBitsAsZExtValue(8, 8 * index);
}

unsigned ElisaLLVMBlockNumber(LLVMBasicBlockRef block) { return unwrap(block)->getNumber(); }

unsigned ElisaLLVMFunctionMaxBlockNumber(LLVMValueRef function) {
  return cast<Function>(unwrap(function))->getMaxBlockNumber();
}

int ElisaLLVMCallHasFunctionAttribute(LLVMValueRef call, unsigned kind) {
  return cast<CallBase>(unwrap(call))->hasFnAttr(static_cast<Attribute::AttrKind>(kind));
}

int ElisaLLVMIsMemIntrinsic(LLVMValueRef value) { return isa<MemIntrinsic>(unwrap(value)); }

int ElisaLLVMIsMemSet(LLVMValueRef value) { return isa<MemSetInst>(unwrap(value)); }

int ElisaLLVMIsUsedByMetadata(LLVMValueRef value) { return unwrap(value)->isUsedByMetadata(); }

uint32_t ElisaLLVMDataLayoutIndexSizeInBits(LLVMModuleRef module, uint32_t address_space) {
  return unwrap(module)->getDataLayout().getIndexSizeInBits(address_space);
}

int ElisaLLVMConstantIntSignedLess(LLVMValueRef first, LLVMValueRef second) {
  return cast<ConstantInt>(unwrap(first))->getValue().slt(cast<ConstantInt>(unwrap(second))->getValue());
}

int ElisaLLVMFunctionHasIrreducibleControlFlow(ElisaFunctionAnalysesRef analyses) {
  FunctionAnalyses *bundle = unwrapAnalyses(analyses);
  ReversePostOrderTraversal<Function *> order(&bundle->function);
  return containsIrreducibleCFG<BasicBlock *>(order, bundle->loops());
}

LLVMValueRef ElisaLLVMUnderlyingObject(LLVMValueRef value) {
  return wrap(getUnderlyingObject(unwrap(value)));
}

int ElisaLLVMBlockIsEHPad(LLVMBasicBlockRef block) { return unwrap(block)->isEHPad(); }

unsigned ElisaLLVMUseOperandNumber(LLVMUseRef use) { return unwrap(use)->getOperandNo(); }

int ElisaLLVMConstantFloatIsNegativeFiniteNonzero(LLVMValueRef constant) {
  const APFloat &Value = cast<ConstantFP>(unwrap(constant))->getValueAPF();
  return Value.isNegative() && !Value.isZero() && !Value.isNaN() && !Value.isInfinity();
}

int ElisaLLVMIsGuaranteedNotToBeUndefOrPoison(LLVMValueRef value) {
  return isGuaranteedNotToBeUndefOrPoison(unwrap(value));
}

int ElisaLLVMIsGuaranteedNotToBeUndefOrPoisonAt(ElisaFunctionAnalysesRef analyses, LLVMValueRef value,
                                                LLVMValueRef context) {
  return isGuaranteedNotToBeUndefOrPoison(unwrap(value), nullptr, cast<Instruction>(unwrap(context)),
                                          unwrapAnalyses(analyses)->dominators.get());
}

ElisaConstantRangeRef ElisaLLVMLazyValueConstantRange(ElisaFunctionAnalysesRef analyses, LLVMValueRef value,
                                                      LLVMValueRef context, int undef_allowed) {
  ConstantRange Range = unwrapAnalyses(analyses)->lazyValueInfo().getConstantRange(
      unwrap(value), cast<Instruction>(unwrap(context)), undef_allowed != 0);
  return reinterpret_cast<ElisaConstantRangeRef>(new ConstantRange(std::move(Range)));
}

int ElisaLLVMIsGuaranteedNotToBeUndefOrPoisonAssuming(ElisaFunctionAnalysesRef analyses,
                                                      LLVMValueRef value, LLVMValueRef context) {
  FunctionAnalyses *A = unwrapAnalyses(analyses);
  return isGuaranteedNotToBeUndefOrPoison(unwrap(value), &A->assumptionCache(),
                                          cast<Instruction>(unwrap(context)), A->dominators.get());
}

ElisaConstantRangeRef ElisaLLVMLazyValueConstantRangeOnEdge(ElisaFunctionAnalysesRef analyses,
                                                            LLVMValueRef value, LLVMBasicBlockRef from,
                                                            LLVMBasicBlockRef to, LLVMValueRef context) {
  ConstantRange Range = unwrapAnalyses(analyses)->lazyValueInfo().getConstantRangeOnEdge(
      unwrap(value), unwrap(from), unwrap(to), cast<Instruction>(unwrap(context)));
  return reinterpret_cast<ElisaConstantRangeRef>(new ConstantRange(std::move(Range)));
}

ElisaConstantRangeRef ElisaLLVMLazyValueConstantRangeAtUse(ElisaFunctionAnalysesRef analyses,
                                                           LLVMValueRef user, uint32_t operand_index,
                                                           int undef_allowed) {
  const Use &Operand = cast<User>(unwrap(user))->getOperandUse(operand_index);
  ConstantRange Range =
      unwrapAnalyses(analyses)->lazyValueInfo().getConstantRangeAtUse(Operand, undef_allowed != 0);
  return reinterpret_cast<ElisaConstantRangeRef>(new ConstantRange(std::move(Range)));
}

int ElisaLLVMIsImpliedCondition(LLVMValueRef condition, LLVMValueRef implied, LLVMModuleRef module,
                                int condition_is_true) {
  std::optional<bool> Known = isImpliedCondition(unwrap(condition), unwrap(implied),
                                                 unwrap(module)->getDataLayout(), condition_is_true != 0);
  return Known ? (*Known ? 1 : 0) : -1;
}

int ElisaLLVMConstantMaxBackedgeTakenCount(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop,
                                           uint64_t *count) {
  auto *Max = dyn_cast<SCEVConstant>(
      unwrapAnalyses(analyses)->scalarEvolution().getConstantMaxBackedgeTakenCount(unwrapLoop(loop)));
  if (!Max || Max->getAPInt().getActiveBits() > 64) return 0;
  *count = Max->getAPInt().getZExtValue();
  return 1;
}

unsigned ElisaLLVMScalarEvolutionUnsignedMaxActiveBits(ElisaFunctionAnalysesRef analyses,
                                                      LLVMValueRef value) {
  ScalarEvolution &SE = unwrapAnalyses(analyses)->scalarEvolution();
  Value *V = unwrap(value);
  if (!SE.isSCEVable(V->getType())) return 0;
  return SE.getUnsignedRangeMax(SE.getSCEV(V)).getActiveBits();
}

ElisaConstantRangeRef ElisaLLVMScalarEvolutionSignedRange(ElisaFunctionAnalysesRef analyses,
                                                          LLVMValueRef value) {
  ScalarEvolution &SE = unwrapAnalyses(analyses)->scalarEvolution();
  ConstantRange Range = SE.getSignedRange(SE.getSCEV(unwrap(value)));
  return reinterpret_cast<ElisaConstantRangeRef>(new ConstantRange(std::move(Range)));
}

uint32_t ElisaLLVMSmallConstantTripCount(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop,
                                         LLVMBasicBlockRef exiting) {
  return unwrapAnalyses(analyses)->scalarEvolution().getSmallConstantTripCount(unwrapLoop(loop),
                                                                               unwrap(exiting));
}

uint32_t ElisaLLVMSmallConstantMaxTripCount(ElisaFunctionAnalysesRef analyses, ElisaLoopRef loop) {
  return unwrapAnalyses(analyses)->scalarEvolution().getSmallConstantMaxTripCount(unwrapLoop(loop));
}

} // extern "C"
