// Reduce a remainder to one conditional subtraction when the dividend is
// nonnegative and below twice the modulus, including bounded loop recurrences.
// For unsigned Mersenne moduli, first fold a bounded dividend into this range.
#include <llvm/Config/llvm-config.h>
#include <llvm-c/Core.h>
#if LLVM_VERSION_MAJOR >= 23
#include <llvm/ADT/DenseMap.h>
#include <llvm/ADT/SmallPtrSet.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/IR/ConstantRange.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/InstIterator.h>
#include <llvm/IR/Module.h>
#include <llvm/Support/CBindingWrapping.h>
#include <optional>

using namespace llvm;

namespace {
const ConstantInt *remainderModulus(const BinaryOperator &Op) {
  switch (Op.getOpcode()) {
  case Instruction::SRem:
  case Instruction::URem:
    return dyn_cast<ConstantInt>(Op.getOperand(1));
  default:
    return nullptr;
  }
}

class BoundedRemainderProof {
  DominatorTree &DT;
  LoopInfo &LI;
  uint64_t Modulus;
  uint64_t SignedMax;
  bool AllowProductBounds;
  unsigned Work = 0;
  SmallPtrSet<Value *, 16> Active;
  DenseMap<std::pair<Value *, Instruction *>, uint64_t> Known;

  std::optional<uint64_t> guardedLoad(Value *V, Instruction *At) {
    auto *Load = dyn_cast<LoadInst>(V);
    if (!Load)
      return std::nullopt;
    for (User *U : Load->users()) {
      auto *Cmp = dyn_cast<ICmpInst>(U);
      if (!Cmp || Cmp->getOperand(0) != V)
        continue;
      auto *Limit = dyn_cast<ConstantInt>(Cmp->getOperand(1));
      if (!Limit || Limit->isNegative())
        continue;
      for (User *Use : Cmp->users()) {
        auto *Branch = dyn_cast<CondBrInst>(Use);
        if (!Branch || Branch->getSuccessor(0) == Branch->getSuccessor(1))
          continue;
        for (unsigned Edge = 0; Edge != 2; ++Edge) {
          auto Predicate = Edge == 0 ? Cmp->getPredicate() : Cmp->getInversePredicate();
          uint64_t Max = Limit->getZExtValue();
          if (Predicate == ICmpInst::ICMP_ULT && Max != 0)
            --Max;
          else if (Predicate != ICmpInst::ICMP_ULE)
            continue;
          if (DT.dominates(BasicBlockEdge(Branch->getParent(), Branch->getSuccessor(Edge)),
                           At->getParent())) {
            GuardedLoads.insert(Load);
            return Max;
          }
        }
      }
    }
    return std::nullopt;
  }

  bool isModularHeader(PHINode &Phi) {
    Loop *L = LI.getLoopFor(Phi.getParent());
    if (!L || L->getHeader() != Phi.getParent())
      return false;
    bool HasEntry = false;
    bool HasBackedge = false;
    for (unsigned I = 0; I < Phi.getNumIncomingValues(); ++I) {
      if (!L->contains(Phi.getIncomingBlock(I))) {
        HasEntry = true;
        continue;
      }
      auto *R = dyn_cast<BinaryOperator>(Phi.getIncomingValue(I));
      auto *K = R ? remainderModulus(*R) : nullptr;
      if (!K || !K->equalsInt(Modulus))
        return false;
      HasBackedge = true;
    }
    return HasEntry && HasBackedge;
  }

  std::optional<uint64_t> bound(Value *V, Instruction *At) {
    // A load's bound is valid only at uses dominated by its range check.
    auto Key = std::make_pair(V, At);
    if (auto It = Known.find(Key); It != Known.end())
      return It->second;
    if (++Work > 512 || Active.size() >= 96)
      return std::nullopt;
    if (auto *K = dyn_cast<ConstantInt>(V)) {
      if (!K->isNegative())
        return K->getZExtValue();
      return std::nullopt;
    }
    if (auto *Phi = dyn_cast<PHINode>(V); Phi && isModularHeader(*Phi)) {
      if (Assumed.insert(Phi).second)
        Pending.push_back(Phi);
      return Modulus - 1;
    }
    if (!Active.insert(V).second)
      return std::nullopt;
    auto Result = boundAcyclic(V, At);
    Active.erase(V);
    if (Result)
      Known.try_emplace(Key, *Result);
    return Result;
  }

