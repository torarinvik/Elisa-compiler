// A positive signed W-bit value divided by B >= 2 reaches zero in at
// most W-1 iterations. Each remainder is in [0,B-1], so a zero-based
// accumulator is bounded by (W-1)*(B-1). The recognizer checks the exact
// PHI recurrences, positive header guard, and signed maximum before elision.
// Other initializers, divisors, guards and update shapes retain their checks.
namespace {
struct DigitBound : PassInfoMixin<DigitBound> {
  PreservedAnalyses run(Function &F, FunctionAnalysisManager &AM) {
    auto &LI = AM.getResult<LoopAnalysis>(F);
    auto &DT = AM.getResult<DominatorTreeAnalysis>(F);
    SmallVector<Loop *, 16> work;
    for (auto *L : LI)
      work.push_back(L);
    bool changed = false;
    while (!work.empty()) {
      Loop *L = work.pop_back_val();
      for (auto *S : *L)
        work.push_back(S);
      BasicBlock *H = L->getHeader(), *P = L->getLoopPreheader(),
                 *B = L->getLoopLatch();
      if (!P || !B)
        continue;
      auto *br = dyn_cast<BranchInst>(H->getTerminator());
      if (!br || !br->isConditional())
        continue;
      auto *cmp = dyn_cast<ICmpInst>(br->getCondition());
      if (!cmp || cmp->getPredicate() != ICmpInst::ICMP_SGT)
        continue;
      auto *n = dyn_cast<PHINode>(cmp->getOperand(0));
      auto *zero = dyn_cast<ConstantInt>(cmp->getOperand(1));
      if (!n || n->getParent() != H || !zero || !zero->isZero() ||
          n->getNumIncomingValues() != 2)
        continue;
      auto *ty = dyn_cast<IntegerType>(n->getType());
      if (!ty || ty->getBitWidth() < 3 || ty->getBitWidth() > 64)
        continue;
      auto *div = dyn_cast<BinaryOperator>(n->getIncomingValueForBlock(B));
      if (!div || div->getOpcode() != Instruction::SDiv ||
          div->getOperand(0) != n || !L->contains(div))
        continue;
      auto *base = dyn_cast<ConstantInt>(div->getOperand(1));
      if (!base || base->isNegative() || base->getValue().ult(2))
        continue;
      uint64_t limit =
          APInt::getSignedMaxValue(ty->getBitWidth()).getZExtValue();
      uint64_t b = base->getZExtValue();
      if (b - 1 > limit / (ty->getBitWidth() - 1))
        continue;
      for (PHINode &total : H->phis()) {
        if (total.getType() != ty || total.getNumIncomingValues() != 2)
          continue;
        auto *init = dyn_cast<ConstantInt>(total.getIncomingValueForBlock(P));
        auto *value =
            dyn_cast<ExtractValueInst>(total.getIncomingValueForBlock(B));
        if (!init || !init->isZero() || !value || value->getNumIndices() != 1 ||
            *value->idx_begin() != 0)
          continue;
        auto *call = dyn_cast<IntrinsicInst>(value->getAggregateOperand());
        if (!call || call->getIntrinsicID() != Intrinsic::sadd_with_overflow ||
            !L->contains(call) || call->getParent() == H ||
            br->getSuccessor(0) == H ||
            !DT.dominates(br->getSuccessor(0), call->getParent()) ||
            L->contains(br->getSuccessor(1)))
          continue;
        Value *other = nullptr;
        if (call->getArgOperand(0) == &total)
          other = call->getArgOperand(1);
        else if (call->getArgOperand(1) == &total)
          other = call->getArgOperand(0);
        auto *rem = dyn_cast_or_null<BinaryOperator>(other);
        if (!rem || rem->getOpcode() != Instruction::SRem ||
            rem->getOperand(0) != n || rem->getOperand(1) != base)
          continue;
        IRBuilder<> builder(call);
        Value *sum = builder.CreateAdd(
            call->getArgOperand(0), call->getArgOperand(1), "proved.digit.sum");
        Value *result = PoisonValue::get(call->getType());
        result = builder.CreateInsertValue(result, sum, 0);
        result = builder.CreateInsertValue(result, builder.getFalse(), 1);
        call->replaceAllUsesWith(result);
        call->eraseFromParent();
        changed = true;
        break;
      }
    }
    return changed ? PreservedAnalyses::none() : PreservedAnalyses::all();
  }
};
} // namespace

extern "C" unsigned elisacoreElideBoundedDivisionSums(LLVMModuleRef moduleRef) {
  if (!moduleRef)
    return 0;
  Module &M = *unwrap(moduleRef);
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
  unsigned candidates = 0;
  for (Function &F : M) {
    if (F.isDeclaration() || F.hasOptNone() || F.hasOptSize() || F.hasMinSize())
      continue;
    bool div = false, rem = false, add = false;
    for (BasicBlock &B : F)
      for (Instruction &I : B) {
        div |= I.getOpcode() == Instruction::SDiv;
        rem |= I.getOpcode() == Instruction::SRem;
        if (auto *C = dyn_cast<IntrinsicInst>(&I))
          add |= C->getIntrinsicID() == Intrinsic::sadd_with_overflow;
      }
    if (!(div && rem && add))
      continue;
    FunctionPassManager FPM;
    FPM.addPass(PromotePass());
    FPM.addPass(LoopSimplifyPass());
    FPM.addPass(DigitBound());
    FPM.run(F, FAM);
    ++candidates;
  }
  return candidates;
}
