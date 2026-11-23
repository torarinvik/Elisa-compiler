// Ranges of loop-carried values for the signed-check prover
// (ElisaCheckedSignedRanges). Three shapes of header phi are bounded:
// - a counter from zero, incremented once per iteration (the increment may be
//   repeated on several paths and joined by a phi) and leaving the loop when
//   it reaches a positive limit, stays below that limit;
// - a value each iteration keeps or moves by a constant where a guard bounds
//   it (a stack's top: pushed while below its capacity, popped while above
//   zero) stays in a hull of its start and those guards' constants, checked by
//   induction over every path to the latch;
// - a sum that adds at most one bounded term per iteration of a counted loop
//   stays within its start plus that many terms;
// - a value with a nonnegative start that every iteration keeps or moves
//   toward zero (divided by at least one, or less such a quotient of
//   itself: `x - x / f`) stays between zero and its start.
// A phi inside one iteration takes one of its incoming values, each bounded
// by the facts that hold where the phi is.
#include <llvm/IR/PatternMatch.h>
namespace ElisaCheckedLoopRanges {
using namespace llvm;
using Facts = DenseMap<Value *, ConstantRange>;
// The range of a value under the facts that hold where it is used.
using RangeIn = function_ref<ConstantRange(Value *, const Facts &)>;
// The facts that hold at an instruction.
using FactsAt = function_ref<Facts(Instruction &)>;
// The guards' range for one value at an instruction, even a loop-carried one.
using FactOn = function_ref<ConstantRange(Instruction &, Value *)>;

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

// The values that reach the header from its latch: phis of the same loop are
// walked, so each leaf is what one path through an iteration computes.
static bool backEdgeLeaves(Value *Next, PHINode &Header, LoopInfo &Loops,
                           SmallVectorImpl<Value *> &Leaves) {
  Loop *Owner = Loops.getLoopFor(Header.getParent());
  SmallVector<Value *, 8> Work{Next};
  SmallPtrSet<Value *, 16> Seen;
  while (!Work.empty()) {
    Value *Current = Work.pop_back_val();
    if (!Seen.insert(Current).second) continue;
    if (Seen.size() > 32) return false;
    auto *Join = dyn_cast<PHINode>(Current);
    if (Join && Join != &Header && Loops.getLoopFor(Join->getParent()) == Owner &&
        Owner->getHeader() != Join->getParent()) {
      for (Value *Incoming : Join->incoming_values()) Work.push_back(Incoming);
      continue;
    }
    Leaves.push_back(Current);
  }
  return true;
}

struct Header {
  Loop *Owner = nullptr;
  BasicBlock *Entry = nullptr;
  BasicBlock *Latch = nullptr;
};

static std::optional<Header> headerOf(PHINode &Phi, LoopInfo &Loops) {
  Loop *Owner = Loops.getLoopFor(Phi.getParent());
  if (!Owner || Owner->getHeader() != Phi.getParent() || Phi.getNumIncomingValues() != 2)
    return std::nullopt;
  Header Shape{Owner, Owner->getLoopPredecessor(), Owner->getLoopLatch()};
  if (!Shape.Entry || !Shape.Latch) return std::nullopt;
  return Shape;
}

// A zero-based counter tested after increment visits [0, limit) when the
// equality exit compares against one positive limit the loop does not change.
// Facts about the limit come only from values that cannot change between the
// guard and their use (ElisaCheckedSignedRanges::collect), so the limit needs
// no stability of its own.
static Value *countedLoopLimit(PHINode &Counter, LoopInfo &Loops) {
  using namespace PatternMatch;
  auto Shape = headerOf(Counter, Loops);
  if (!Shape) return nullptr;
  auto *Initial = dyn_cast<ConstantInt>(Counter.getIncomingValueForBlock(Shape->Entry));
  Value *Next = Counter.getIncomingValueForBlock(Shape->Latch);
  auto *Branch = dyn_cast<CondBrInst>(Shape->Latch->getTerminator());
  if (!Initial || !Initial->isZero() || !Branch ||
      Branch->getSuccessor(1) != Shape->Owner->getHeader() ||
      Shape->Owner->contains(Branch->getSuccessor(0)))
    return nullptr;
  SmallVector<Value *, 4> Leaves;
  if (!backEdgeLeaves(Next, Counter, Loops, Leaves)) return nullptr;
  for (Value *Leaf : Leaves)
    if (!match(Leaf, m_c_Add(m_Specific(&Counter), m_One()))) return nullptr;
  auto *Compare = dyn_cast<ICmpInst>(Branch->getCondition());
  if (!Compare || Compare->getPredicate() != ICmpInst::ICMP_EQ) return nullptr;
  Value *Limit = Compare->getOperand(0) == Next   ? Compare->getOperand(1)
                 : Compare->getOperand(1) == Next ? Compare->getOperand(0)
                                                  : nullptr;
  return Limit && Shape->Owner->isLoopInvariant(Limit) ? Limit : nullptr;
}

// The positive limits a counter's limit takes when the loop is entered,
// narrowed by the guards that skip the loop for an empty count.
static std::optional<ConstantRange> positiveLimits(PHINode &Counter, Value *Limit,
                                                   ConstantRange Limits, FactOn On) {
  if (On)
    Limits = Limits.intersectWith(On(*Counter.getParent()->getFirstNonPHI(), Limit),
                                  ConstantRange::Signed);
  if (Limits.isEmptySet() || Limits.isSignWrappedSet() || !Limits.getSignedMin().isStrictlyPositive())
    return std::nullopt;
  return Limits;
}

// The most iterations one entry into the loop of `Phi` runs, when one of its
// header phis counts them.
static std::optional<APInt> tripBound(PHINode &Phi, LoopInfo &Loops, RangeIn Range,
                                      const Facts &AtEntry, FactOn On) {
  for (PHINode &Counter : Phi.getParent()->phis())
    if (Value *Limit = countedLoopLimit(Counter, Loops))
      if (auto Limits = positiveLimits(Counter, Limit, Range(Limit, AtEntry), On))
        return Limits->getSignedMax();
  return std::nullopt;
}

// A counter's range: [0, the largest limit).
static std::optional<ConstantRange> counterRange(PHINode &Counter, LoopInfo &Loops,
                                                 function_ref<ConstantRange(Value *)> Range,
                                                 FactOn On) {
  Value *Limit = countedLoopLimit(Counter, Loops);
  if (!Limit) return std::nullopt;
  auto Limits = positiveLimits(Counter, Limit, Range(Limit), On);
  if (!Limits) return std::nullopt;
  return ConstantRange(APInt(Limits->getBitWidth(), 0), Limits->getSignedMax());
}

// A step from `Phi`: the term added by `Phi + Term`, checked or not.
static Value *addedTerm(Value *Leaf, PHINode &Phi, Instruction *&At) {
  using namespace PatternMatch;
  Value *Term = nullptr;
  if (match(Leaf, m_c_Add(m_Specific(&Phi), m_Value(Term)))) {
    At = cast<Instruction>(Leaf);
    return Term;
  }
  auto *Field = dyn_cast<ExtractValueInst>(Leaf);
  auto *Call = Field && Field->getNumIndices() == 1 && *Field->idx_begin() == 0
                   ? dyn_cast<IntrinsicInst>(Field->getAggregateOperand())
                   : nullptr;
  if (!Call || Call->getIntrinsicID() != Intrinsic::sadd_with_overflow) return nullptr;
  At = Call;
  return Call->getArgOperand(0) == &Phi   ? Call->getArgOperand(1)
         : Call->getArgOperand(1) == &Phi ? Call->getArgOperand(0)
                                          : nullptr;
}

// start + [0, trips] * (each term's hull with zero), when it fits.
static std::optional<ConstantRange> summedRange(PHINode &Sum, LoopInfo &Loops, RangeIn Range,
                                                FactsAt At, FactOn On) {
  auto Shape = headerOf(Sum, Loops);
  if (!Shape || !Sum.getType()->isIntegerTy(64)) return std::nullopt;
  Facts AtEntry = At(*Shape->Owner->getHeader()->getFirstNonPHI());
  auto Trips = tripBound(Sum, Loops, Range, AtEntry, On);
  SmallVector<Value *, 4> Leaves;
  if (!Trips || !backEdgeLeaves(Sum.getIncomingValueForBlock(Shape->Latch), Sum, Loops, Leaves))
    return std::nullopt;
  ConstantRange Terms(APInt(64, 0));
  bool Summed = false;
  for (Value *Leaf : Leaves) {
    if (Leaf == &Sum) continue;
    Instruction *Step = nullptr;
    Value *Term = addedTerm(Leaf, Sum, Step);
    if (!Term) return std::nullopt;
    Terms = Terms.unionWith(Range(Term, At(*Step)), ConstantRange::Signed);
    if (Terms.isFullSet()) return std::nullopt;
    Summed = true;
  }
  ConstantRange Start = Range(Sum.getIncomingValueForBlock(Shape->Entry), AtEntry);
  if (!Summed || Start.isEmptySet() || Start.isFullSet()) return std::nullopt;
  APInt Count = Trips->sext(130);
  APInt Low = Start.getSignedMin().sext(130) + Count * Terms.getSignedMin().sext(130);
  APInt High = Start.getSignedMax().sext(130) + Count * Terms.getSignedMax().sext(130);
  if (!Low.isSignedIntN(64) || !High.isSignedIntN(64)) return std::nullopt;
  return ConstantRange::getNonEmpty(Low.trunc(64), High.trunc(64) + 1);
}

// The narrowest hull of the start and the guards' constants that every path
// keeps a stepped header phi in.
static std::optional<ConstantRange> steppedRange(PHINode &Phi, LoopInfo &Loops, RangeIn Range,
                                                 FactsAt At, FactOn On) {
  using namespace PatternMatch;
  auto Shape = headerOf(Phi, Loops);
  if (!Shape || !Phi.getType()->isIntegerTy()) return std::nullopt;
  unsigned Width = Phi.getType()->getIntegerBitWidth();
  SmallVector<Value *, 4> Leaves;
  if (!backEdgeLeaves(Phi.getIncomingValueForBlock(Shape->Latch), Phi, Loops, Leaves))
    return std::nullopt;
  ConstantRange Start = Range(Phi.getIncomingValueForBlock(Shape->Entry),
                              At(*Shape->Owner->getHeader()->getFirstNonPHI()));
  if (Start.isEmptySet() || Start.isFullSet() || Start.isSignWrappedSet()) return std::nullopt;
  struct Step { APInt Offset; ConstantRange Guard; };
  SmallVector<Step, 4> Steps;
  SmallVector<APInt, 8> Bounds{Start.getSignedMin(), Start.getSignedMax()};
  for (Value *Leaf : Leaves) {
    if (Leaf == &Phi) continue;
    const APInt *Offset = nullptr;
    if (!match(Leaf, m_c_Add(m_Specific(&Phi), m_APInt(Offset))) || Steps.size() == 4)
      return std::nullopt;
    ConstantRange Guard = On(*cast<Instruction>(Leaf), &Phi);
    Steps.push_back({*Offset, Guard});
    if (const APInt *Excluded = Guard.inverse().getSingleElement()) {
      Bounds.push_back(*Excluded);
    } else if (!Guard.isFullSet() && !Guard.isSignWrappedSet()) {
      Bounds.push_back(Guard.getSignedMin() + *Offset);
      Bounds.push_back(Guard.getSignedMax() + *Offset);
    }
  }
  if (Steps.empty()) return std::nullopt;
  // [Low, High] holds when every step from inside it lands inside it again.
  auto Inductive = [&](const APInt &Low, const APInt &High) {
    for (const Step &Each : Steps) {
      ConstantRange Before = ConstantRange::getNonEmpty(Low, High + 1)
                                 .intersectWith(Each.Guard, ConstantRange::Signed);
      if (Before.isEmptySet()) continue;
      if (Before.isSignWrappedSet()) return false;
      APInt Least = Before.getSignedMin().sext(Width + 1) + Each.Offset.sext(Width + 1);
      APInt Most = Before.getSignedMax().sext(Width + 1) + Each.Offset.sext(Width + 1);
      if (Least.slt(Low.sext(Width + 1)) || Most.sgt(High.sext(Width + 1))) return false;
    }
    return true;
  };
  std::optional<ConstantRange> Best;
  for (const APInt &Low : Bounds)
    for (const APInt &High : Bounds)
      if (Low.sle(Start.getSignedMin()) && High.sge(Start.getSignedMax()) &&
          !High.isMaxSignedValue() &&
          (!Best || (High - Low).ult(Best->getSignedMax() - Best->getSignedMin())) &&
          Inductive(Low, High))
        Best = ConstantRange::getNonEmpty(Low, High + 1);
  return Best;
}

// Leaf lies in [0, Base] whenever Base is nonnegative: Base itself, a
// quotient of such a value by a divisor of at least one, such a value less
// its own quotient (`x - x / f`, checked or not), a phi joining such values,
// or the header phi of a loop that starts from one and only shrinks itself.
static bool shrinks(Value *Leaf, Value *Base, LoopInfo &Loops, RangeIn Range, FactsAt At,
                    unsigned Depth) {
  using namespace PatternMatch;
  if (Leaf == Base) return true;
  auto *Step = dyn_cast<Instruction>(Leaf);
  if (!Step || Depth > 6) return false;
  auto Quotient = [&](Value *V, Value *&Dividend) {
    Value *Divisor = nullptr;
    if (!match(V, m_SDiv(m_Value(Dividend), m_Value(Divisor)))) return false;
    ConstantRange Divisors = Range(Divisor, At(*cast<Instruction>(V)));
    return !Divisors.isEmptySet() && Divisors.getSignedMin().sge(1);
  };
  auto Recurse = [&](Value *V, Value *Within) { return shrinks(V, Within, Loops, Range, At, Depth + 1); };
  Value *Dividend = nullptr, *Whole = nullptr, *Part = nullptr;
  if (Quotient(Leaf, Dividend)) return Recurse(Dividend, Base);
  auto *Field = dyn_cast<ExtractValueInst>(Leaf);
  auto *Checked = Field ? dyn_cast<WithOverflowInst>(Field->getAggregateOperand()) : nullptr;
  if (Checked && Checked->getBinaryOp() == Instruction::Sub && Field->getNumIndices() == 1 &&
      Field->getIndices()[0] == 0) {
    Whole = Checked->getLHS();
    Part = Checked->getRHS();
  }
  if (Whole || match(Leaf, m_Sub(m_Value(Whole), m_Value(Part))))
    return Quotient(Part, Dividend) && Dividend == Whole && Recurse(Whole, Base);
  auto *Inner = dyn_cast<PHINode>(Leaf);
  if (!Inner) return false;
  auto Shape = headerOf(*Inner, Loops);
  if (!Shape)
    return llvm::all_of(Inner->incoming_values(), [&](Value *V) { return Recurse(V, Base); });
  SmallVector<Value *, 4> Leaves;
  return Recurse(Inner->getIncomingValueForBlock(Shape->Entry), Base) &&
         backEdgeLeaves(Inner->getIncomingValueForBlock(Shape->Latch), *Inner, Loops, Leaves) &&
         llvm::all_of(Leaves, [&](Value *V) { return Recurse(V, Inner); });
}

// A header phi from a nonnegative start whose every iteration shrinks it.
static std::optional<ConstantRange> shrinkingRange(PHINode &Phi, LoopInfo &Loops, RangeIn Range,
                                                   FactsAt At) {
  auto Shape = headerOf(Phi, Loops);
  if (!Shape || !Phi.getType()->isIntegerTy()) return std::nullopt;
  ConstantRange Start = Range(Phi.getIncomingValueForBlock(Shape->Entry),
                              At(*Shape->Owner->getHeader()->getFirstNonPHI()));
  SmallVector<Value *, 4> Leaves;
  if (Start.isEmptySet() || Start.isSignWrappedSet() || Start.getSignedMin().isNegative() ||
      !backEdgeLeaves(Phi.getIncomingValueForBlock(Shape->Latch), Phi, Loops, Leaves) ||
      !llvm::all_of(Leaves, [&](Value *Leaf) { return shrinks(Leaf, &Phi, Loops, Range, At, 0); }))
    return std::nullopt;
  return ConstantRange::getNonEmpty(APInt::getZero(Start.getBitWidth()), Start.getSignedMax() + 1);
}

// A header phi's range under every shape that bounds it.
static std::optional<ConstantRange> headerRange(PHINode &Phi, LoopInfo &Loops, RangeIn Range,
                                                FactsAt At, FactOn On) {
  auto Summed = summedRange(Phi, Loops, Range, At, On);
  auto Stepped = steppedRange(Phi, Loops, Range, At, On);
  if (Summed && Stepped) return Summed->intersectWith(*Stepped, ConstantRange::Signed);
  if (Summed || Stepped) return Summed ? Summed : Stepped;
  return shrinkingRange(Phi, Loops, Range, At);
}

// A phi inside an iteration: the value its loop carries when it feeds a
// stepped header phi, else the hull of its incoming values.
static std::optional<ConstantRange> joinRange(PHINode &Join, LoopInfo &Loops, RangeIn Range,
                                              FactsAt At, FactOn On) {
  for (User *Carrier : Join.users())
    if (auto *Header = dyn_cast<PHINode>(Carrier); Header && Header != &Join)
      if (auto Shape = headerOf(*Header, Loops);
          Shape && Header->getIncomingValueForBlock(Shape->Latch) == &Join)
        if (auto Carried = steppedRange(*Header, Loops, Range, At, On)) return Carried;
  Facts Here = At(Join);
  unsigned Width = Join.getType()->getIntegerBitWidth();
  ConstantRange Hull = ConstantRange::getEmpty(Width);
  for (Value *Incoming : Join.incoming_values()) {
    Hull = Hull.unionWith(Range(Incoming, Here), ConstantRange::Signed);
    if (Hull.isFullSet()) return std::nullopt;
  }
  return Hull;
}
} // namespace ElisaCheckedLoopRanges
