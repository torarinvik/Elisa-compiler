// When an earlier unsigned upper bound excludes negative limits, the
// signed tests "value < 0 or value > limit" are one unsigned comparison.
static bool comparesNegative(Value *Condition, Value *ValueToCheck) {
  auto *Compare = dyn_cast<ICmpInst>(Condition);
  if (!Compare) return false;
  auto Predicate = Compare->getPredicate();
  auto *Zero = dyn_cast<ConstantInt>(Compare->getOperand(1));
  if (Zero && Zero->isZero())
    return Predicate == ICmpInst::ICMP_SLT &&
           Compare->getOperand(0) == ValueToCheck;
  Zero = dyn_cast<ConstantInt>(Compare->getOperand(0));
  return Zero && Zero->isZero() && Predicate == ICmpInst::ICMP_SGT &&
         Compare->getOperand(1) == ValueToCheck;
}

static Value *valueAboveSignedLimit(Value *Condition, Value *Limit) {
  auto *Compare = dyn_cast<ICmpInst>(Condition);
  if (!Compare) return nullptr;
  if (Compare->getPredicate() == ICmpInst::ICMP_SGT &&
      Compare->getOperand(1) == Limit)
    return Compare->getOperand(0);
  if (Compare->getPredicate() == ICmpInst::ICMP_SLT &&
      Compare->getOperand(0) == Limit)
    return Compare->getOperand(1);
  return nullptr;
}

static void foldGuardedUnsignedComparisons(Module &Module) {
  if (!Module.getTargetTriple().isAArch64()) return;
  for (auto &Function : Module)
    for (auto &Block : Function)
      for (auto &Instruction : Block) {
        auto *Select = dyn_cast<SelectInst>(&Instruction);
        if (!Select || !Select->getType()->isIntegerTy(1)) continue;
        auto *Reject = dyn_cast<ConstantInt>(Select->getTrueValue());
        auto *Guard = dyn_cast<ICmpInst>(Select->getCondition());
        auto *Either = dyn_cast<BinaryOperator>(Select->getFalseValue());
        if (!Reject || !Reject->isOne() || !Guard ||
            Guard->getPredicate() != ICmpInst::ICMP_UGT ||
            !Either || Either->getOpcode() != Instruction::Or)
          continue;
        auto *Upper = dyn_cast<ConstantInt>(Guard->getOperand(1));
        if (!Upper || Upper->isNegative()) continue;

        Value *Limit = Guard->getOperand(0);
        for (unsigned Index = 0; Index < 2; ++Index) {
          Value *Input = valueAboveSignedLimit(Either->getOperand(Index), Limit);
          if (!Input || !comparesNegative(Either->getOperand(1 - Index), Input))
            continue;
          IRBuilder<> Builder(Select);
          Select->setFalseValue(Builder.CreateICmpUGT(Input, Limit));
          RecursivelyDeleteTriviallyDeadInstructions(Either);
          break;
        }
      }
}
