// Remove signed-multiply overflow checks from constant-start running products
// whose multiplier is a unit-step counter under a small constant loop bound.
// The product sequence is then fully determined, so simulate it exactly: range
// multiplication cannot prove this shape, since 20^20 overflows while 20! fits.
#include "llvm_bounded_product.cpp"
#include <llvm/IR/InstIterator.h>
#include <llvm/ADT/APInt.h>
#include <llvm/ADT/SmallPtrSet.h>
#if LLVM_VERSION_MAJOR >= 23
namespace {
constexpr unsigned BFP_MaxIterations = 64;
static Value *BFP_Strip(Value *V) {
  auto *F = dyn_cast<FreezeInst>(V);
  return F ? F->getOperand(0) : V;
}
// True when V is the counter plus one, in plain or checked form.
static bool BFP_IsUnitStep(Value *V, PHINode *Counter) {
  Value *X = nullptr, *Y = nullptr;
  if (auto *Add = dyn_cast<BinaryOperator>(V)) {
    if (Add->getOpcode() != Instruction::Add) return false;
    X = Add->getOperand(0);
    Y = Add->getOperand(1);
  } else if (auto *E = dyn_cast<ExtractValueInst>(V)) {
    auto *C = dyn_cast<IntrinsicInst>(E->getAggregateOperand());
    if (!C || C->getIntrinsicID() != Intrinsic::sadd_with_overflow ||
        E->getNumIndices() != 1 || *E->idx_begin() != 0) return false;
    X = C->getArgOperand(0);
    Y = C->getArgOperand(1);
  } else {
    return false;
  }
  auto *One = dyn_cast<ConstantInt>(Y);
  return X == Counter && One && One->isOne();
}
// The largest counter value allowed to re-enter the header: the backedge is
// taken only when Step <= Limit (or Step < Limit), for invariant signed Limit.
static Value *BFP_UpperLimit(Loop *L, BasicBlock *Latch, Value *Step) {
  auto *B = dyn_cast<CondBrInst>(Latch->getTerminator());
  auto *Cmp = B ? dyn_cast<ICmpInst>(B->getCondition()) : nullptr;
  if (!Cmp) return nullptr;
  ICmpInst::Predicate P = Cmp->getPredicate();
  Value *Limit = Cmp->getOperand(1);
  if (Cmp->getOperand(0) != Step) {
    if (Cmp->getOperand(1) != Step) return nullptr;
    P = ICmpInst::getSwappedPredicate(P);
    Limit = Cmp->getOperand(0);
  }
  if (!L->isLoopInvariant(Limit)) return nullptr;
  bool StayOnTrue = B->getSuccessor(0) == L->getHeader() && !L->contains(B->getSuccessor(1));
  bool ExitOnTrue = B->getSuccessor(1) == L->getHeader() && !L->contains(B->getSuccessor(0));
  bool UpperStay = P == ICmpInst::ICMP_SLE || P == ICmpInst::ICMP_SLT;
  bool UpperExit = P == ICmpInst::ICMP_SGT || P == ICmpInst::ICMP_SGE;
  return (StayOnTrue && UpperStay) || (ExitOnTrue && UpperExit) ? Limit : nullptr;
}
// Accumulators over a repeatedly divided value: sum += r / C or sum += r % C,
// with r = r / C on each pass. For r0 <= M the k-th r is at most M / C^k, and
// once r is zero every later addend is zero, so the worst-case total is finite
// whatever the loop's exit condition. Addends are nonnegative, so only the
// upper end can overflow.
static void BFP_CollectDivisionSums(Loop *L, BasicBlock *Pre, BasicBlock *Latch, LoopInfo &LI,
                                    LazyValueInfo &LVI, SmallVectorImpl<IntrinsicInst *> &Out) {
  for (PHINode &R : L->getHeader()->phis()) {
    if (!R.getType()->isIntegerTy(64) || R.getNumIncomingValues() != 2) continue;
    auto *Div = dyn_cast<BinaryOperator>(R.getIncomingValueForBlock(Latch));
    if (!Div || Div->getOpcode() != Instruction::UDiv || Div->isExact() ||
        Div->getOperand(0) != &R) continue;
    auto *C = dyn_cast<ConstantInt>(Div->getOperand(1));
    if (!C || C->getValue().ult(2)) continue;
    Value *Initial = R.getIncomingValueForBlock(Pre);
    // UndefAllowed=false: a possibly-undef start yields the full range.
    ConstantRange IR = LVI.getConstantRangeOnEdge(Initial, Pre, L->getHeader(), Pre->getTerminator());
    if (IR.isEmptySet() || IR.isFullSet() || !IR.getUnsignedMax().isNonNegative()) continue;
    for (PHINode &Sum : L->getHeader()->phis()) {
      if (&Sum == &R || !Sum.getType()->isIntegerTy(64) || Sum.getNumIncomingValues() != 2) continue;
      auto *S0 = dyn_cast<ConstantInt>(Sum.getIncomingValueForBlock(Pre));
      auto *E = dyn_cast<ExtractValueInst>(Sum.getIncomingValueForBlock(Latch));
      auto *Call = E ? dyn_cast<IntrinsicInst>(E->getAggregateOperand()) : nullptr;
      if (!S0 || !Call || E->getNumIndices() != 1 || *E->idx_begin() != 0 ||
          Call->getIntrinsicID() != Intrinsic::sadd_with_overflow || Call->hasOperandBundles() ||
          Call->isConvergent() || Call->hasMetadataOtherThanDebugLoc() ||
          LI.getLoopFor(Call->getParent()) != L) continue;
      Value *X = BFP_Strip(Call->getArgOperand(0)), *Y = BFP_Strip(Call->getArgOperand(1));
      Value *Addend = X == &Sum ? Y : (Y == &Sum ? X : nullptr);
      auto *A = dyn_cast_or_null<BinaryOperator>(Addend);
      if (!A) continue;
      bool Quotient = A == Div;
      bool Remainder = A->getOpcode() == Instruction::URem && A->getOperand(0) == &R &&
                       A->getOperand(1) == C;
      if (!Quotient && !Remainder) continue;
      APInt Total = S0->getValue().sext(128), Rest = IR.getUnsignedMax().zext(128);
      APInt Divisor = C->getValue().zext(128);
      while (!Rest.isZero()) {
        APInt Next = Rest.udiv(Divisor);
        if (Quotient) Total += Next;
        else Total += Rest.ult(Divisor) ? Rest : Divisor - 1;
        Rest = Next;
      }
      if (Total.isSignedIntN(64)) Out.push_back(Call);
    }
  }
}
// The largest iteration count of a unit-step counter from a constant start,
// bounded by a limit whose preheader range is known. Zero when unproved.
static uint64_t BFP_IterationBound(Loop *L, BasicBlock *Pre, BasicBlock *Latch, LazyValueInfo &LVI) {
  auto *Br = dyn_cast<CondBrInst>(Latch->getTerminator());
  auto *Cmp = Br ? dyn_cast<ICmpInst>(Br->getCondition()) : nullptr;
  if (!Cmp) return 0;
  for (PHINode &I : L->getHeader()->phis()) {
    if (!I.getType()->isIntegerTy(64) || I.getNumIncomingValues() != 2) continue;
    auto *S = dyn_cast<ConstantInt>(I.getIncomingValueForBlock(Pre));
    Value *Step = I.getIncomingValueForBlock(Latch);
    if (!S || !BFP_IsUnitStep(Step, &I)) continue;
    Value *Limit = BFP_UpperLimit(L, Latch, Step);
    bool Equality = false;
    if (!Limit) {
      // Equality exits bound a unit counter only when the limit starts above it.
      Value *Other = Cmp->getOperand(0) == Step ? Cmp->getOperand(1)
                   : Cmp->getOperand(1) == Step ? Cmp->getOperand(0) : nullptr;
      bool Exit = (Cmp->getPredicate() == ICmpInst::ICMP_EQ && !L->contains(Br->getSuccessor(0)) &&
                   Br->getSuccessor(1) == L->getHeader()) ||
                  (Cmp->getPredicate() == ICmpInst::ICMP_NE && !L->contains(Br->getSuccessor(1)) &&
                   Br->getSuccessor(0) == L->getHeader());
      if (!Other || !Exit || !L->isLoopInvariant(Other)) continue;
      Limit = Other;
      Equality = true;
    }
    ConstantRange R = LVI.getConstantRangeOnEdge(Limit, Pre, L->getHeader(), Pre->getTerminator());
    if (R.isEmptySet() || R.isFullSet()) continue;
    if (Equality && !R.getSignedMin().sgt(S->getValue())) continue;
    APInt Last = R.getSignedMax();
    if (Last.slt(S->getValue())) Last = S->getValue();
    if (!S->getValue().sge(-1024) || !Last.sle(1024)) continue;
    uint64_t Count = Last.getSExtValue() - S->getSExtValue() + 1;
    if (Count <= BFP_MaxIterations) return Count;
  }
  return 0;
}
// Horner recurrences: x = x * K + d, with constant start and K, d in a range
// known at its use, and a bounded loop. Simulate the interval of x exactly.
static void BFP_CollectHorner(Loop *L, BasicBlock *Pre, BasicBlock *Latch, LoopInfo &LI,
                              LazyValueInfo &LVI, SmallVectorImpl<IntrinsicInst *> &Out) {
  auto Checked = [&](Value *V, Intrinsic::ID ID) -> IntrinsicInst * {
    auto *E = dyn_cast<ExtractValueInst>(V);
    auto *C = E ? dyn_cast<IntrinsicInst>(E->getAggregateOperand()) : nullptr;
    if (!C || E->getNumIndices() != 1 || *E->idx_begin() != 0 || C->getIntrinsicID() != ID ||
        C->hasOperandBundles() || C->isConvergent() || C->hasMetadataOtherThanDebugLoc() ||
        LI.getLoopFor(C->getParent()) != L) return nullptr;
    return C;
  };
  uint64_t Iterations = 0;
  for (PHINode &X : L->getHeader()->phis()) {
    if (!X.getType()->isIntegerTy(64) || X.getNumIncomingValues() != 2) continue;
    auto *X0 = dyn_cast<ConstantInt>(X.getIncomingValueForBlock(Pre));
    IntrinsicInst *Add = Checked(X.getIncomingValueForBlock(Latch), Intrinsic::sadd_with_overflow);
    if (!X0 || !Add) continue;
    IntrinsicInst *Mul = nullptr;
    Value *D = nullptr;
    for (unsigned I = 0; I < 2 && !Mul; ++I)
      if ((Mul = Checked(Add->getArgOperand(I), Intrinsic::smul_with_overflow)))
        D = Add->getArgOperand(1 - I);
    if (!Mul) continue;
    Value *A = Mul->getArgOperand(0), *B = Mul->getArgOperand(1);
    auto *K = dyn_cast<ConstantInt>(A == &X ? B : (B == &X ? A : nullptr));
    if (!K || !K->getValue().isStrictlyPositive()) continue;
    // UndefAllowed=false: a possibly-undef addend yields the full range.
    ConstantRange DR = LVI.getConstantRange(D, Add, false);
    if (DR.isEmptySet() || DR.isFullSet()) continue;
    if (!Iterations) Iterations = BFP_IterationBound(L, Pre, Latch, LVI);
    if (!Iterations) return;
    APInt Lo = X0->getValue().sext(128), Hi = Lo, Factor = K->getValue().sext(128);
    APInt DMin = DR.getSignedMin().sext(128), DMax = DR.getSignedMax().sext(128);
    bool Safe = true;
    // Factor > 0 keeps interval endpoints ordered. Widening with the previous
    // interval also covers runs that stop after fewer iterations.
    for (uint64_t I = 0; I < Iterations && Safe; ++I) {
      APInt L1 = Lo * Factor, H1 = Hi * Factor;
      APInt L2 = L1 + DMin, H2 = H1 + DMax;
      Safe = L1.isSignedIntN(64) && H1.isSignedIntN(64) && L2.isSignedIntN(64) && H2.isSignedIntN(64);
      Lo = APIntOps::smin(Lo, L2);
      Hi = APIntOps::smax(Hi, H2);
    }
    if (Safe) {
      Out.push_back(Mul);
      Out.push_back(Add);
    }
  }
}
}
extern "C" unsigned elisacoreBoundedFactorials(LLVMModuleRef Ref) {
  if (!Ref) return 0;
  Module &M = *unwrap(Ref);
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
  unsigned Changed = 0;
  for (Function &F : M) {
    if (BDU_SkipFunction(F, M)) continue;
    bool HasCheckedMul = false;
    for (Instruction &I : instructions(F))
      if (auto *C = dyn_cast<IntrinsicInst>(&I))
        HasCheckedMul |= C->getIntrinsicID() == Intrinsic::smul_with_overflow ||
                         C->getIntrinsicID() == Intrinsic::sadd_with_overflow;
    if (!HasCheckedMul) continue;
    auto &LI = FAM.getResult<LoopAnalysis>(F);
    auto &DT = FAM.getResult<DominatorTreeAnalysis>(F);
    auto &LVI = FAM.getResult<LazyValueAnalysis>(F);
    SmallVector<std::pair<BinaryOperator *, IntrinsicInst *>, 4> Proven;
    SmallVector<IntrinsicInst *, 4> ProvenSums;
    SmallPtrSet<IntrinsicInst *, 8> SeenSums;
    for (Loop *L : LI.getLoopsInPreorder()) {
      BasicBlock *Pre = L->getLoopPredecessor(), *Latch = L->getLoopLatch();
      if (!Pre || !Latch || !L->getSubLoops().empty()) continue;
      BFP_CollectDivisionSums(L, Pre, Latch, LI, LVI, ProvenSums);
      BFP_CollectHorner(L, Pre, Latch, LI, LVI, ProvenSums);
      for (PHINode &Product : L->getHeader()->phis()) {
        if (!Product.getType()->isIntegerTy(64) || Product.getNumIncomingValues() != 2) continue;
        auto *P0 = dyn_cast<ConstantInt>(Product.getIncomingValueForBlock(Pre));
        auto *Mul = dyn_cast<BinaryOperator>(Product.getIncomingValueForBlock(Latch));
        if (!P0 || !Mul || Mul->getOpcode() != Instruction::Mul ||
            Mul->hasNoUnsignedWrap() || LI.getLoopFor(Mul->getParent()) != L ||
            !DT.dominates(Mul->getParent(), Latch)) continue;
        Value *A = BFP_Strip(Mul->getOperand(0)), *B = BFP_Strip(Mul->getOperand(1));
        auto *Counter = dyn_cast<PHINode>(A == &Product ? B : (B == &Product ? A : nullptr));
        if (!Counter || Counter == &Product || Counter->getParent() != L->getHeader() ||
            Counter->getNumIncomingValues() != 2) continue;
        auto *C0 = dyn_cast<ConstantInt>(Counter->getIncomingValueForBlock(Pre));
        Value *Step = Counter->getIncomingValueForBlock(Latch);
        if (!C0 || !BFP_IsUnitStep(Step, Counter)) continue;
        Value *Limit = BFP_UpperLimit(L, Latch, Step);
        if (!Limit) continue;
        // UndefAllowed=false: a possibly-undef limit yields the full range.
        ConstantRange LR = LVI.getConstantRangeOnEdge(Limit, Pre, L->getHeader(), Pre->getTerminator());
        if (LR.isEmptySet() || LR.isFullSet()) continue;
        APInt First = C0->getValue(), Last = LR.getSignedMax();
        if (Last.slt(First)) Last = First; // A first iteration may precede the test.
        if (!First.sge(-1024) || !Last.sle(1024) ||
            (Last.getSExtValue() - First.getSExtValue()) >= BFP_MaxIterations) continue;
        // Exact simulation in 128 bits. The first iteration runs unconditionally
        // in rotated form; later counters are bounded by the backedge test.
        APInt Value128 = P0->getValue().sext(128);
        bool Safe = true;
        for (int64_t K = First.getSExtValue(); K <= Last.getSExtValue() && Safe; ++K) {
          Value128 *= APInt(128, K, true);
          Safe = Value128.isSignedIntN(64);
        }
        if (!Safe) continue;
        for (BasicBlock *BB : L->blocks())
          for (Instruction &I : *BB) {
            auto *C = dyn_cast<IntrinsicInst>(&I);
            if (!C || C->getIntrinsicID() != Intrinsic::smul_with_overflow ||
                C->hasOperandBundles() || C->isConvergent() || !DT.dominates(Mul, C)) continue;
            Value *X = BFP_Strip(C->getArgOperand(0)), *Y = BFP_Strip(C->getArgOperand(1));
            if ((X == &Product && Y == Counter) || (X == Counter && Y == &Product))
              Proven.push_back({Mul, C});
          }
      }
    }
    for (auto &[Mul, C] : Proven) {
      Mul->setHasNoSignedWrap(true);
      IRBuilder<> B(C);
      Value *Pair = B.CreateInsertValue(PoisonValue::get(C->getType()), Mul, 0);
      Pair = B.CreateInsertValue(Pair, B.getFalse(), 1);
      C->replaceAllUsesWith(Pair);
      C->eraseFromParent();
      ++Changed;
    }
    for (IntrinsicInst *C : ProvenSums) {
      if (!SeenSums.insert(C).second) continue;
      IRBuilder<> B(C);
      Value *Sum = C->getIntrinsicID() == Intrinsic::smul_with_overflow
                       ? B.CreateNSWMul(C->getArgOperand(0), C->getArgOperand(1))
                       : B.CreateNSWAdd(C->getArgOperand(0), C->getArgOperand(1));
      Value *Pair = B.CreateInsertValue(PoisonValue::get(C->getType()), Sum, 0);
      Pair = B.CreateInsertValue(Pair, B.getFalse(), 1);
      C->replaceAllUsesWith(Pair);
      C->eraseFromParent();
      ++Changed;
    }
    if (!Proven.empty() || !ProvenSums.empty()) FAM.invalidate(F, PreservedAnalyses::none());
  }
  return Changed;
}
#else
extern "C" unsigned elisacoreBoundedFactorials(LLVMModuleRef) { return 0; }
#endif
