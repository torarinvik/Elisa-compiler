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
                    unsigned &Budget,
                    SmallPtrSetImpl<LoadInst *> *UnstableLoads) {
  if (!Budget) return;
  --Budget;
  auto Visit = [&](Value *Operand, bool Truth) {
    collect(Operand, Truth, At, EdgeTarget, Tree, Assumptions, Bounds, Budget, UnstableLoads);
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
  if (!isStable(Input, At, EdgeTarget, Tree, Assumptions)) {
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

static std::optional<Instruction::BinaryOps> checkedOpcode(Intrinsic::ID ID) {
  switch (ID) {
  case Intrinsic::sadd_with_overflow: return Instruction::Add;
  case Intrinsic::ssub_with_overflow: return Instruction::Sub;
  case Intrinsic::smul_with_overflow: return Instruction::Mul;
  default: return std::nullopt;
  }
}

// A zero-based counter tested after increment visits [0, limit) when
// the equality exit compares against one stable, positive limit.
static Value *countedLoopLimit(PHINode &Counter, LoopInfo &Loops) {
  Loop *Loop = Loops.getLoopFor(Counter.getParent());
  if (!Loop || Loop->getHeader() != Counter.getParent() ||
      Counter.getNumIncomingValues() != 2)
    return nullptr;
  BasicBlock *Latch = Loop->getLoopLatch();
  BasicBlock *Entry = Loop->getLoopPredecessor();
  if (!Latch || !Entry) return nullptr;
  auto *Initial = dyn_cast<ConstantInt>(Counter.getIncomingValueForBlock(Entry));
  auto *Next = dyn_cast<BinaryOperator>(Counter.getIncomingValueForBlock(Latch));
  auto *Branch = dyn_cast<CondBrInst>(Latch->getTerminator());
  if (!Initial || !Initial->isZero() || !Next ||
      Next->getOpcode() != Instruction::Add || Next->getOperand(0) != &Counter ||
      !Branch || Branch->getSuccessor(1) != Loop->getHeader() ||
      Loop->contains(Branch->getSuccessor(0)))
    return nullptr;
  auto *Step = dyn_cast<ConstantInt>(Next->getOperand(1));
  auto *Compare = dyn_cast<ICmpInst>(Branch->getCondition());
  if (!Step || !Step->isOne() || !Compare ||
      Compare->getPredicate() != ICmpInst::ICMP_EQ)
    return nullptr;
  Value *Limit = Compare->getOperand(0) == Next ? Compare->getOperand(1)
                 : Compare->getOperand(1) == Next ? Compare->getOperand(0)
                                                 : nullptr;
  if (!Limit || !Loop->isLoopInvariant(Limit)) return nullptr;

  Value *Stable = Limit;
  while (isa<SExtInst, ZExtInst>(Stable))
    Stable = cast<CastInst>(Stable)->getOperand(0);
  return isa<FreezeInst, ConstantInt>(Stable) ? Limit : nullptr;
}

static ConstantRange rangeOf(Value *ValueToCheck, const Facts &Bounds,
                             ScalarEvolution &Evolution, LoopInfo &Loops, unsigned &Budget,
                             unsigned Depth = 0) {
  unsigned Width = ValueToCheck->getType()->getIntegerBitWidth();
  if (!Budget || Depth == 8) return ConstantRange::getFull(Width);
  --Budget;
  if (auto Fact = Bounds.find(ValueToCheck); Fact != Bounds.end())
    return Fact->second;
  if (auto *Constant = dyn_cast<ConstantInt>(ValueToCheck))
    return ConstantRange(Constant->getValue());

  auto Recurse = [&](Value *Operand) {
    return rangeOf(Operand, Bounds, Evolution, Loops, Budget, Depth + 1);
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
  if (auto *Counter = dyn_cast<PHINode>(ValueToCheck))
    if (Value *Limit = countedLoopLimit(*Counter, Loops)) {
      auto Range = Recurse(Limit);
      if (!Range.isEmptySet() && Range.getSignedMin().isStrictlyPositive())
        return ConstantRange(APInt(Width, 0), Range.getSignedMax());
    }
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

// A private helper can use ranges common to all of its direct callers.
static Facts incomingFieldBounds(Function &Function) {
  Facts Bounds;
  if (!Function.hasLocalLinkage() || Function.use_empty() ||
      Function.getNumUses() > 8)
    return Bounds;

  SmallVector<CallBase *, 8> Callers;
  for (Use &Use : Function.uses()) {
    auto *Call = dyn_cast<CallBase>(Use.getUser());
    if (!Call || &Use != &Call->getCalledOperandUse() ||
        Call->getFunctionType() != Function.getFunctionType())
      return Facts();
    Callers.push_back(Call);
  }

  for (Instruction &Instruction : Function.getEntryBlock()) {
    auto *Field = dyn_cast<ExtractValueInst>(&Instruction);
    if (!Field || !Field->getType()->isIntegerTy(64)) continue;
    auto *Argument = dyn_cast<llvm::Argument>(Field->getAggregateOperand());
    if (!Argument) continue;

    ConstantRange Combined = ConstantRange::getEmpty(64);
    for (CallBase *Call : Callers) {
      Value *Actual = FindInsertedValue(Call->getArgOperand(Argument->getArgNo()),
                                       Field->getIndices());
      if (auto *Constant = dyn_cast_or_null<ConstantInt>(Actual)) {
        Combined = Combined.unionWith(ConstantRange(Constant->getValue()));
      } else if (auto *Extend = dyn_cast_or_null<SExtInst>(Actual)) {
        unsigned Width = Extend->getSrcTy()->getIntegerBitWidth();
        Combined = Combined.unionWith(ConstantRange::getFull(Width).signExtend(64));
      } else {
        Combined = ConstantRange::getFull(64);
        break;
      }
    }
    if (!Combined.isFullSet()) Bounds.try_emplace(Field, Combined);
  }
  return Bounds;
}

static Facts dominatingBounds(IntrinsicInst &Call, DominatorTree &Tree,
                              AssumptionCache &Assumptions, const Facts &Incoming,
                              SmallPtrSetImpl<LoadInst *> *UnstableLoads = nullptr) {
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
                Assumptions, Bounds, Budget, UnstableLoads);
    }
  }
  return Bounds;
}
// Inline a pair of calls that share most of their aggregate inputs after
// removing the checked arithmetic that previously kept the helper too large.
static void findRelatedCalls(Function &Helper,
                             FunctionAnalysisManager &Analyses,
                             SmallVectorImpl<CallBase *> &Pending) {
  if (Pending.size() >= 8 || !Helper.hasLocalLinkage() || !Helper.hasNUses(2) ||
      Helper.hasFnAttribute(Attribute::NoInline) ||
      Helper.getInstructionCount() > 300)
    return;

  SmallVector<CallBase *, 2> Calls;
  for (Use &Use : Helper.uses()) {
    auto *Call = dyn_cast<CallInst>(Use.getUser());
    if (!Call || &Use != &Call->getCalledOperandUse() ||
        Call->getFunctionType() != Helper.getFunctionType() ||
        Call->getFunction() == &Helper || Call->isMustTailCall() || Call->isNoInline() ||
        Call->hasOperandBundles() || Call->isConvergent())
      return;
    Calls.push_back(Call);
  }
  if (Calls[0]->getParent() != Calls[1]->getParent() ||
      Calls[0]->getFunction()->hasOptSize() || Calls[0]->getFunction()->hasMinSize() ||
      Calls[0]->getFunction()->hasOptNone() ||
      Calls[0]->getFunction()->getInstructionCount() > 1200 ||
      !isInlineViable(Helper).isSuccess())
    return;

  unsigned SharedAggregates = 0, Differences = 0;
  for (unsigned Index = 0; Index < Helper.arg_size(); ++Index) {
    Value *Left = Calls[0]->getArgOperand(Index);
    Value *Right = Calls[1]->getArgOperand(Index);
    SharedAggregates += Left == Right && Left->getType()->isAggregateType();
    Differences += Left != Right;
  }
  if (SharedAggregates < 2 || Differences != 1) return;
  auto &Target = Analyses.getResult<TargetIRAnalysis>(Helper);
  auto GetLibrary = [&](Function &Function) -> const TargetLibraryInfo & {
    return Analyses.getResult<TargetLibraryAnalysis>(Function);
  };
  for (CallBase *Call : Calls)
    if (auto Decision = getAttributeBasedInliningDecision(
            *Call, &Helper, Target, GetLibrary);
        Decision && !Decision->isSuccess())
      return;
  Pending.append(Calls.begin(), Calls.end());
}

} // namespace ElisaCheckedSignedRanges

static unsigned foldProvenSignedChecks(
    Module &Module, TargetMachine *Machine,
    SmallPtrSetImpl<Function *> *Inlined = nullptr, Function *Only = nullptr) {
  using namespace ElisaCheckedSignedRanges;
  if (!Module.getTargetTriple().isAArch64()) return 0;
  FunctionAnalysisManager Analyses;
  PassBuilder Builder(Machine);
  Builder.registerFunctionAnalyses(Analyses);
  unsigned Changes = 0;
  SmallVector<CallBase *, 8> RelatedCalls;
  for (Function &Function : Module) {
    if ((Only && &Function != Only) || Function.isDeclaration() || Function.hasOptNone() ||
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
    auto &Loops = Analyses.getResult<LoopAnalysis>(Function);
    const auto Incoming = incomingFieldBounds(Function);
    SmallVector<IntrinsicInst *, 16> Safe;
    for (IntrinsicInst *Call : Candidates) {
      auto Bounds = dominatingBounds(*Call, Tree, Assumptions, Incoming);
      if (Bounds.empty()) continue;
      unsigned Budget = 64;
      auto Left = rangeOf(Call->getArgOperand(0), Bounds, Evolution, Loops, Budget);
      auto Right = rangeOf(Call->getArgOperand(1), Bounds, Evolution, Loops, Budget);
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
    if (Inlined && Safe.size() >= 8) findRelatedCalls(Function, Analyses, RelatedCalls);
    Analyses.invalidate(Function, PreservedAnalyses::none());
  }
  for (CallBase *Call : RelatedCalls) {
    InlineFunctionInfo Info;
    Function *Caller = Call->getFunction();
    if (InlineFunction(*Call, Info).isSuccess()) {
      Inlined->insert(Caller);
      ++Changes;
    }
  }
  return Changes;
}


// Stabilize the loads whose accepted guard edges prove useful narrow ranges.
// Freeze picks a consistent value for undefined data and is inert for defined
// inputs. All uses, including the guard, must see the same frozen value.
static void stabilizeGuardedSignedOperands(Function &Function) {
  using namespace ElisaCheckedSignedRanges;
  DominatorTree Tree(Function);
  AssumptionCache Assumptions(Function);
  SmallPtrSet<LoadInst *, 16> Loads;
  for (Instruction &Instruction : instructions(Function)) {
    auto *Call = dyn_cast<IntrinsicInst>(&Instruction);
    if (Call && checkedOpcode(Call->getIntrinsicID()))
      dominatingBounds(*Call, Tree, Assumptions, Facts(), &Loads);
  }
  if (Loads.size() > 16) return;
  for (BasicBlock &Block : Function)
    for (Instruction &Instruction : make_early_inc_range(Block)) {
      auto *Load = dyn_cast<LoadInst>(&Instruction);
      if (!Load || !Loads.contains(Load)) continue;
      IRBuilder<> Builder(Load->getNextNode());
      auto *Stable = cast<FreezeInst>(Builder.CreateFreeze(Load, "validated.input"));
      Load->replaceUsesWithIf(Stable, [&](Use &Use) { return Use.getUser() != Stable; });
    }
}
