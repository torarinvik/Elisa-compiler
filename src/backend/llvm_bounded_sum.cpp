//go:build cgo

#include <llvm/Config/llvm-config.h>
#include <llvm-c/Core.h>
#include <llvm-c/TargetMachine.h>
#include <llvm-c/Error.h>
#include <llvm-c/Transforms/PassBuilder.h>
#if LLVM_VERSION_MAJOR >= 23
// Prove a recurrence's prefix sums from its nonnegative seed and step range
// and its maximum iteration count. Reuse those bounds for nearby arithmetic.
#include <cstdint>
#include <llvm/ADT/STLExtras.h>
#include <llvm/ADT/DenseMap.h>
#include <llvm/ADT/SmallPtrSet.h>
#include <llvm/Analysis/AssumptionCache.h>
#include <llvm/Analysis/CFG.h>
#include <llvm/Analysis/LazyValueInfo.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/Analysis/ScalarEvolution.h>
#include <llvm/Analysis/ScalarEvolutionExpressions.h>
#include <llvm/Analysis/TargetLibraryInfo.h>
#include <llvm/Analysis/ValueTracking.h>
#include <llvm/IR/Constants.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/IR/InstIterator.h>
#include <llvm/IR/Module.h>
#include <llvm/IR/PassManager.h>
#include <llvm/Passes/PassBuilder.h>
#include <llvm/Support/CBindingWrapping.h>

using namespace llvm;