  std::optional<uint64_t> boundAcyclic(Value *V, Instruction *At) {
    if (auto *Phi = dyn_cast<PHINode>(V)) {
      uint64_t Max = 0;
      for (unsigned I = 0; I < Phi->getNumIncomingValues(); ++I) {
        auto Incoming = bound(Phi->getIncomingValue(I),
                              Phi->getIncomingBlock(I)->getTerminator());
        if (!Incoming)
          return std::nullopt;
        Max = std::max(Max, *Incoming);
      }
      return Max;
    }
    if (auto *Op = dyn_cast<BinaryOperator>(V)) {
      if (Op->getOpcode() == Instruction::Add) {
        auto A = bound(Op->getOperand(0), Op);
        auto B = bound(Op->getOperand(1), Op);
        if (A && B && *A <= SignedMax && *B <= SignedMax - *A)
          return *A + *B;
      } else if (AllowProductBounds && Op->getOpcode() == Instruction::Mul) {
        auto A = bound(Op->getOperand(0), Op);
        auto B = bound(Op->getOperand(1), Op);
        if (A && B && (*A == 0 || *B <= SignedMax / *A))
          return *A * *B;
      } else if (auto *K = remainderModulus(*Op);
                 K && K->getValue().isStrictlyPositive() &&
                 ((AllowProductBounds && Op->getOpcode() == Instruction::URem) ||
                  bound(Op->getOperand(0), Op))) {
        return K->getZExtValue() - 1;
      }
    }
    return guardedLoad(V, At);
  }

  SmallPtrSet<PHINode *, 8> Assumed;
  SmallVector<PHINode *, 8> Pending;

public:
  SmallPtrSet<LoadInst *, 8> GuardedLoads;

  BoundedRemainderProof(DominatorTree &DT, LoopInfo &LI, uint64_t Modulus,
                        uint64_t SignedMax, bool AllowProductBounds = false)
      : DT(DT), LI(LI), Modulus(Modulus), SignedMax(SignedMax),
        AllowProductBounds(AllowProductBounds) {}

