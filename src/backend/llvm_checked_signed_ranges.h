// Propagate dominating validation ranges into checked signed arithmetic.
#include "llvm_checked_loop_ranges.h"
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
    } else if (!ElisaCheckedLoopRanges::neverUndefined(Input)) {
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

static std::optional<Instruction::BinaryOps> checkedOpcode(Intrinsic::ID ID) {
  switch (ID) {
  case Intrinsic::sadd_with_overflow: return Instruction::Add;
  case Intrinsic::ssub_with_overflow: return Instruction::Sub;
  case Intrinsic::smul_with_overflow: return Instruction::Mul;
  default: return std::nullopt;
  }
}

// Values fixed for one case of a case split (see splitCannotOverflow).
using Cases = SmallDenseMap<Value *, APInt, 4>;

static Facts dominatingBounds(Instruction &Call, DominatorTree &Tree,
                              AssumptionCache &Assumptions, const Facts &Incoming,
                              SmallPtrSetImpl<LoadInst *> *UnstableLoads,
                              SmallPtrSetImpl<Argument *> *FrozenArguments);

static ConstantRange directFact(Instruction &Point, Value *Subject, DominatorTree &Tree,
                                AssumptionCache &Assumptions, SmallPtrSetImpl<Argument *> *Parameters);

// What loop-carried values need to find the facts at their own definitions
// (ElisaCheckedLoopRanges). Facts on unstable parameters go to Parameters,
// which a successful proof freezes.
struct Scope {
  DominatorTree &Tree;
  AssumptionCache &Assumptions;
  const Facts &Incoming;
  SmallPtrSetImpl<Argument *> *Parameters;
};

static ConstantRange rangeOf(Value *ValueToCheck, const Facts &Bounds,
                             ScalarEvolution &Evolution, LoopInfo &Loops, unsigned &Budget,
                             unsigned Depth = 0, const Cases *Assigned = nullptr,
                             const Scope *Context = nullptr) {
  unsigned Width = ValueToCheck->getType()->getIntegerBitWidth();
  if (!Budget || Depth == 14) return ConstantRange::getFull(Width);
  --Budget;
  if (Assigned)
    if (auto Fixed = Assigned->find(ValueToCheck); Fixed != Assigned->end())
      return ConstantRange(Fixed->second);
  if (auto Fact = Bounds.find(ValueToCheck); Fact != Bounds.end())
    return Fact->second;
  if (auto *Constant = dyn_cast<ConstantInt>(ValueToCheck))
    return ConstantRange(Constant->getValue());

  auto Recurse = [&](Value *Operand) {
    return rangeOf(Operand, Bounds, Evolution, Loops, Budget, Depth + 1, Assigned, Context);
  };
  // Within one case, shifts, masks, comparisons and selects narrow too.
  if (Assigned) {
    if (auto *Compare = dyn_cast<ICmpInst>(ValueToCheck);
        Compare && Compare->getOperand(0)->getType()->isIntegerTy()) {
      ConstantRange Left = Recurse(Compare->getOperand(0)), Right = Recurse(Compare->getOperand(1));
      if (Left.icmp(Compare->getPredicate(), Right)) return ConstantRange(APInt(1, 1));
      if (Left.icmp(Compare->getInversePredicate(), Right)) return ConstantRange(APInt(1, 0));
      return ConstantRange::getFull(1);
    }
    if (auto *Choice = dyn_cast<SelectInst>(ValueToCheck)) {
      ConstantRange Condition = Recurse(Choice->getCondition());
      if (const APInt *Known = Condition.getSingleElement())
        return Recurse(Known->isOne() ? Choice->getTrueValue() : Choice->getFalseValue());
      return Recurse(Choice->getTrueValue()).unionWith(Recurse(Choice->getFalseValue()));
    }
    if (isa<ICmpInst>(ValueToCheck) || Width == 1) return ConstantRange::getFull(Width);
    if (auto *Binary = dyn_cast<BinaryOperator>(ValueToCheck))
      return Recurse(Binary->getOperand(0))
          .binaryOp(Binary->getOpcode(), Recurse(Binary->getOperand(1)))
          .intersectWith(Evolution.getSignedRange(Evolution.getSCEV(ValueToCheck)),
                         ConstantRange::Signed);
  }
  if (auto *Cast = dyn_cast<CastInst>(ValueToCheck);
      Cast && Cast->getSrcTy()->isIntegerTy())
    return Recurse(Cast->getOperand(0)).castOp(Cast->getOpcode(), Width);
  if (auto Hull = ElisaBisectionRanges::bisectionHull(ValueToCheck, Recurse)) return *Hull;
  // A load whose `!range` holds is never poison, so freezing it keeps it; so
  // is a join of such loads and of values computed from defined ones.
  if (auto *Frozen = dyn_cast<FreezeInst>(ValueToCheck)) {
    auto *Load = dyn_cast<LoadInst>(Frozen->getOperand(0));
    if ((Load && Load->getMetadata(LLVMContext::MD_range)) ||
        (Context && !Load && !isa<Argument>(Frozen->getOperand(0))))
      return Recurse(Frozen->getOperand(0));
  }

  if (auto *Binary = dyn_cast<BinaryOperator>(ValueToCheck)) {
    auto Opcode = Binary->getOpcode();
    // An exact quotient of a nonnegative range rounds its least value up.
    if (auto *Divisor = dyn_cast<ConstantInt>(Binary->getOperand(1));
        Divisor && Binary->isExact() && (Opcode == Instruction::LShr || Opcode == Instruction::UDiv)) {
      ConstantRange Dividend = Recurse(Binary->getOperand(0));
      APInt Scale = Opcode == Instruction::UDiv ? Divisor->getValue()
                                                : APInt::getOneBitSet(Width, Divisor->getZExtValue() % Width);
      if (!Scale.isZero() && !Dividend.isEmptySet() && !Dividend.isSignWrappedSet() &&
          Dividend.getSignedMin().isNonNegative())
        return ConstantRange::getNonEmpty(APIntOps::RoundingUDiv(Dividend.getSignedMin(), Scale, APInt::Rounding::UP),
                                          Dividend.getSignedMax().udiv(Scale) + 1);
    }
    // A remainder is bounded by its divisor whatever the dividend is; a
    // quotient by the ranges of both operands.
    if (Opcode == Instruction::Add || Opcode == Instruction::Sub ||
        Opcode == Instruction::Mul || Opcode == Instruction::SRem ||
        Opcode == Instruction::URem || Opcode == Instruction::SDiv ||
        Opcode == Instruction::UDiv || Opcode == Instruction::LShr || Opcode == Instruction::And)
      return Recurse(Binary->getOperand(0)).binaryOp(
          Opcode, Recurse(Binary->getOperand(1)));
  }
  if (auto *Field = dyn_cast<ExtractValueInst>(ValueToCheck);
      Field && Field->getNumIndices() == 1 && *Field->idx_begin() == 0)
    if (auto *Call = dyn_cast<IntrinsicInst>(Field->getAggregateOperand()))
      if (auto Opcode = checkedOpcode(Call->getIntrinsicID()))
        return Recurse(Call->getArgOperand(0)).binaryOp(
            *Opcode, Recurse(Call->getArgOperand(1)));
  if (auto *Phi = dyn_cast<PHINode>(ValueToCheck)) {
    auto On = [&](Instruction &Point, Value *Subject) {
      return directFact(Point, Subject, Context->Tree, Context->Assumptions, Context->Parameters);
    };
    if (auto Counted = ElisaCheckedLoopRanges::counterRange(
            *Phi, Loops, Recurse, Context ? ElisaCheckedLoopRanges::FactOn(On) : nullptr))
      return *Counted;
    if (Context && Width <= 64) {
      auto In = [&](Value *Operand, const Facts &Where) {
        return rangeOf(Operand, Where, Evolution, Loops, Budget, Depth + 1, Assigned, Context);
      };
      auto At = [&](Instruction &Point) {
        return dominatingBounds(Point, Context->Tree, Context->Assumptions, Context->Incoming, nullptr,
                                Context->Parameters);
      };
      auto Carried = Loops.isLoopHeader(Phi->getParent())
                         ? ElisaCheckedLoopRanges::headerRange(*Phi, Loops, In, At, On)
                         : ElisaCheckedLoopRanges::joinRange(*Phi, Loops, In, At, On);
      if (Carried)
        return Carried->intersectWith(Evolution.getSignedRange(Evolution.getSCEV(Phi)),
                                      ConstantRange::Signed);
    }
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

static bool provenSafe(IntrinsicInst &Call, const Facts &Bounds, ScalarEvolution &Evolution,
                       LoopInfo &Loops, const Scope &Context) {
  unsigned Budget = 256;
  auto Left = rangeOf(Call.getArgOperand(0), Bounds, Evolution, Loops, Budget, 0, nullptr, &Context);
  auto Right = rangeOf(Call.getArgOperand(1), Bounds, Evolution, Loops, Budget, 0, nullptr, &Context);
  return cannotOverflow(*checkedOpcode(Call.getIntrinsicID()), Left, Right);
}

// The checked operation cannot overflow in any case of a split on the low
// bits `x & 1` its operands depend on, each 0 or 1. Only bits computed
// outside loops are split on, so each has one value whenever the check runs.
static bool splitCannotOverflow(IntrinsicInst &Call, const Facts &Bounds,
                                ScalarEvolution &Evolution, LoopInfo &Loops) {
  using namespace PatternMatch;
  SmallVector<Value *, 3> Bits;
  SmallPtrSet<Value *, 32> Seen;
  SmallVector<std::pair<Value *, unsigned>, 32> Work{{Call.getArgOperand(0), 0}, {Call.getArgOperand(1), 0}};
  while (!Work.empty()) {
    auto [V, Depth] = Work.pop_back_val();
    auto *I = dyn_cast<Instruction>(V);
    if (!I || Depth == 8 || !Seen.insert(I).second || isa<PHINode>(I)) continue;
    if (match(I, m_And(m_Value(), m_One())) && !Loops.getLoopFor(I->getParent())) {
      if (Bits.size() == 3) return false;
      Bits.push_back(I);
    }
    for (Value *Operand : I->operands()) Work.push_back({Operand, Depth + 1});
  }
  if (Bits.empty()) return false;
  auto Opcode = *checkedOpcode(Call.getIntrinsicID());
  for (unsigned Choice = 0; Choice < (1u << Bits.size()); ++Choice) {
    Cases Assigned;
    for (unsigned Index = 0; Index < Bits.size(); ++Index)
      Assigned.try_emplace(Bits[Index], APInt(Bits[Index]->getType()->getIntegerBitWidth(),
                                              (Choice >> Index) & 1));
    unsigned Budget = 128;
    auto Left = rangeOf(Call.getArgOperand(0), Bounds, Evolution, Loops, Budget, 0, &Assigned);
    auto Right = rangeOf(Call.getArgOperand(1), Bounds, Evolution, Loops, Budget, 0, &Assigned);
    if (!cannotOverflow(Opcode, Left, Right)) return false;
  }
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
// The guards on `Subject` that hold at `Point`, for that value itself and
// none computed from it.
static ConstantRange directFact(Instruction &Point, Value *Subject, DominatorTree &Tree,
                                AssumptionCache &Assumptions, SmallPtrSetImpl<Argument *> *Parameters) {
  Facts Found;
  unsigned Budget = 96;
  for (auto *Node = Tree.getNode(Point.getParent()); Node && Budget; Node = Node->getIDom()) {
    BasicBlock *Block = Node->getBlock();
    auto *Branch = dyn_cast<CondBrInst>(Block->getTerminator());
    if (!Branch || Branch->getSuccessor(0) == Branch->getSuccessor(1)) continue;
    for (unsigned Edge = 0; Edge < 2; ++Edge) {
      auto *Target = Branch->getSuccessor(Edge);
      if (Tree.dominates(BasicBlockEdge(Block, Target), Point.getParent()))
        collect(Branch->getCondition(), Edge == 0, *Branch, *Target, Tree, Assumptions, Found,
                Budget, nullptr, Parameters, Subject);
    }
  }
  auto Fact = Found.find(Subject);
  return Fact == Found.end() ? ConstantRange::getFull(Subject->getType()->getIntegerBitWidth())
                             : Fact->second;
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
        Function.getInstructionCount() > 4000)
      continue;
    SmallVector<IntrinsicInst *, 16> Candidates;
    for (Instruction &Instruction : instructions(Function))
      if (auto *Call = dyn_cast<IntrinsicInst>(&Instruction);
          Call && checkedOpcode(Call->getIntrinsicID()) &&
          Call->getArgOperand(0)->getType()->isIntegerTy(64))
        Candidates.push_back(Call);
    // Each candidate's proof is budgeted, so the cap only bounds pathological bodies.
    if (Candidates.empty() || Candidates.size() > 256) continue;
    auto &Tree = Analyses.getResult<DominatorTreeAnalysis>(Function);
    auto &Assumptions = Analyses.getResult<AssumptionAnalysis>(Function);
    auto &Evolution = Analyses.getResult<ScalarEvolutionAnalysis>(Function);
    auto &Loops = Analyses.getResult<LoopAnalysis>(Function);
    const auto Incoming = incomingFieldBounds(Function);
    SmallVector<IntrinsicInst *, 16> Safe;
    SmallPtrSet<Argument *, 4> Frozen;
    for (IntrinsicInst *Call : Candidates) {
      // Operands can be bounded without any dominating fact (loads with a
      // proven `!range`, bisection webs), so every candidate is tried.
      auto Bounds = dominatingBounds(*Call, Tree, Assumptions, Incoming);
      Scope Stable{Tree, Assumptions, Incoming, nullptr};
      if (provenSafe(*Call, Bounds, Evolution, Loops, Stable)) {
        Safe.push_back(Call);
        continue;
      }
      // With guarded parameters frozen, then within the cases of a split.
      SmallPtrSet<Argument *, 4> Parameters;
      auto Split = dominatingBounds(*Call, Tree, Assumptions, Incoming, nullptr, &Parameters);
      Scope Freezing{Tree, Assumptions, Incoming, &Parameters};
      if (!Parameters.empty() && provenSafe(*Call, Split, Evolution, Loops, Freezing)) {
        Safe.push_back(Call);
        Frozen.insert(Parameters.begin(), Parameters.end());
        continue;
      }
      if (!Split.empty() && splitCannotOverflow(*Call, Split, Evolution, Loops)) {
        Safe.push_back(Call);
        Frozen.insert(Parameters.begin(), Parameters.end());
      }
    }
    for (Argument *Parameter : Frozen) {
      IRBuilder<> Entry(&*Function.getEntryBlock().getFirstInsertionPt());
      auto *Stable = cast<FreezeInst>(Entry.CreateFreeze(Parameter, "validated.parameter"));
      Parameter->replaceUsesWithIf(Stable, [&](Use &Use) { return Use.getUser() != Stable; });
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
