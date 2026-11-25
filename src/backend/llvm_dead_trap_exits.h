// The comparisons a branch condition decides, and trap blocks, for the C++ passes not yet
// ported (edge exclusion, element bounds, index ranges and bounds, proven checks). The dead-trap-exit pass that
// introduced them is Elisa now (llvm_passes/late_cleanup/range_checks/dead_trap_exits.elisa),
// and so is this walk (llvm_passes/ir/decided_compares.elisa).
#include <llvm/IR/PatternMatch.h>
namespace ElisaDeadTrapExits {
using namespace llvm;

// Comparisons a branch condition decides when it has value Truth, through
// logical and/or (and their select forms).
static void decided(Value *Condition, bool Truth,
                    SmallVectorImpl<std::pair<ICmpInst *, bool>> &Out, unsigned Depth = 0) {
  using namespace PatternMatch;
  Value *Left = nullptr, *Right = nullptr;
  if (auto *Compare = dyn_cast<ICmpInst>(Condition)) {
    Out.push_back({Compare, Truth});
  } else if (Depth < 6 && ((Truth && match(Condition, m_LogicalAnd(m_Value(Left), m_Value(Right)))) ||
                           (!Truth && match(Condition, m_LogicalOr(m_Value(Left), m_Value(Right)))))) {
    decided(Left, Truth, Out, Depth + 1);
    decided(Right, Truth, Out, Depth + 1);
  }
}

// Comparisons decided on the edge From -> To.
static SmallVector<std::pair<ICmpInst *, bool>, 4> edgeFacts(BasicBlock *From, BasicBlock *To) {
  SmallVector<std::pair<ICmpInst *, bool>, 4> Facts;
  auto *Branch = dyn_cast<CondBrInst>(From->getTerminator());
  if (Branch && Branch->getSuccessor(0) != Branch->getSuccessor(1))
    decided(Branch->getCondition(), Branch->getSuccessor(0) == To, Facts);
  return Facts;
}

static bool isTrap(BasicBlock &Block) { return isa<UnreachableInst>(Block.getTerminator()); }
} // namespace ElisaDeadTrapExits
