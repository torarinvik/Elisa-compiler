// Preserve overflow traps unless an inductive loop bound and widened
// interval products prove every intermediate result fits signed arithmetic.
#include "llvm_bounded_division_unroll.cpp"
#if LLVM_VERSION_MAJOR >= 23
namespace {
// Range composition is not a definedness proof: flagged arithmetic is
// checked separately, using only ranges of operands already proved defined.
static ConstantRange BDP_Range(Value *V, Instruction *Context,
                               LazyValueInfo &LVI,
                               const DenseMap<Value *, ConstantRange> *Known,
                               unsigned Depth = 0, unsigned *Budget = nullptr) {
  unsigned Local = 64;
  if (!Budget)
    Budget = &Local;
  if (!*Budget)
    return ConstantRange::getFull(V->getType()->getIntegerBitWidth());
  --*Budget;
  if (Known)
    if (auto I = Known->find(V); I != Known->end())
      return I->second;
  auto R = LVI.getConstantRange(V, Context, false);
  if (Depth >= 6)
    return R;
  if (auto *B = dyn_cast<BinaryOperator>(V)) {
    auto A =
        BDP_Range(B->getOperand(0), Context, LVI, Known, Depth + 1, Budget);
    auto C =
        BDP_Range(B->getOperand(1), Context, LVI, Known, Depth + 1, Budget);
    R = R.intersectWith(
        A.binaryOp(static_cast<Instruction::BinaryOps>(B->getOpcode()), C));
  }
  return R;
}
static bool
BDP_Defined(Value *V, Instruction *Context, AssumptionCache &AC,
            DominatorTree &DT, LazyValueInfo &LVI, unsigned Depth = 0,
            const SmallPtrSetImpl<Value *> *Known = nullptr,
            const DenseMap<Value *, ConstantRange> *Ranges = nullptr,
            unsigned *Budget = nullptr) {
  unsigned Local = 64;
  if (!Budget)
    Budget = &Local;
  if (!*Budget)
    return false;
  --*Budget;
  if (Known && Known->contains(V))
    return true;
  if (Depth > 6)
    return false;
  if (isGuaranteedNotToBeUndefOrPoison(V, &AC, Context, &DT))
    return true;
  if (auto *C = dyn_cast<CastInst>(V))
    if (!canCreateUndefOrPoison(cast<Operator>(C)))
      return BDP_Defined(C->getOperand(0), Context, AC, DT, LVI, Depth + 1,
                         Known, Ranges, Budget);
  if (auto *B = dyn_cast<BinaryOperator>(V)) {
    if (!B->getType()->isIntegerTy() ||
        !BDP_Defined(B->getOperand(0), Context, AC, DT, LVI, Depth + 1, Known,
                     Ranges, Budget) ||
        !BDP_Defined(B->getOperand(1), Context, AC, DT, LVI, Depth + 1, Known,
                     Ranges, Budget))
      return false;
    if (B->getOpcode() == Instruction::UDiv) {
      auto *C = dyn_cast<ConstantInt>(B->getOperand(1));
      return C && !C->isZero() && !B->isExact();
    }
    if (B->getOpcode() != Instruction::Add &&
        B->getOpcode() != Instruction::Sub &&
        B->getOpcode() != Instruction::Mul)
      return false;
    auto A = BDP_Range(B->getOperand(0), Context, LVI, Ranges),
         R = BDP_Range(B->getOperand(1), Context, LVI, Ranges);
    if (A.isEmptySet() || R.isEmptySet())
      return false;
    using O = ConstantRange::OverflowResult;
    if (B->hasNoSignedWrap()) {
      if (B->getOpcode() == Instruction::Add &&
          A.signedAddMayOverflow(R) != O::NeverOverflows)
        return false;
      if (B->getOpcode() == Instruction::Sub &&
          A.signedSubMayOverflow(R) != O::NeverOverflows)
        return false;
      if (B->getOpcode() == Instruction::Mul) {
        unsigned W = A.getBitWidth();
        for (APInt X : {A.getSignedMin(), A.getSignedMax()})
          for (APInt Y : {R.getSignedMin(), R.getSignedMax()})
            if (!(X.sext(2 * W) * Y.sext(2 * W)).isSignedIntN(W))
              return false;
      }
    }
    if (B->hasNoUnsignedWrap()) {
      if (B->getOpcode() == Instruction::Add &&
          A.unsignedAddMayOverflow(R) != O::NeverOverflows)
        return false;
      if (B->getOpcode() == Instruction::Sub &&
          A.unsignedSubMayOverflow(R) != O::NeverOverflows)
        return false;
      if (B->getOpcode() == Instruction::Mul &&
          A.unsignedMulMayOverflow(R) != O::NeverOverflows)
        return false;
    }
    return true;
  }
  if (auto *P = dyn_cast<PHINode>(V)) {
    for (unsigned I = 0; I < P->getNumIncomingValues(); ++I)
      if (!BDP_Defined(P->getIncomingValue(I),
                       P->getIncomingBlock(I)->getTerminator(), AC, DT, LVI,
                       Depth + 1, Known, Ranges, Budget))
        return false;
    return true;
  }
  if (auto *S = dyn_cast<SelectInst>(V))
    return BDP_Defined(S->getCondition(), Context, AC, DT, LVI, Depth + 1,
                       Known, Ranges, Budget) &&
           BDP_Defined(S->getTrueValue(), Context, AC, DT, LVI, Depth + 1,
                       Known, Ranges, Budget) &&
           BDP_Defined(S->getFalseValue(), Context, AC, DT, LVI, Depth + 1,
                       Known, Ranges, Budget);
  if (auto *Cmp = dyn_cast<ICmpInst>(V)) {
    if (!Cmp->hasSameSign() ||
        !BDP_Defined(Cmp->getOperand(0), Context, AC, DT, LVI, Depth + 1, Known,
                     Ranges, Budget) ||
        !BDP_Defined(Cmp->getOperand(1), Context, AC, DT, LVI, Depth + 1, Known,
                     Ranges, Budget))
      return false;
    auto A = LVI.getConstantRange(Cmp->getOperand(0), Context, false);
    auto B = LVI.getConstantRange(Cmp->getOperand(1), Context, false);
    if (A.isEmptySet() || B.isEmptySet())
      return false;
    return (A.isAllNonNegative() && B.isAllNonNegative()) ||
           (A.isAllNegative() && B.isAllNegative());
  }
  return false;
}
struct BDP_CounterFact {
  PHINode *P;
  IntrinsicInst *Call;
  ConstantInt *Step;
  APInt Lo, Hi;
};
struct BDP_DivisionFact {
  PHINode *P;
  ConstantInt *Max;
  SmallVector<BDP_CounterFact, 2> Counters;
};
} // namespace
extern "C" unsigned elisacoreBoundedProducts(LLVMModuleRef Ref) {
  if (!Ref)
    return 0;
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
  unsigned Changed = 0, Functions = 0, Loops = 0, GrowthBudget = 0;
  unsigned ProductLoops = 0, ProductCandidates = 0;
  for (Function &F : M) {
    if (BDU_SkipFunction(F, M) ||
        !BDU_MayContainCandidate(F, F.getInstructionCount()))
      continue;
    if (++Functions > 32)
      break;
    auto &LI = FAM.getResult<LoopAnalysis>(F);
    auto &DT = FAM.getResult<DominatorTreeAnalysis>(F);
    auto &AC = FAM.getResult<AssumptionAnalysis>(F);
    auto &LVI = FAM.getResult<LazyValueAnalysis>(F);
    SmallVector<BDP_DivisionFact, 4> Facts;
    for (Loop *L : LI.getLoopsInPreorder()) {
      if (++Loops > 64)
        break;
      BasicBlock *Pred = L->getLoopPredecessor();
      if (!Pred)
        continue;
      auto *Branch = dyn_cast<CondBrInst>(L->getHeader()->getTerminator());
      auto *Cmp = Branch ? dyn_cast<ICmpInst>(Branch->getCondition()) : nullptr;
      if (!Cmp)
        continue;
      for (PHINode &P : L->getHeader()->phis()) {
        if (P.getNumIncomingValues() != 2 || !P.getType()->isIntegerTy() ||
            P.getType()->getIntegerBitWidth() > 128)
          continue;
        int Pre = P.getBasicBlockIndex(Pred);
        if (Pre < 0)
          continue;
        auto *Div = dyn_cast<BinaryOperator>(P.getIncomingValue(1 - Pre));
        if (!Div || Div->getOpcode() != Instruction::UDiv || Div->isExact() ||
            Div->getOperand(0) != &P || !L->contains(Div->getParent()))
          continue;
        auto *C = dyn_cast<ConstantInt>(Div->getOperand(1));
        if (!C || C->getValue().getActiveBits() > 32 || C->getZExtValue() < 2)
          continue;
        Value *Initial = P.getIncomingValue(Pre);
        if (!isGuaranteedNotToBeUndefOrPoison(Initial, &AC,
                                              Pred->getTerminator(), &DT))
          continue;
        auto R = LVI.getConstantRangeOnEdge(Initial, Pred, L->getHeader(),
                                            Pred->getTerminator());
        if (R.isFullSet() || R.isEmptySet())
          continue;
        APInt Maximum = R.getUnsignedMax();
        bool ContinueOnNonzero = false;
        Value *Other =
            Cmp->getOperand(0) == &P
                ? Cmp->getOperand(1)
                : (Cmp->getOperand(1) == &P ? Cmp->getOperand(0) : nullptr);
        auto *Zero = dyn_cast_or_null<ConstantInt>(Other);
        if (Zero && Zero->isZero()) {
          if (Cmp->getPredicate() == ICmpInst::ICMP_EQ &&
              !L->contains(Branch->getSuccessor(0)) &&
              L->contains(Branch->getSuccessor(1)))
            ContinueOnNonzero = true;
          if (Cmp->getPredicate() == ICmpInst::ICMP_NE &&
              L->contains(Branch->getSuccessor(0)) &&
              !L->contains(Branch->getSuccessor(1)))
            ContinueOnNonzero = true;
        }
        if (!ContinueOnNonzero)
          continue;
        unsigned Bound = 0;
        APInt X = Maximum;
        while (!X.isZero() && Bound <= 16) {
          ++Bound;
          X = X.udiv(C->getValue());
        }
        if (!Bound || Bound > 16)
          continue;
        BasicBlock *Continue = L->contains(Branch->getSuccessor(0))
                                   ? Branch->getSuccessor(0)
                                   : Branch->getSuccessor(1);
        BDP_DivisionFact Fact{
            &P, ConstantInt::get(P.getContext(), Maximum), {}};
        for (PHINode &Counter : L->getHeader()->phis()) {
          if (Counter.getNumIncomingValues() != 2 ||
              !Counter.getType()->isIntegerTy() ||
              Counter.getType()->getIntegerBitWidth() > 128)
            continue;
          int CP = Counter.getBasicBlockIndex(Pred);
          if (CP < 0)
            continue;
          auto *E =
              dyn_cast<ExtractValueInst>(Counter.getIncomingValue(1 - CP));
          if (!E || E->getNumIndices() != 1 || *E->idx_begin() != 0)
            continue;
          auto *Call = dyn_cast<IntrinsicInst>(E->getAggregateOperand());
          if (!Call ||
              Call->getIntrinsicID() != Intrinsic::sadd_with_overflow ||
              Call->hasOperandBundles() || Call->isConvergent() ||
              Call->hasMetadataOtherThanDebugLoc() ||
              LI.getLoopFor(Call->getParent()) != L ||
              Call->getParent() == L->getHeader() ||
              !DT.dominates(Continue, Call->getParent()))
            continue;
          // Bound counts continuing body updates. A header call could also
          // execute on the final zero/exit visit and exceed that bound.
          ConstantInt *Step = nullptr;
          for (unsigned I = 0; I < 2; ++I)
            if (Call->getArgOperand(I) == &Counter)
              Step = dyn_cast<ConstantInt>(Call->getArgOperand(1 - I));
          if (!Step)
            continue;
          Value *Start = Counter.getIncomingValue(CP);
          if (!BDP_Defined(Start, Pred->getTerminator(), AC, DT, LVI))
            continue;
          auto CR = LVI.getConstantRangeOnEdge(Start, Pred, L->getHeader(),
                                               Pred->getTerminator());
          if (CR.isFullSet() || CR.isEmptySet())
            continue;
          unsigned Width = Step->getBitWidth();
          APInt Lo = CR.getSignedMin().sext(Width + 6),
                Hi = CR.getSignedMax().sext(Width + 6);
          APInt Delta =
              Step->getValue().sext(Width + 6) * APInt(Width + 6, Bound);
          if (Delta.isNegative())
            Lo += Delta;
          else
            Hi += Delta;
          if (!Lo.isSignedIntN(Width) || !Hi.isSignedIntN(Width))
            continue;
          Fact.Counters.push_back(
              {&Counter, Call, Step, Lo.trunc(Width), Hi.trunc(Width)});
          if (Fact.Counters.size() >= 4)
            break;
        }
        unsigned Growth = 2 + 6 * Fact.Counters.size();
        if (GrowthBudget + Growth > 1024)
          break;
        GrowthBudget += Growth;
        Facts.push_back(std::move(Fact));
        break;
      }
    }
    for (auto &Fact : Facts) {
      IRBuilder<> B(Fact.P->getParent()->getTerminator());
      B.CreateAssumption(B.CreateICmpULE(Fact.P, Fact.Max));
      ++Changed;
      for (auto &CF : Fact.Counters) {
        Value *Off =
            B.CreateSub(CF.P, ConstantInt::get(CF.P->getContext(), CF.Lo));
        B.CreateAssumption(B.CreateICmpULE(
            Off, ConstantInt::get(CF.P->getContext(), CF.Hi - CF.Lo)));
        IRBuilder<> A(CF.Call);
        Value *Sum = A.CreateNSWAdd(CF.P, CF.Step);
        Value *Pair =
            A.CreateInsertValue(PoisonValue::get(CF.Call->getType()), Sum, 0);
        Pair = A.CreateInsertValue(Pair, A.getFalse(), 1);
        CF.Call->replaceAllUsesWith(Pair);
        CF.Call->eraseFromParent();
        ++Changed;
      }
    }
    // The first phase proved these PHIs defined on every reachable header
    // visit. Rebuild analyses after the mutations, retaining only these facts.
    SmallPtrSet<Value *, 16> Known;
    DenseMap<Value *, ConstantRange> KnownRanges;
    for (auto &Fact : Facts) {
      Known.insert(Fact.P);
      KnownRanges.try_emplace(
          Fact.P, ConstantRange::getNonEmpty(APInt(Fact.Max->getBitWidth(), 0),
                                             Fact.Max->getValue() + 1));
      for (auto &CF : Fact.Counters) {
        Known.insert(CF.P);
        KnownRanges.try_emplace(CF.P,
                                ConstantRange::getNonEmpty(CF.Lo, CF.Hi + 1));
      }
    }
    if (Facts.empty())
      continue;
    FAM.invalidate(F, PreservedAnalyses::none());
    auto &PL = FAM.getResult<LoopAnalysis>(F);
    auto &PD = FAM.getResult<DominatorTreeAnalysis>(F);
    auto &PA = FAM.getResult<AssumptionAnalysis>(F);
    auto &PV = FAM.getResult<LazyValueAnalysis>(F);
    auto &PS = FAM.getResult<ScalarEvolutionAnalysis>(F);
    struct ProductFact {
      BinaryOperator *Mul;
      FreezeInst *Freeze;
      Value *Base;
      SmallVector<IntrinsicInst *, 2> Calls;
    };
    SmallVector<ProductFact, 4> Products;
    for (Loop *L : PL.getLoopsInPreorder()) {
      if (++ProductLoops > 64 || ProductCandidates >= 64)
        break;
      if (!L->getSubLoops().empty())
        continue;
      BasicBlock *Pre = L->getLoopPredecessor(), *Latch = L->getLoopLatch();
      if (!Pre || !Latch)
        continue;
      auto *B = dyn_cast<CondBrInst>(Latch->getTerminator());
      auto *Cmp = B ? dyn_cast<ICmpInst>(B->getCondition()) : nullptr;
      if (!Cmp)
        continue;
      bool EqExit = Cmp->getPredicate() == ICmpInst::ICMP_EQ &&
                    !L->contains(B->getSuccessor(0)) &&
                    B->getSuccessor(1) == L->getHeader();
      bool NeExit = Cmp->getPredicate() == ICmpInst::ICMP_NE &&
                    !L->contains(B->getSuccessor(1)) &&
                    B->getSuccessor(0) == L->getHeader();
      if (!EqExit && !NeExit)
        continue;
      Value *Limit = nullptr;
      for (PHINode &I : L->getHeader()->phis()) {
        if (I.getNumIncomingValues() != 2 || !I.getType()->isIntegerTy())
          continue;
        int A = I.getBasicBlockIndex(Pre);
        if (A < 0)
          continue;
        auto *Start = dyn_cast<ConstantInt>(I.getIncomingValue(A));
        auto *Inc = dyn_cast<BinaryOperator>(I.getIncomingValue(1 - A));
        if (!Start || !Start->isZero() || !Inc ||
            Inc->getOpcode() != Instruction::Add || Inc->getOperand(0) != &I ||
            Inc->getParent() != Latch)
          continue;
        auto *One = dyn_cast<ConstantInt>(Inc->getOperand(1));
        if (!One || !One->isOne())
          continue;
        Value *V =
            Cmp->getOperand(0) == Inc
                ? Cmp->getOperand(1)
                : (Cmp->getOperand(1) == Inc ? Cmp->getOperand(0) : nullptr);
        if (V && L->isLoopInvariant(V)) {
          Limit = V;
          break;
        }
      }
      if (!Limit || !BDP_Defined(Limit, Pre->getTerminator(), PA, PD, PV, 0,
                                 &Known, &KnownRanges))
        continue;
      auto LR = PV.getConstantRangeOnEdge(Limit, Pre, L->getHeader(),
                                          Pre->getTerminator());
      if (auto It = KnownRanges.find(Limit); It != KnownRanges.end())
        LR = LR.intersectWith(It->second);
      if (LR.isEmptySet() || LR.getSignedMin().sle(0) ||
          LR.getUnsignedMax().ugt(16))
        continue;
      unsigned Bound = LR.getUnsignedMax().getZExtValue();
      for (PHINode &Power : L->getHeader()->phis()) {
        if (!Power.getType()->isIntegerTy() ||
            Power.getType()->getIntegerBitWidth() > 128 ||
            Power.getNumIncomingValues() != 2)
          continue;
        int A = Power.getBasicBlockIndex(Pre);
        if (A < 0)
          continue;
        auto *Start = dyn_cast<ConstantInt>(Power.getIncomingValue(A));
        auto *Mul = dyn_cast<BinaryOperator>(Power.getIncomingValue(1 - A));
        if (!Start || !Mul || Mul->getOpcode() != Instruction::Mul ||
            Mul->hasNoUnsignedWrap() || PL.getLoopFor(Mul->getParent()) != L)
          continue;
        if (++ProductCandidates > 64)
          break;
        Value *Operand =
            Mul->getOperand(0) == &Power
                ? Mul->getOperand(1)
                : (Mul->getOperand(1) == &Power ? Mul->getOperand(0) : nullptr);
        if (!Operand)
          continue;
        auto *Freeze = dyn_cast<FreezeInst>(Operand);
        Value *Base = Freeze ? Freeze->getOperand(0) : Operand;
        if (!L->isLoopInvariant(Base) ||
            !BDP_Defined(Base, Mul, PA, PD, PV, 0, &Known, &KnownRanges))
          continue;
        auto BR = PS.getUnsignedRange(PS.getSCEV(Base));
        if (BR.isEmptySet() || BR.isFullSet())
          continue;
        unsigned W = Start->getBitWidth();
        APInt Lo = Start->getValue(), Hi = Lo;
        APInt BL = BR.getSignedMin().sext(2 * W),
              BH = BR.getSignedMax().sext(2 * W);
        bool Safe = true;
        // A W-bit signed product fits in 2W bits. Check all endpoint products
        // before truncating so the interval never silently wraps.
        for (unsigned I = 0; I < Bound; ++I) {
          APInt X = Lo.sext(2 * W) * BL, Y = Lo.sext(2 * W) * BH,
                Z = Hi.sext(2 * W) * BL, T = Hi.sext(2 * W) * BH;
          APInt Min = X, Max = X;
          for (const APInt *V : {&Y, &Z, &T}) {
            if (V->slt(Min))
              Min = *V;
            if (V->sgt(Max))
              Max = *V;
          }
          if (!Min.isSignedIntN(W) || !Max.isSignedIntN(W)) {
            Safe = false;
            break;
          }
          Lo = Min.trunc(W);
          Hi = Max.trunc(W);
        }
        if (!Safe)
          continue;
        // Definedness was proved at Mul. Other freeze users may execute on a
        // path where that contextual proof does not hold; retain the freeze
        // there.
        bool RemoveFreeze = true;
        if (Freeze)
          for (User *U : Freeze->users()) {
            auto *I = dyn_cast<Instruction>(U);
            if (!I || !PD.dominates(Mul, I))
              RemoveFreeze = false;
          }
        ProductFact Fact{Mul, RemoveFreeze ? Freeze : nullptr, Base, {}};
        for (BasicBlock *BB : L->blocks())
          for (Instruction &I : *BB) {
            auto *C = dyn_cast<IntrinsicInst>(&I);
            if (!C || C->getIntrinsicID() != Intrinsic::smul_with_overflow ||
                C->hasOperandBundles() || C->isConvergent())
              continue;
            bool Same = (C->getArgOperand(0) == &Power &&
                         C->getArgOperand(1) == Operand) ||
                        (C->getArgOperand(1) == &Power &&
                         C->getArgOperand(0) == Operand);
            if (Same && PD.dominates(Mul, C)) {
              SmallVector<std::pair<unsigned, MDNode *>, 4> Metadata;
              C->getAllMetadataOtherThanDebugLoc(Metadata);
              bool SafeMetadata = true;
              for (auto &MD : Metadata)
                if (MD.first !=
                    M.getContext().getMDKindID("elisa.checkedmul.slow"))
                  SafeMetadata = false;
              if (SafeMetadata)
                Fact.Calls.push_back(C);
            }
          }
        unsigned Growth = 2 * Fact.Calls.size();
        if (!Fact.Calls.empty() && GrowthBudget + Growth <= 1024) {
          GrowthBudget += Growth;
          Products.push_back(std::move(Fact));
        }
      }
    }
    SmallPtrSet<FreezeInst *, 8> Freezes;
    for (auto &Fact : Products) {
      Fact.Mul->setHasNoSignedWrap(true);
      for (auto *C : Fact.Calls) {
        IRBuilder<> B(C);
        Value *V =
            B.CreateInsertValue(PoisonValue::get(C->getType()), Fact.Mul, 0);
        V = B.CreateInsertValue(V, B.getFalse(), 1);
        C->replaceAllUsesWith(V);
        C->eraseFromParent();
        ++Changed;
      }
      if (Fact.Freeze)
        Freezes.insert(Fact.Freeze);
    }

    for (FreezeInst *FI : Freezes)
      FI->replaceAllUsesWith(FI->getOperand(0));
    for (FreezeInst *FI : Freezes)
      FI->eraseFromParent();
  }
  return Changed;
}

#else
extern "C" unsigned elisacoreBoundedProducts(LLVMModuleRef) { return 0; }
#endif