  bool prove(BinaryOperator &Remainder, uint64_t Limit) {
    auto Dividend = bound(Remainder.getOperand(0), &Remainder);
    if (!Dividend || *Dividend >= Limit)
      return false;
    // Discharge all hypotheses together. Each loop header's entry and
    // backedge must preserve the proposed bound, including cross-dependencies.
    for (unsigned P = 0; P < Pending.size(); ++P) {
      PHINode *Phi = Pending[P];
      for (unsigned I = 0; I < Phi->getNumIncomingValues(); ++I) {
        auto Incoming = bound(Phi->getIncomingValue(I),
                              Phi->getIncomingBlock(I)->getTerminator());
        if (!Incoming || *Incoming >= Modulus)
          return false;
      }
    }
    return true;
  }
};

bool exposeValidatedDivisorBound(BasicBlock &Block) {
  auto *Branch = dyn_cast<CondBrInst>(Block.getTerminator());
  if (!Branch || Branch->getSuccessor(0) == Branch->getSuccessor(1))
    return false;
  BasicBlock *Accepted = Branch->getSuccessor(1);
  if (Accepted->getSinglePredecessor() != &Block ||
      Accepted->getFirstInsertionPt() == Accepted->end())
    return false;

  // On the false edge of select A, true, B, the comparison B was evaluated
  // and returned false. Preserve its bound after short-circuit folding.
  auto *Condition = dyn_cast<SelectInst>(Branch->getCondition());
  auto *Reject = Condition ? dyn_cast<ConstantInt>(Condition->getTrueValue()) : nullptr;
  if (!Reject || !Reject->isOne())
    return false;
  auto *Comparison = dyn_cast<ICmpInst>(Condition->getFalseValue());
  if (!Comparison)
    return false;
  auto *Adjusted = dyn_cast<BinaryOperator>(Comparison->getOperand(0));
  auto *Limit = dyn_cast<ConstantInt>(Comparison->getOperand(1));
  if (!Adjusted || Adjusted->getOpcode() != Instruction::Add || !Limit)
    return false;
  auto *Offset = dyn_cast<ConstantInt>(Adjusted->getOperand(1));
  auto *Divisor = dyn_cast<LoadInst>(Adjusted->getOperand(0));
  if (!Offset || !Divisor || Divisor->getParent() != &Block ||
      Limit->getBitWidth() > 64)
    return false;
  auto Range = ConstantRange::makeExactICmpRegion(
      Comparison->getInversePredicate(), Limit->getValue()).subtract(Offset->getValue());
  if (Range.isEmptySet() || Range.getUnsignedMax().isAllOnes())
    return false;
  APInt Maximum = Range.getUnsignedMax();
  if (!llvm::any_of(Divisor->users(), [&](User *Use) {
        auto *Remainder = dyn_cast<BinaryOperator>(Use);
        if (!Remainder || Remainder->getOpcode() != Instruction::URem ||
            Remainder->getOperand(1) != Divisor)
          return false;
        return llvm::any_of(Remainder->users(), [&](User *Use) {
          auto *Check = dyn_cast<ICmpInst>(Use);
          if (!Check || Check->getPredicate() != ICmpInst::ICMP_ULT ||
              Check->getOperand(0) != Remainder)
            return false;
          auto *Extent = dyn_cast<ConstantInt>(Check->getOperand(1));
          return Extent && Maximum.ule(Extent->getValue());
        });
      }))
    return false;

  // The comparison and remainder must use the same value if the load is undef.
  IRBuilder<> AtLoad(Divisor->getNextNode());
  auto *Defined = cast<FreezeInst>(AtLoad.CreateFreeze(Divisor, "validated.divisor"));
  Divisor->replaceUsesWithIf(Defined, [&](Use &U) { return U.getUser() != Defined; });
  IRBuilder<> AtAccepted(&*Accepted->getFirstInsertionPt());
  auto *Upper = ConstantInt::get(Defined->getType(), Maximum);
  AtAccepted.CreateAssumption(AtAccepted.CreateICmpULE(Defined, Upper));
  return true;
}

unsigned foldBoundedRemainders(Module &M) {
  if (M.getNamedMetadata("llvm.dbg.cu") || !M.getTargetTriple().isAArch64())
    return 0;
  for (StringRef Flag : {"SanitizeAddress", "SanitizeHWAddress", "SanitizeMemory",
                         "SanitizeThread", "SanitizeRealtime"})
    if (M.getModuleFlag(Flag))
      return 0;
  unsigned Changed = 0;
  for (Function &F : M) {
    if (F.isDeclaration() || F.hasOptNone() || F.hasOptSize() || F.hasMinSize() ||
        F.getSubprogram() || F.getInstructionCount() > 2000)
      continue;
    if (llvm::any_of(std::initializer_list<Attribute::AttrKind>{Attribute::SanitizeAddress, Attribute::SanitizeHWAddress,
                     Attribute::SanitizeMemory, Attribute::SanitizeThread,
                     Attribute::SanitizeMemTag, Attribute::SanitizeRealtime,
                     Attribute::SanitizeRealtimeBlocking},
                    [&](Attribute::AttrKind Kind) { return F.hasFnAttribute(Kind); }))
      continue;
    for (BasicBlock &Block : F)
      Changed += exposeValidatedDivisorBound(Block);
    SmallVector<BinaryOperator *, 8> Candidates;
    for (Instruction &I : instructions(F)) {
      auto *Op = dyn_cast<BinaryOperator>(&I);
      if (!Op || Op->hasMetadataOtherThanDebugLoc() ||
          !Op->getType()->isIntegerTy() || Op->getType()->getIntegerBitWidth() > 64)
        continue;
      auto *K = remainderModulus(*Op);
      if (K && K->getValue().isStrictlyPositive() && !K->getValue().isPowerOf2())
        Candidates.push_back(Op);
    }
    if (Candidates.empty() || Candidates.size() > 64)
      continue;
    DominatorTree DT(F);
    LoopInfo LI(DT);
    SmallPtrSet<LoadInst *, 16> Loads;
    SmallVector<std::pair<BinaryOperator *, unsigned>, 8> Proven;
    for (BinaryOperator *Op : Candidates) {
      const auto &Modulus = cast<ConstantInt>(Op->getOperand(1))->getValue();
      uint64_t SignedMax = APInt::getSignedMaxValue(Modulus.getBitWidth()).getZExtValue();
      BoundedRemainderProof Proof(DT, LI, Modulus.getZExtValue(), SignedMax);
      uint64_t Divisor = Modulus.getZExtValue();
      if (Proof.prove(*Op, 2 * Divisor)) {
        Proven.emplace_back(Op, 0);
        Loads.insert(Proof.GuardedLoads.begin(), Proof.GuardedLoads.end());
        continue;
      }
      unsigned Shift = Modulus.countr_one();
      // Restrict the AArch64 rewrite to divisors whose constant-division
      // sequence needs multiple instructions to materialize its constants.
      if (Op->getOpcode() != Instruction::URem || Modulus.getBitWidth() != 64 ||
          Shift < 17 || Shift > 31 || !Modulus.isMask())
        continue;
      BoundedRemainderProof MersenneProof(DT, LI, Divisor, SignedMax, true);
      if (MersenneProof.prove(*Op, Divisor << Shift)) {
        Proven.emplace_back(Op, Shift);
        Loads.insert(MersenneProof.GuardedLoads.begin(), MersenneProof.GuardedLoads.end());
      }
    }
    if (Proven.empty())
      continue;
    // Visit loads in IR order so generated names are deterministic.
    for (Instruction &I : instructions(F)) {
      auto *Load = dyn_cast<LoadInst>(&I);
      if (!Load || !Loads.contains(Load))
        continue;
      // The range check and all consumers must see the same value even if
      // the load can return undef. Freeze once at the definition.
      IRBuilder<> Builder(Load->getNextNode());
      auto *Defined = cast<FreezeInst>(Builder.CreateFreeze(Load, "bounded.load"));
      Load->replaceUsesWithIf(Defined, [&](Use &U) { return U.getUser() != Defined; });
    }
    for (auto [Op, Shift] : Proven) {
      IRBuilder<> Builder(Op);
      Value *Dividend = Op->getOperand(0);
      Value *Modulus = Op->getOperand(1);
      if (Shift) {
        // Splitting at k preserves the residue modulo 2^k - 1. The
        // proven limit bounds the high part by modulus - 1.
        Dividend = Builder.CreateFreeze(Dividend);
        Dividend = Builder.CreateAdd(Builder.CreateAnd(Dividend, Modulus),
                                     Builder.CreateLShr(Dividend, Shift));
        // The carry is one exactly when the folded value reaches the modulus.
        Value *Carry = Builder.CreateLShr(Builder.CreateAdd(Dividend, Builder.getInt64(1)),
                                         Shift);
        Op->replaceAllUsesWith(Builder.CreateAnd(Builder.CreateAdd(Dividend, Carry), Modulus,
                                                 "mersenne.remainder"));
        Op->eraseFromParent();
        ++Changed;
        continue;
      }
      Value *Large = Builder.CreateICmpUGE(Dividend, Modulus);
      Value *Reduced = Builder.CreateSub(Dividend, Modulus);
      Op->replaceAllUsesWith(Builder.CreateSelect(Large, Reduced, Dividend, "bounded.remainder"));
      Op->eraseFromParent();
      ++Changed;
    }
  }
  return Changed;
}
}

extern "C" unsigned elisacoreFoldBoundedRemainders(LLVMModuleRef M) {
  return M ? foldBoundedRemainders(*unwrap(M)) : 0;
}
#else
extern "C" unsigned elisacoreFoldBoundedRemainders(LLVMModuleRef) { return 0; }
#endif
