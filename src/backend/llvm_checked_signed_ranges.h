// Propagate dominating validation ranges into checked signed arithmetic.
namespace ElisaCheckedSignedRanges {
using Facts = DenseMap<Value *, ConstantRange>;

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
                    unsigned &Budget) {
  if (!Budget) return;
  --Budget;
  auto Visit = [&](Value *Operand, bool Truth) {
    collect(Operand, Truth, At, EdgeTarget, Tree, Assumptions, Bounds, Budget);
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
  if (!isStable(Input, At, EdgeTarget, Tree, Assumptions)) return;
  auto [Fact, Inserted] = Bounds.try_emplace(Input, Range);
  if (!Inserted) Fact->second = Fact->second.intersectWith(Range);
}

static std::optional<Instruction::BinaryOps> checkedOpcode(Intrinsic::ID ID) {
  switch (ID) {
  case Intrinsic::sadd_with_overflow: return Instruction::Add;
  case Intrinsic::ssub_with_overflow: return Instruction::Sub;
  case Intrinsic::smul_with_overflow: return Instruction::Mul;
  default: return std::nullopt;
  }
}

static ConstantRange rangeOf(Value *ValueToCheck, const Facts &Bounds,
                             ScalarEvolution &Evolution, unsigned &Budget,
                             unsigned Depth = 0) {
  unsigned Width = ValueToCheck->getType()->getIntegerBitWidth();
  if (!Budget || Depth == 8) return ConstantRange::getFull(Width);
  --Budget;
  if (auto Fact = Bounds.find(ValueToCheck); Fact != Bounds.end())
    return Fact->second;
  if (auto *Constant = dyn_cast<ConstantInt>(ValueToCheck))
    return ConstantRange(Constant->getValue());

  auto Recurse = [&](Value *Operand) {
    return rangeOf(Operand, Bounds, Evolution, Budget, Depth + 1);
  };
  if (auto *Cast = dyn_cast<CastInst>(ValueToCheck);
      Cast && Cast->getSrcTy()->isIntegerTy())
    return Recurse(Cast->getOperand(0)).castOp(Cast->getOpcode(), Width);

  if (auto *Binary = dyn_cast<BinaryOperator>(ValueToCheck)) {
    auto Opcode = Binary->getOpcode();
    if (Opcode == Instruction::Add || Opcode == Instruction::Sub ||
        Opcode == Instruction::Mul)
      return Recurse(Binary->getOperand(0)).binaryOp(
          Opcode, Recurse(Binary->getOperand(1)));
  }
  if (auto *Field = dyn_cast<ExtractValueInst>(ValueToCheck);
      Field && Field->getNumIndices() == 1 && *Field->idx_begin() == 0)
    if (auto *Call = dyn_cast<IntrinsicInst>(Field->getAggregateOperand()))
      if (auto Opcode = checkedOpcode(Call->getIntrinsicID()))
        return Recurse(Call->getArgOperand(0)).binaryOp(
            *Opcode, Recurse(Call->getArgOperand(1)));
  return Evolution.getSignedRange(Evolution.getSCEV(ValueToCheck));
}

static bool cannotOverflow(Instruction::BinaryOps Opcode,
                           const ConstantRange &Left,
                           const ConstantRange &Right) {
  using Result = ConstantRange::OverflowResult;
  if (Left.isEmptySet() || Right.isEmptySet()) return false;
  if (Opcode == Instruction::Add)
    return Left.signedAddMayOverflow(Right) == Result::NeverOverflows;
  if (Opcode == Instruction::Sub)
    return Left.signedSubMayOverflow(Right) == Result::NeverOverflows;
  unsigned Width = Left.getBitWidth();
  for (const APInt &A : {Left.getSignedMin(), Left.getSignedMax()})
    for (const APInt &B : {Right.getSignedMin(), Right.getSignedMax()})
      if (!(A.sext(2 * Width) * B.sext(2 * Width)).isSignedIntN(Width))
        return false;
  return true;
}

static Facts dominatingBounds(IntrinsicInst &Call, DominatorTree &Tree,
                              AssumptionCache &Assumptions) {
  Facts Bounds;
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
                Assumptions, Bounds, Budget);
    }
  }
  return Bounds;
}
} // namespace ElisaCheckedSignedRanges

static unsigned foldProvenSignedChecks(Module &Module) {
  using namespace ElisaCheckedSignedRanges;
  if (!Module.getTargetTriple().isAArch64()) return 0;
  FunctionAnalysisManager Analyses;
  PassBuilder Builder;
  Builder.registerFunctionAnalyses(Analyses);
  unsigned Changes = 0;
  for (Function &Function : Module) {
    if (Function.isDeclaration() || Function.hasOptNone() ||
        Function.getInstructionCount() > 1200)
      continue;
    SmallVector<IntrinsicInst *, 16> Candidates;
    for (Instruction &Instruction : instructions(Function))
      if (auto *Call = dyn_cast<IntrinsicInst>(&Instruction);
          Call && checkedOpcode(Call->getIntrinsicID()) &&
          Call->getArgOperand(0)->getType()->isIntegerTy(64))
        Candidates.push_back(Call);
    if (Candidates.empty() || Candidates.size() > 64) continue;
    auto &Tree = Analyses.getResult<DominatorTreeAnalysis>(Function);
    auto &Assumptions = Analyses.getResult<AssumptionAnalysis>(Function);
    auto &Evolution = Analyses.getResult<ScalarEvolutionAnalysis>(Function);
    SmallVector<IntrinsicInst *, 16> Safe;
    for (IntrinsicInst *Call : Candidates) {
      auto Bounds = dominatingBounds(*Call, Tree, Assumptions);
      if (Bounds.empty()) continue;
      unsigned Budget = 64;
      auto Left = rangeOf(Call->getArgOperand(0), Bounds, Evolution, Budget);
      auto Right = rangeOf(Call->getArgOperand(1), Bounds, Evolution, Budget);
      if (cannotOverflow(*checkedOpcode(Call->getIntrinsicID()), Left, Right))
        Safe.push_back(Call);
    }
    for (IntrinsicInst *Call : Safe) {
      IRBuilder<> Builder(Call);
      Value *Result = Builder.CreateBinOp(*checkedOpcode(Call->getIntrinsicID()),
                                          Call->getArgOperand(0), Call->getArgOperand(1));
      Value *Pair = Builder.CreateInsertValue(PoisonValue::get(Call->getType()), Result, 0);
      Pair = Builder.CreateInsertValue(Pair, Builder.getFalse(), 1);
      Call->replaceAllUsesWith(Pair);
      Call->eraseFromParent();
      ++Changes;
    }
    Analyses.invalidate(Function, PreservedAnalyses::none());
  }
  return Changes;
}