namespace BoundedSumProof {
struct SumFact {
  PHINode *Accumulator;
  Value *Update;
  BinaryOperator *PlainAdd;
  IntrinsicInst *CheckedAdd;
  ConstantRange Range;
};

static bool trapBlock(BasicBlock *BB) {
  bool SawTrap = false;
  for (Instruction &I : *BB) {
    if (isa<DbgInfoIntrinsic>(&I))
      continue;
    if (auto *CB = dyn_cast<IntrinsicInst>(&I)) {
      if (CB->getIntrinsicID() == Intrinsic::trap && !SawTrap &&
          !CB->hasOperandBundles()) {
        SawTrap = true;
        continue;
      }
    }
    if (isa<UnreachableInst>(I) && SawTrap)
      return true;
    return false;
  }
  return false;
}

static bool checkedAddHasTrapGuard(IntrinsicInst *Call, BasicBlock *UseBlock,
                                   Loop *L, DominatorTree &DT) {
  if (!Call || Call->getIntrinsicID() != Intrinsic::sadd_with_overflow ||
      Call->arg_size() != 2 || Call->hasOperandBundles() ||
      Call->hasMetadataOtherThanDebugLoc() || Call->isConvergent() ||
      !L->contains(Call->getParent()))
    return false;
  ExtractValueInst *Flag = nullptr;
  for (User *U : Call->users()) {
    auto *E = dyn_cast<ExtractValueInst>(U);
    if (!E || E->getNumIndices() != 1 || *E->idx_begin() > 1)
      return false;
    if (*E->idx_begin() == 1) {
      if (Flag)
        return false;
      Flag = E;
    }
  }
  if (!Flag || !Flag->hasOneUse())
    return false;
  auto *Br = dyn_cast<CondBrInst>(*Flag->user_begin());
  if (!Br || Br->getCondition() != Flag ||
      !trapBlock(Br->getSuccessor(0)))
    return false;
  BasicBlock *Continue = Br->getSuccessor(1);
  return L->contains(Continue) && DT.dominates(Continue, UseBlock);
}

static bool checkedSubHasOnlyTrapFlag(IntrinsicInst *Call) {
  if (!Call || Call->getIntrinsicID() != Intrinsic::ssub_with_overflow ||
      Call->arg_size() != 2 || Call->hasOperandBundles() ||
      Call->hasMetadataOtherThanDebugLoc() || Call->isConvergent())
    return false;
  ExtractValueInst *Flag = nullptr;
  for (User *U : Call->users()) {
    auto *E = dyn_cast<ExtractValueInst>(U);
    if (!E || E->getNumIndices() != 1 || *E->idx_begin() > 1)
      return false;
    if (*E->idx_begin() == 1) {
      if (Flag)
        return false;
      Flag = E;
    }
  }
  if (!Flag || !Flag->hasOneUse())
    return false;
  auto *Br = dyn_cast<CondBrInst>(*Flag->user_begin());
  return Br && Br->getCondition() == Flag &&
         trapBlock(Br->getSuccessor(0));
}

// Accept a recurrence leaf only when it is either the old value (a skipped
// conditional update) or exactly one add of the PHI and an independent step.
static bool findUpdateLeaf(Value *V, PHINode *P, Loop *L, Value *&Step,
                           BinaryOperator *&PlainAdd,
                           IntrinsicInst *&CheckedAdd, unsigned Depth = 0) {
  if (Depth > 8)
    return false;
  if (V == P)
    return true;
  if (auto *E = dyn_cast<ExtractValueInst>(V)) {
    if (E->getNumIndices() != 1 || *E->idx_begin() != 0)
      return false;
    auto *Call = dyn_cast<IntrinsicInst>(E->getAggregateOperand());
    if (!Call || Call->getIntrinsicID() != Intrinsic::sadd_with_overflow ||
        Call->arg_size() != 2 || (CheckedAdd && CheckedAdd != Call) ||
        PlainAdd)
      return false;
    Value *S = nullptr;
    if (Call->getArgOperand(0) == P)
      S = Call->getArgOperand(1);
    else if (Call->getArgOperand(1) == P)
      S = Call->getArgOperand(0);
    if (!S || (Step && Step != S))
      return false;
    Step = S;
    CheckedAdd = Call;
    return true;
  }
  if (auto *BO = dyn_cast<BinaryOperator>(V)) {
    if (BO->getOpcode() != Instruction::Add || BO->hasMetadataOtherThanDebugLoc() ||
        (PlainAdd && PlainAdd != BO) || CheckedAdd)
      return false;
    Value *S = nullptr;
    if (BO->getOperand(0) == P)
      S = BO->getOperand(1);
    else if (BO->getOperand(1) == P)
      S = BO->getOperand(0);
    if (!S || (Step && Step != S))
      return false;
    PlainAdd = BO;
    Step = S;
    return true;
  }
  // A latch PHI/select may carry the old accumulator on some paths and the
  // one checked/plain update on others. Do not look through arbitrary ops.
  if (auto *P2 = dyn_cast<PHINode>(V)) {
    if (!L->contains(P2->getParent()))
      return false;
    bool SawUpdate = false;
    for (Value *In : P2->incoming_values()) {
      Value *Before = Step;
      BinaryOperator *BeforeAdd = PlainAdd;
      IntrinsicInst *BeforeCall = CheckedAdd;
      if (!findUpdateLeaf(In, P, L, Step, PlainAdd, CheckedAdd, Depth + 1))
        return false;
      SawUpdate |= Step != Before || PlainAdd != BeforeAdd ||
                   CheckedAdd != BeforeCall;
    }
    return SawUpdate;
  }
  if (auto *Sel = dyn_cast<SelectInst>(V)) {
    Value *Before = Step;
    BinaryOperator *BeforeAdd = PlainAdd;
    IntrinsicInst *BeforeCall = CheckedAdd;
    bool A = findUpdateLeaf(Sel->getTrueValue(), P, L, Step, PlainAdd,
                            CheckedAdd, Depth + 1);
    bool B = findUpdateLeaf(Sel->getFalseValue(), P, L, Step, PlainAdd,
                            CheckedAdd, Depth + 1);
    return A && B && (Step != Before || PlainAdd != BeforeAdd ||
                      CheckedAdd != BeforeCall);
  }
  return false;
}

static ConstantRange rangeAt(Value *V, Instruction *At, LazyValueInfo &LVI, AssumptionCache &AC, DominatorTree &DT,
                             const DenseMap<Value *, ConstantRange> &Known) {
  if (auto I = Known.find(V); I != Known.end())
    return I->second;
  if (!V->getType()->isIntegerTy())
    return ConstantRange::getFull(1);
  auto R = LVI.getConstantRange(V, At, false);
  if (R.isSingleElement() && !isGuaranteedNotToBeUndefOrPoison(V, &AC, At, &DT))
    return ConstantRange::getFull(V->getType()->getIntegerBitWidth());
  return R;
}

// A signed minimum with a nonnegative cap can lower a zero-seeded sum
// without taking it outside the same nonnegative prefix bounds.
static bool findClampedUpdate(
    IntrinsicInst *Min, PHINode *P, Loop *L, Value *&Step,
    BinaryOperator *&PlainAdd, IntrinsicInst *&CheckedAdd,
    LazyValueInfo &LVI, AssumptionCache &AC, DominatorTree &DT,
    const DenseMap<Value *, ConstantRange> &Known) {
  if (Min->hasOperandBundles() || Min->hasMetadataOtherThanDebugLoc())
    return false;
  for (unsigned Index = 0; Index < 2; ++Index) {
    Value *CandidateStep = nullptr;
    BinaryOperator *CandidateAdd = nullptr;
    IntrinsicInst *CandidateChecked = nullptr;
    if (!findUpdateLeaf(Min->getArgOperand(Index), P, L, CandidateStep,
                        CandidateAdd, CandidateChecked) ||
        !CandidateStep)
      continue;
    auto Cap = rangeAt(Min->getArgOperand(1 - Index), Min, LVI, AC, DT, Known);
    if (Cap.isEmptySet() || Cap.getSignedMin().isNegative())
      continue;
    Step = CandidateStep;
    PlainAdd = CandidateAdd;
    CheckedAdd = CandidateChecked;
    return true;
  }
  return false;
}

static bool fitsSignedAccumulation(PHINode *P, Value *Initial, Value *Step,
                                   Instruction *At, uint32_t Updates,
                                   LazyValueInfo &LVI,
                                   AssumptionCache &AC, DominatorTree &DT,
                                   ConstantRange &Out) {
  auto *Ty = dyn_cast<IntegerType>(P->getType());
  auto *Start = dyn_cast<ConstantInt>(Initial);
  if (!Ty || Ty->getBitWidth() > 128 || !Start || Start->isNegative() ||
      Step->getType() != P->getType() ||
      !isGuaranteedNotToBeUndefOrPoison(Initial, &AC, At, &DT))
    return false;
  // LVI(false) excludes non-singleton ranges that may include undef. A
  // singleton may still include undef, so require a separate guarantee there.
  // For the closed recurrence, every concrete step choice is
  // bounded; poison propagates through its adds. It needs no noundef assertion
  // on the cyclic PHI (which ValueTracking cannot generally prove).
  const APInt &Seed = Start->getValue();
  ConstantRange SR = LVI.getConstantRange(Step, At, false);
  if (SR.isEmptySet() || SR.isFullSet() || SR.isWrappedSet() ||
      SR.getSignedMin().isNegative() ||
      (SR.isSingleElement() && !isGuaranteedNotToBeUndefOrPoison(Step, &AC, At, &DT)))
    return false;
  unsigned W = Ty->getBitWidth(), EW = W + 32;
  APInt MaxStep = SR.getSignedMax().sext(EW);
  APInt MaxSum = Seed.zext(EW) + MaxStep * APInt(EW, Updates);
  if (!MaxSum.isSignedIntN(W))
    return false;
  Out = ConstantRange::getNonEmpty(Seed,
                                    MaxSum.trunc(W) + APInt(W, 1));
  return true;
}

static bool boundedBackedges(Loop *L, ScalarEvolution &SE, uint32_t &Updates) {
  const SCEV *S = SE.getConstantMaxBackedgeTakenCount(L);
  auto *C = dyn_cast<SCEVConstant>(S);
  if (!C || C->getAPInt().getActiveBits() > 32)
    return false;
  uint64_t MaxBackedges = C->getAPInt().getZExtValue();
  if (MaxBackedges >= UINT32_MAX)
    return false;
  Updates = static_cast<uint32_t>(MaxBackedges + 1);
  return true;
}

} // namespace

