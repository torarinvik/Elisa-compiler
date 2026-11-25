// The guard facts dominating an instruction, for the array value ranges
// (llvm_array_value_ranges.h). The signed-check prover that also used them
// is ported to Elisa (llvm_passes/late_cleanup/signed_checks/guard_facts.elisa).
namespace ElisaCheckedSignedRanges {
using Facts = DenseMap<Value *, ConstantRange>;

// A value computed only from constants and from instructions that compute
// one, so every use of it sees the same value: no argument, load or call.
static bool neverUndefined(Value *Root) {
  SmallVector<Value *, 8> Work{Root};
  SmallPtrSet<Value *, 16> Seen;
  while (!Work.empty()) {
    Value *Current = Work.pop_back_val();
    if (!Seen.insert(Current).second) continue;
    if (Seen.size() > 32) return false;
    if (isa<ConstantInt>(Current)) continue;
    // A checked operation's result: the operation on defined operands.
    if (auto *Field = dyn_cast<ExtractValueInst>(Current)) {
      auto *Checked = dyn_cast<WithOverflowInst>(Field->getAggregateOperand());
      if (!Checked || Field->getNumIndices() != 1 || Field->getIndices()[0] != 0) return false;
      Work.append({Checked->getLHS(), Checked->getRHS()});
      continue;
    }
    if (!isa<PHINode, BinaryOperator, CastInst, SelectInst, ICmpInst, FreezeInst>(Current))
      return false;
    if (isa<FreezeInst>(Current)) continue;
    for (Value *Operand : cast<Instruction>(Current)->operands()) Work.push_back(Operand);
  }
  return true;
}


// Walk backwards from the definition. A forward search from the accepted
// edge would traverse the entire optimized loop nest.
static bool mayReexecute(BasicBlock &Definition, BasicBlock &EdgeTarget) {
  SmallVector<BasicBlock *, 16> Pending{&Definition};
  SmallPtrSet<BasicBlock *, 32> Visited;
  while (!Pending.empty()) {
    BasicBlock *Block = Pending.pop_back_val();
    if (!Visited.insert(Block).second) continue;
    if (Block == &EdgeTarget || Visited.size() > 256) return true;
    for (BasicBlock *Predecessor : predecessors(Block))
      if (!Visited.contains(Predecessor)) Pending.push_back(Predecessor);
  }
  return false;
}

static bool isStable(Value *Input, Instruction &At, BasicBlock &EdgeTarget,
                     DominatorTree &Tree, AssumptionCache &Assumptions) {
  auto *Definition = dyn_cast<Instruction>(Input);
  if (Definition &&
      mayReexecute(*Definition->getParent(), EdgeTarget))
    return false;
  if (auto *Field = dyn_cast<ExtractValueInst>(Input))
    if (isa<FreezeInst>(Field->getAggregateOperand())) return true;
  return isGuaranteedNotToBeUndefOrPoison(Input, &Assumptions, &At, &Tree);
}

static void collect(Value *Condition, bool Taken, Instruction &At,
                    BasicBlock &EdgeTarget, DominatorTree &Tree,
                    AssumptionCache &Assumptions, Facts &Bounds,
                    unsigned &Budget,
                    SmallPtrSetImpl<LoadInst *> *UnstableLoads,
                    SmallPtrSetImpl<Argument *> *FrozenArguments = nullptr,
                    Value *Only = nullptr) {
  if (!Budget) return;
  --Budget;
  auto Visit = [&](Value *Operand, bool Truth) {
    collect(Operand, Truth, At, EdgeTarget, Tree, Assumptions, Bounds, Budget, UnstableLoads,
            FrozenArguments, Only);
  };
  if (auto *Either = dyn_cast<BinaryOperator>(Condition)) {
    if ((Either->getOpcode() == Instruction::Or && !Taken) ||
        (Either->getOpcode() == Instruction::And && Taken))
      for (Value *Operand : Either->operands()) Visit(Operand, Taken);
    return;
  }
  if (auto *Choice = dyn_cast<SelectInst>(Condition)) {
    if (auto *True = dyn_cast<ConstantInt>(Choice->getTrueValue());
        True && True->isOne() != Taken) {
      Visit(Choice->getCondition(), false);
      Visit(Choice->getFalseValue(), Taken);
    } else if (auto *False = dyn_cast<ConstantInt>(Choice->getFalseValue());
               False && False->isOne() != Taken) {
      Visit(Choice->getCondition(), true);
      Visit(Choice->getTrueValue(), Taken);
    }
    return;
  }

  auto *Compare = dyn_cast<ICmpInst>(Condition);
  if (!Compare) return;
  auto *Limit = dyn_cast<ConstantInt>(Compare->getOperand(1));
  if (!Limit) return;
  Value *Input = Compare->getOperand(0);
  auto Predicate = Taken ? Compare->getPredicate() : Compare->getInversePredicate();
  ConstantRange Range = ConstantRange::makeExactICmpRegion(Predicate, Limit->getValue());
  if (auto *Add = dyn_cast<BinaryOperator>(Input);
      Add && Add->getOpcode() == Instruction::Add) {
    if (auto *Offset = dyn_cast<ConstantInt>(Add->getOperand(1))) {
      Range = Range.sub(ConstantRange(Offset->getValue()));
      Input = Add->getOperand(0);
    }
  }
  if (auto *Absolute = dyn_cast<IntrinsicInst>(Input);
      Absolute && Absolute->getIntrinsicID() == Intrinsic::abs &&
      Predicate == ICmpInst::ICMP_ULE && !Limit->isNegative() &&
      !Limit->getValue().isMaxSignedValue()) {
    APInt Bound = Limit->getValue();
    Input = Absolute->getArgOperand(0);
    Range = ConstantRange(-Bound, Bound + 1);
  }
  // Read only where the edge dominates (directFact): the last definition of
  // the value before that point dominates the guard, so the guard tested it.
  // A parameter must be frozen, and other values cannot be undefined.
  if (Only) {
    if (Input != Only) return;
    if (auto *Parameter = dyn_cast<Argument>(Input)) {
      if (!isStable(Input, At, EdgeTarget, Tree, Assumptions)) {
        if (!FrozenArguments) return;
        FrozenArguments->insert(Parameter);
      }
    } else if (!neverUndefined(Input)) {
      return;
    }
    auto [Fact, Inserted] = Bounds.try_emplace(Input, Range);
    if (!Inserted) Fact->second = Fact->second.intersectWith(Range);
    return;
  }
  // A parameter is defined once, at entry; freezing it there (when a proof
  // uses this fact) gives the guard and every later use the same value.
  if (auto *Parameter = dyn_cast<Argument>(Input);
      Parameter && FrozenArguments && !isStable(Input, At, EdgeTarget, Tree, Assumptions))
    FrozenArguments->insert(Parameter);
  else if (!isStable(Input, At, EdgeTarget, Tree, Assumptions)) {
    auto *Load = dyn_cast<LoadInst>(Input);
    if (UnstableLoads && Load && Load->getType()->isIntegerTy(32) &&
        Load->isSimple() && !Range.isEmptySet() &&
        Range.getSignedMin().sge(-32) && Range.getSignedMax().sle(32) &&
        !mayReexecute(*Load->getParent(), EdgeTarget))
      UnstableLoads->insert(Load);
    return;
  }
  auto [Fact, Inserted] = Bounds.try_emplace(Input, Range);
  if (!Inserted) Fact->second = Fact->second.intersectWith(Range);
}

static Facts dominatingBounds(Instruction &Call, DominatorTree &Tree,
                              AssumptionCache &Assumptions, const Facts &Incoming,
                              SmallPtrSetImpl<LoadInst *> *UnstableLoads = nullptr,
                              SmallPtrSetImpl<Argument *> *FrozenArguments = nullptr) {
  Facts Bounds = Incoming;
  unsigned Budget = 96;
  for (auto *Node = Tree.getNode(Call.getParent()); Node && Budget;
       Node = Node->getIDom()) {
    BasicBlock *Block = Node->getBlock();
    auto *Branch = dyn_cast<CondBrInst>(Block->getTerminator());
    if (!Branch || Branch->getSuccessor(0) == Branch->getSuccessor(1)) continue;
    for (unsigned Edge = 0; Edge < 2; ++Edge) {
      auto *Target = Branch->getSuccessor(Edge);
      if (Tree.dominates(BasicBlockEdge(Block, Target), Call.getParent()))
        collect(Branch->getCondition(), Edge == 0, *Branch, *Target, Tree,
                Assumptions, Bounds, Budget, UnstableLoads, FrozenArguments);
    }
  }
  return Bounds;
}
} // namespace ElisaCheckedSignedRanges
