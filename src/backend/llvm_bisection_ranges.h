// Bound the values of a bisection search. A midpoint M = L + (H - L) / c, for
// a constant c >= 1, or M = (L + H) / 2 lies between L and H whichever is
// larger: a quotient rounded toward zero or down stays between zero and its
// dividend, and between two integers when the exact quotient is. The endpoints and
// midpoints of a search flow into each other through phis and selects, so
// every value of that web stays within the hull of the values that enter it
// from outside (the initial low and high bounds).
namespace ElisaBisectionRanges {
using namespace llvm;

// The operands of an add or sub that cannot wrap: a checked intrinsic, read
// on its no-overflow path, or a plain instruction with `nsw`.
static bool nonWrapping(Value *Result, Intrinsic::ID Checked, Instruction::BinaryOps Plain,
                        Value *&Left, Value *&Right) {
  if (auto *Field = dyn_cast<ExtractValueInst>(Result);
      Field && Field->getNumIndices() == 1 && *Field->idx_begin() == 0) {
    Value *Pair = Field->getAggregateOperand();
    if (auto *Frozen = dyn_cast<FreezeInst>(Pair)) Pair = Frozen->getOperand(0);
    auto *Call = dyn_cast<IntrinsicInst>(Pair);
    if (!Call || Call->getIntrinsicID() != Checked) return false;
    Left = Call->getArgOperand(0);
    Right = Call->getArgOperand(1);
    return true;
  }
  auto *Binary = dyn_cast<BinaryOperator>(Result);
  if (!Binary || Binary->getOpcode() != Plain || !Binary->hasNoSignedWrap()) return false;
  Left = Binary->getOperand(0);
  Right = Binary->getOperand(1);
  return true;
}

// The dividend of a division by a positive constant that rounds toward zero
// (sdiv) or down (ashr); Halving requires the divisor to be exactly two.
static Value *shrunkDividend(Value *Quotient, bool Halving) {
  auto *Binary = dyn_cast<BinaryOperator>(Quotient);
  if (!Binary) return nullptr;
  auto *Divisor = dyn_cast<ConstantInt>(Binary->getOperand(1));
  if (!Divisor) return nullptr;
  const APInt &Amount = Divisor->getValue();
  if (Binary->getOpcode() == Instruction::SDiv && Amount.isStrictlyPositive() &&
      (!Halving || Amount == 2))
    return Binary->getOperand(0);
  if (Binary->getOpcode() == Instruction::AShr &&
      Amount.ult(Binary->getType()->getIntegerBitWidth()) && (!Halving || Amount == 1))
    return Binary->getOperand(0);
  return nullptr;
}

// The two endpoints whose midpoint Value is, if it is one.
static bool midpointEnds(Value *Candidate, Value *&Low, Value *&High) {
  Value *Left, *Right, *Minuend, *Subtrahend;
  if (nonWrapping(Candidate, Intrinsic::sadd_with_overflow, Instruction::Add, Left, Right)) {
    for (auto [Base, Step] : {std::pair{Left, Right}, std::pair{Right, Left}}) {
      Value *Span = shrunkDividend(Step, false);
      if (Span && nonWrapping(Span, Intrinsic::ssub_with_overflow, Instruction::Sub, Minuend,
                              Subtrahend) && Subtrahend == Base) {
        Low = Base;
        High = Minuend;
        return true;
      }
    }
    return false;
  }
  Value *Sum = shrunkDividend(Candidate, true);
  if (Sum && nonWrapping(Sum, Intrinsic::sadd_with_overflow, Instruction::Add, Left, Right)) {
    Low = Left;
    High = Right;
    return true;
  }
  return false;
}

// The hull of a bisection web containing Start, or nothing when Start is not
// in one. Leaf gives the range of a value entering the web.
template <typename LeafRange>
static std::optional<ConstantRange> bisectionHull(Value *Start, LeafRange Leaf) {
  if (!isa<PHINode, SelectInst, ExtractValueInst, BinaryOperator, FreezeInst>(Start) ||
      !Start->getType()->isIntegerTy())
    return std::nullopt;
  unsigned Width = Start->getType()->getIntegerBitWidth();
  SmallPtrSet<Value *, 16> Web, Entering;
  SmallVector<Value *, 16> Work{Start};
  bool HasMidpoint = false;
  while (!Work.empty()) {
    Value *Member = Work.pop_back_val();
    if (Web.contains(Member) || Entering.contains(Member)) continue;
    if (Web.size() + Entering.size() > 24) return std::nullopt;
    Value *Low, *High;
    if (auto *Merge = dyn_cast<PHINode>(Member)) {
      Web.insert(Member);
      Work.append(Merge->incoming_values().begin(), Merge->incoming_values().end());
    } else if (auto *Frozen = dyn_cast<FreezeInst>(Member)) {
      // Web values come from entering values and non-wrapping arithmetic, so
      // they are defined whenever the entering values are; freezing keeps them.
      Web.insert(Member);
      Work.push_back(Frozen->getOperand(0));
    } else if (auto *Choice = dyn_cast<SelectInst>(Member)) {
      Web.insert(Member);
      Work.append({Choice->getTrueValue(), Choice->getFalseValue()});
    } else if (midpointEnds(Member, Low, High)) {
      Web.insert(Member);
      HasMidpoint = true;
      Work.append({Low, High});
    } else {
      if (Member == Start) return std::nullopt;
      Entering.insert(Member);
    }
  }
  if (!HasMidpoint || Entering.empty()) return std::nullopt;
  ConstantRange Hull = ConstantRange::getEmpty(Width);
  for (Value *Outside : Entering) {
    Hull = Hull.unionWith(Leaf(Outside), ConstantRange::Signed);
    if (Hull.isFullSet()) return std::nullopt;
  }
  return Hull;
}
} // namespace ElisaBisectionRanges