extern "C" unsigned elisacoreBoundedCheckedSums(LLVMModuleRef Ref) {
  if (!Ref)
    return 0;
  using namespace BoundedSumProof;
  Module &M = *unwrap(Ref);
  if (M.getNamedMetadata("llvm.dbg.cu"))
    return 0;
  PassBuilder PB;
  LoopAnalysisManager LAM;
  FunctionAnalysisManager FAM;
  CGSCCAnalysisManager CGAM;
  ModuleAnalysisManager MAM;
  PB.registerModuleAnalyses(MAM);
  PB.registerCGSCCAnalyses(CGAM);
  PB.registerFunctionAnalyses(FAM);
  PB.registerLoopAnalyses(LAM);
  PB.crossRegisterProxies(LAM, FAM, CGAM, MAM);
  unsigned Changed = 0, Functions = 0, Loops = 0;
  for (Function &F : M) {
    if (F.isDeclaration() || F.hasFnAttribute(Attribute::StrictFP) ||
        F.hasOptNone() || F.hasFnAttribute(Attribute::OptimizeForSize) ||
        F.hasFnAttribute(Attribute::MinSize) ||
        F.hasFnAttribute(Attribute::SanitizeAddress) ||
        F.hasFnAttribute(Attribute::SanitizeMemory) ||
        F.hasFnAttribute(Attribute::SanitizeThread) ||
        F.hasFnAttribute(Attribute::SanitizeHWAddress) ||
        F.getInstructionCount() > 10000)
      continue;
    bool HasZeroPhi = false, HasUpdate = false;
    for (Instruction &I : instructions(F)) {
      if (auto *P = dyn_cast<PHINode>(&I))
        if (P->getType()->isIntegerTy() && P->getNumIncomingValues() == 2)
          for (Value *V : P->incoming_values())
            if (auto *C = dyn_cast<ConstantInt>(V)) HasZeroPhi |= C->isZero();
      if (auto *BO = dyn_cast<BinaryOperator>(&I))
        HasUpdate |= BO->getOpcode() == Instruction::Add &&
                     (!BO->hasNoSignedWrap() || !BO->hasNoUnsignedWrap());
      if (auto *II = dyn_cast<IntrinsicInst>(&I))
        HasUpdate |= II->getIntrinsicID() == Intrinsic::sadd_with_overflow;
    }
    if (!HasZeroPhi || !HasUpdate) continue;
    if (++Functions > 32) break;
    auto &LI = FAM.getResult<LoopAnalysis>(F);
    auto &DT = FAM.getResult<DominatorTreeAnalysis>(F);
    auto &AC = FAM.getResult<AssumptionAnalysis>(F);
    auto &LVI = FAM.getResult<LazyValueAnalysis>(F);
    auto &SE = FAM.getResult<ScalarEvolutionAnalysis>(F);
    ReversePostOrderTraversal<Function *> RPO(&F);
    if (containsIrreducibleCFG<BasicBlock *>(RPO, LI))
      continue;
    SmallVector<SumFact, 4> Facts;
    DenseMap<Value *, ConstantRange> ProvenRanges;
    for (Loop *L : LI.getLoopsInPreorder()) {
      if (++Loops > 64)
        break;
      if (!L->getSubLoops().empty())
        continue;
      BasicBlock *Pre = L->getLoopPredecessor();
      BasicBlock *Latch = L->getLoopLatch();
      uint32_t Updates = 0;
      if (!Pre || !Latch || !boundedBackedges(L, SE, Updates))
        continue;
      for (PHINode &P : L->getHeader()->phis()) {
        if (P.getNumIncomingValues() != 2 || !P.getType()->isIntegerTy())
          continue;
        int PI = P.getBasicBlockIndex(Pre), LIx = P.getBasicBlockIndex(Latch);
        if (PI < 0 || LIx < 0 || PI == LIx)
          continue;
        Value *U = P.getIncomingValue(LIx), *Step = nullptr;
        BinaryOperator *PlainAdd = nullptr;
        IntrinsicInst *CheckedAdd = nullptr;
        Value *Initial = P.getIncomingValue(PI);
        auto *Min = dyn_cast<IntrinsicInst>(U);
        auto *Seed = dyn_cast<ConstantInt>(Initial);
        if (Min && Min->getIntrinsicID() == Intrinsic::smin && Seed &&
            Seed->isZero()) {
          if (!findClampedUpdate(Min, &P, L, Step, PlainAdd, CheckedAdd,
                                 LVI, AC, DT, ProvenRanges))
            continue;
        } else if (!findUpdateLeaf(U, &P, L, Step, PlainAdd, CheckedAdd)) {
          continue;
        }
        Instruction *At = CheckedAdd ? static_cast<Instruction *>(CheckedAdd) : PlainAdd;
        if (!At || !DT.dominates(L->getHeader(), At->getParent()))
          continue;
        if (CheckedAdd &&
            !checkedAddHasTrapGuard(CheckedAdd, Latch, L, DT))
          continue;
        ConstantRange R = ConstantRange::getFull(P.getType()->getIntegerBitWidth());
        if (!fitsSignedAccumulation(&P, Initial, Step, At, Updates, LVI, AC,
                                    DT, R))
          continue;
        Facts.push_back({&P, U, PlainAdd, CheckedAdd, R});
        ProvenRanges.insert_or_assign(&P, R);
        ProvenRanges.insert_or_assign(U, R);
        if (CheckedAdd)
          for (User *CU : CheckedAdd->users())
            if (auto *EV = dyn_cast<ExtractValueInst>(CU))
              if (EV->getNumIndices() == 1 && *EV->idx_begin() == 0)
                ProvenRanges.insert_or_assign(EV, R);
      }
    }

    // Use the recurrence bounds to prove other checked arithmetic.
    SmallVector<IntrinsicInst *, 4> SafeChecked;
    SmallVector<BinaryOperator *, 4> SafePlainSubs;
    for (Instruction &I : instructions(F)) {
      if (auto *Sub = dyn_cast<BinaryOperator>(&I)) {
        if (Sub->getOpcode() != Instruction::Sub ||
            Sub->hasNoSignedWrap() || Sub->hasNoUnsignedWrap() ||
            Sub->hasMetadataOtherThanDebugLoc())
          continue;
        auto A = rangeAt(Sub->getOperand(0), Sub, LVI, AC, DT, ProvenRanges);
        auto B = rangeAt(Sub->getOperand(1), Sub, LVI, AC, DT, ProvenRanges);
        if (A.isEmptySet() || A.isFullSet() || A.isWrappedSet() ||
            B.isEmptySet() || B.isFullSet() || B.isWrappedSet())
          continue;
        unsigned W = Sub->getType()->getIntegerBitWidth();
        APInt Lo = A.getSignedMin().sext(W + 1) - B.getSignedMax().sext(W + 1);
        APInt Hi = A.getSignedMax().sext(W + 1) - B.getSignedMin().sext(W + 1);
        if (Lo.isSignedIntN(W) && Hi.isSignedIntN(W))
          SafePlainSubs.push_back(Sub);
        continue;
      }
      auto *Call = dyn_cast<IntrinsicInst>(&I);
      if (Call && Call->getIntrinsicID() == Intrinsic::sadd_with_overflow &&
          !Call->hasOperandBundles() && !Call->hasMetadataOtherThanDebugLoc() &&
          !Call->isConvergent() &&
          (ProvenRanges.count(Call->getArgOperand(0)) ||
           ProvenRanges.count(Call->getArgOperand(1))) &&
          !llvm::any_of(Facts, [Call](const SumFact &Fact) {
            return Fact.CheckedAdd == Call;
          })) {
        auto A = rangeAt(Call->getArgOperand(0), Call, LVI, AC, DT, ProvenRanges);
        auto B = rangeAt(Call->getArgOperand(1), Call, LVI, AC, DT, ProvenRanges);
        if (!A.isEmptySet() && !B.isEmptySet() &&
            A.signedAddMayOverflow(B) == ConstantRange::OverflowResult::NeverOverflows)
          SafeChecked.push_back(Call);
        continue;
      }
      if (!Call || Call->getIntrinsicID() != Intrinsic::ssub_with_overflow ||
          Call->hasOperandBundles() || Call->hasMetadataOtherThanDebugLoc() ||
          Call->isConvergent() || Call->arg_size() != 2 ||
          !checkedSubHasOnlyTrapFlag(Call))
        continue;
      auto A = rangeAt(Call->getArgOperand(0), Call, LVI, AC, DT, ProvenRanges);
      auto B = rangeAt(Call->getArgOperand(1), Call, LVI, AC, DT, ProvenRanges);
      if (A.isEmptySet() || A.isFullSet() || A.isWrappedSet() ||
          B.isEmptySet() || B.isFullSet() || B.isWrappedSet())
        continue;
      unsigned W = Call->getArgOperand(0)->getType()->getIntegerBitWidth();
      APInt Lo = A.getSignedMin().sext(W + 1) - B.getSignedMax().sext(W + 1);
      APInt Hi = A.getSignedMax().sext(W + 1) - B.getSignedMin().sext(W + 1);
      if (Lo.isSignedIntN(W) && Hi.isSignedIntN(W))
        SafeChecked.push_back(Call);
    }

    // Apply only after all ranges were derived from the unmodified function.
    SmallPtrSet<IntrinsicInst *, 8> RewrittenAdds;
    for (SumFact &Fact : Facts) {
      if (Fact.PlainAdd && (!Fact.PlainAdd->hasNoSignedWrap() || !Fact.PlainAdd->hasNoUnsignedWrap())) {
        Fact.PlainAdd->setHasNoSignedWrap();
        Fact.PlainAdd->setHasNoUnsignedWrap();
        ++Changed;
      }
      if (Fact.CheckedAdd && RewrittenAdds.insert(Fact.CheckedAdd).second) {
        IRBuilder<> B(Fact.CheckedAdd);
        Value *Sum = B.CreateAdd(Fact.CheckedAdd->getArgOperand(0),
                                 Fact.CheckedAdd->getArgOperand(1), "", true, true);
        Value *Pair = B.CreateInsertValue(
            PoisonValue::get(Fact.CheckedAdd->getType()), Sum, 0);
        Pair = B.CreateInsertValue(Pair, B.getFalse(), 1);
        Fact.CheckedAdd->replaceAllUsesWith(Pair);
        Fact.CheckedAdd->eraseFromParent();
        ++Changed;
      }
    }
    for (IntrinsicInst *Call : SafeChecked) {
      IRBuilder<> B(Call);
      Value *A = Call->getArgOperand(0), *BVal = Call->getArgOperand(1);
      Value *Result = Call->getIntrinsicID() == Intrinsic::sadd_with_overflow
                          ? B.CreateNSWAdd(A, BVal)
                          : B.CreateNSWSub(A, BVal);
      Value *Pair = B.CreateInsertValue(PoisonValue::get(Call->getType()),
                                        Result, 0);
      Pair = B.CreateInsertValue(Pair, B.getFalse(), 1);
      Call->replaceAllUsesWith(Pair);
      Call->eraseFromParent();
      ++Changed;
    }
    for (BinaryOperator *Sub : SafePlainSubs) {
      Sub->setHasNoSignedWrap();
      ++Changed;
    }
  }
  return Changed;
}

#else
extern "C" unsigned elisacoreBoundedCheckedSums(LLVMModuleRef) { return 0; }
#endif

extern "C" unsigned elisacoreOptimizeBoundedSums(LLVMModuleRef M, LLVMTargetMachineRef T) {
  if (!elisacoreBoundedCheckedSums(M)) return 0;
  auto Options = LLVMCreatePassBuilderOptions();
  auto Error = LLVMRunPasses(M, "function(instcombine<max-iterations=8;no-verify-fixpoint>,simplifycfg)", T, Options);
  LLVMDisposePassBuilderOptions(Options);
  if (Error) { LLVMConsumeError(Error); return 2; }
  return 1;
}
