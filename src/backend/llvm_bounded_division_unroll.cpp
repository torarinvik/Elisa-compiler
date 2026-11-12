// Bounded unrolling for simple monotone unsigned-division loops.
// This pass never weakens the loop's tests or arithmetic checks. The LVI range
// is used only to derive an unroll factor/cap; LLVM's unroller retains runtime
// exit checks. Proven recurrence bounds expose invariants only when the
// initial value is defined and every unsigned division remains defined.
#include <algorithm>
#include "llvm_loop_pass_policy.h"
#include <llvm/Config/llvm-config.h>
#include <llvm/IR/Instructions.h>
#include <llvm/IR/InstIterator.h>
#include <llvm/Analysis/TargetLibraryInfo.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/Module.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/IR/ConstantRange.h>
#include <llvm/Analysis/LazyValueInfo.h>
#include <llvm/Analysis/ValueTracking.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/Analysis/ScalarEvolution.h>
#include <llvm/Analysis/AssumptionCache.h>
#include <llvm/Analysis/OptimizationRemarkEmitter.h>
#include <llvm/Analysis/TargetTransformInfo.h>
#include <llvm/IR/Dominators.h>
#include <llvm/Passes/PassBuilder.h>
#include <llvm/Transforms/Utils/LoopUtils.h>
#include <llvm/Transforms/Utils/LoopPeel.h>
#include <llvm/Transforms/Utils/ValueMapper.h>
#include <llvm/Transforms/Utils/BasicBlockUtils.h>
#include <llvm/Transforms/Utils/UnrollLoop.h>
#include <llvm/Support/CBindingWrapping.h>

#if LLVM_VERSION_MAJOR >= 23
using namespace llvm;

namespace {
constexpr unsigned BDU_MaxTrips = 16;
constexpr unsigned BDU_MaxFunctionInstructions = 800;
constexpr unsigned BDU_MaxLoopInstructions = 64;
constexpr unsigned BDU_MaxGrowthInstructions = 256;
constexpr unsigned BDU_MaxModuleGrowth = 1024;

static bool BDU_NoUnrollPolicy(const Loop &L) {
  MDNode *ID = L.getLoopID();
  if (!ID) return true;
  if (ID->getNumOperands() > 64) return false;
  for (unsigned I = 1; I < ID->getNumOperands(); ++I) {
    auto *Property = dyn_cast_or_null<MDNode>(ID->getOperand(I).get());
    if (!Property || !Property->getNumOperands()) return false;
    auto *Tag = dyn_cast_or_null<MDString>(Property->getOperand(0).get());
    if (!Tag || Tag->getString().starts_with("llvm.loop.unroll")) return false;
  }
  return true;
}

// Cheap gate before building LoopInfo/SE/DT/LVI for a function. The current
// transform requires both a constant unsigned division recurrence and a
// checked increment, so functions without either cannot qualify.
static bool BDU_MayContainCandidate(const Function &F, unsigned FunctionInsts) {
  if (FunctionInsts > BDU_MaxFunctionInstructions) return false;
  bool HasDiv = false, HasCheckedAdd = false;
  for (const BasicBlock &BB : F) for (const Instruction &I : BB) {
    if (auto *BO = dyn_cast<BinaryOperator>(&I)) {
      if (BO->getOpcode() == Instruction::UDiv) {
        auto *C = dyn_cast<ConstantInt>(BO->getOperand(1));
        if (C && C->getValue().getActiveBits() <= 32 && C->getZExtValue() >= 2)
          HasDiv = true;
      }
    }
    if (auto *CB = dyn_cast<CallBase>(&I)) {
      auto *II = dyn_cast<IntrinsicInst>(CB);
      if (II && (II->getIntrinsicID() == Intrinsic::sadd_with_overflow ||
                 II->getIntrinsicID() == Intrinsic::uadd_with_overflow))
        HasCheckedAdd = true;
    }
    if (HasDiv && HasCheckedAdd) return true;
  }
  return false;
}

static bool BDU_IsTrap(const CallBase &CB) {
  auto *II = dyn_cast<IntrinsicInst>(&CB);
  return II && II->getIntrinsicID() == Intrinsic::trap &&
         !CB.hasOperandBundles() && !CB.isConvergent();
}

static bool BDU_IsCheckedArithmetic(const CallBase &CB) {
  auto *II = dyn_cast<IntrinsicInst>(&CB);
  if (!II || CB.hasOperandBundles() || CB.isConvergent()) return false;
  switch (II->getIntrinsicID()) {
  case Intrinsic::sadd_with_overflow:
  case Intrinsic::ssub_with_overflow:
  case Intrinsic::smul_with_overflow:
  case Intrinsic::uadd_with_overflow:
  case Intrinsic::usub_with_overflow:
  case Intrinsic::umul_with_overflow:
    return true;
  default:
    return false;
  }
}

static bool BDU_IsTrapBlock(const BasicBlock &BB) {
  bool SawTrap = false;
  for (const Instruction &I : BB) {
    if (isa<DbgInfoIntrinsic>(I)) continue;
    if (auto *CB = dyn_cast<CallBase>(&I)) {
      if (!BDU_IsTrap(*CB) || SawTrap) return false;
      SawTrap = true;
    } else if (!isa<UnreachableInst>(I)) {
      return false;
    }
  }
  return SawTrap && isa<UnreachableInst>(BB.getTerminator());
}

static bool BDU_SafeLoop(const Loop &L, unsigned &Insts) {
  if (L.getNumBlocks() != 2 || !L.getSubLoops().empty()) return false;
  unsigned NormalExitEdges = 0;
  for (BasicBlock *BB : L.blocks()) {
    if (!isa<BranchInst>(BB->getTerminator())) return false;
    for (Instruction &I : *BB) {
      ++Insts;
      if (isa<LoadInst>(I) || isa<StoreInst>(I) || isa<AtomicRMWInst>(I) ||
          isa<AtomicCmpXchgInst>(I) || isa<AllocaInst>(I) || isa<InvokeInst>(I) ||
          isa<CallBrInst>(I) || isa<VAArgInst>(I) || isa<FenceInst>(I) ||
          isa<IndirectBrInst>(I)) return false;
      if (auto *CB = dyn_cast<CallBase>(&I))
        if (!BDU_IsTrap(*CB) && !BDU_IsCheckedArithmetic(*CB)) return false;
      if (auto *BI = dyn_cast<BranchInst>(&I)) {
        for (BasicBlock *Succ : BI->successors()) {
          if (!L.contains(Succ) && !BDU_IsTrapBlock(*Succ)) ++NormalExitEdges;
        }
      }
    }
  }
  return Insts <= BDU_MaxLoopInstructions && NormalExitEdges == 1;
}

struct BDU_Candidate {
  Loop *L = nullptr;
  PHINode *P = nullptr;
  BinaryOperator *Div = nullptr;
  Value *Initial = nullptr;
  BasicBlock *Pred = nullptr;
  unsigned Divisor = 0;
  unsigned Bound = 0;
  ConstantInt *InitialMax = nullptr;
  unsigned Growth = 0;
};

static bool BDU_FindCandidate(Loop &L, LazyValueInfo &LVI,
                              BDU_Candidate &Out) {
  BasicBlock *Header = L.getHeader();
  BasicBlock *Pred = L.getLoopPredecessor();
  if (!Header || !Pred || !L.contains(Header) || !BDU_NoUnrollPolicy(L)) return false;
  unsigned LoopInsts = 0;
  if (!BDU_SafeLoop(L, LoopInsts)) return false;
  auto *BI = dyn_cast<BranchInst>(Header->getTerminator());
  auto *Cmp = BI && BI->isConditional()
                  ? dyn_cast<ICmpInst>(BI->getCondition()) : nullptr;
  if (!Cmp) return false;
  BasicBlock *T = BI->getSuccessor(0), *F = BI->getSuccessor(1);
  if (L.contains(T) == L.contains(F)) return false;

  auto IsZero = [](Value *V) {
    auto *C = dyn_cast<ConstantInt>(V);
    return C && C->isZero();
  };
  for (PHINode &P : Header->phis()) {
    if (P.getNumIncomingValues() != 2) continue;
    int PreIdx = P.getBasicBlockIndex(Pred);
    if (PreIdx < 0) continue;
    int BackIdx = 1 - PreIdx;
    BasicBlock *BackPred = P.getIncomingBlock(BackIdx);
    if (!L.contains(BackPred)) continue;
    auto *Div = dyn_cast<BinaryOperator>(P.getIncomingValue(BackIdx));
    if (!Div || Div->getOpcode() != Instruction::UDiv || Div->getOperand(0) != &P ||
        Div->getParent() != BackPred) continue;
    auto *DivC = dyn_cast<ConstantInt>(Div->getOperand(1));
    if (!DivC || DivC->getValue().getActiveBits() > 32) continue;
    uint64_t Divisor64 = DivC->getZExtValue();
    if (Divisor64 < 2 || Divisor64 > UINT32_MAX) continue;
    unsigned Divisor = static_cast<unsigned>(Divisor64);

    Value *Other = nullptr;
    if (Cmp->getOperand(0) == &P) Other = Cmp->getOperand(1);
    if (Cmp->getOperand(1) == &P) Other = Cmp->getOperand(0);
    if (!Other) continue;
    bool ThresholdExit = false;
    bool TestMatches = false;
    if (Cmp->getPredicate() == ICmpInst::ICMP_ULT) {
      auto *K = dyn_cast<ConstantInt>(Other);
      TestMatches = Cmp->getOperand(0) == &P && K && K->getValue().getActiveBits() <= 32 &&
                    K->getZExtValue() == Divisor && L.contains(F) && !L.contains(T);
      ThresholdExit = true;
    } else if (Cmp->getPredicate() == ICmpInst::ICMP_NE) {
      TestMatches = IsZero(Other) && L.contains(T) && !L.contains(F);
    }
    if (!TestMatches) continue;

    Instruction *Context = Pred->getTerminator();
    ConstantRange R = LVI.getConstantRangeOnEdge(P.getIncomingValue(PreIdx),
                                                  Pred, Header, Context);
    if (R.isEmptySet() || R.isFullSet() || R.getBitWidth() == 0) continue;
    APInt Max = R.getUnsignedMax();
    APInt C(Max.getBitWidth(), Divisor);
    unsigned Trips = 0;
    while (ThresholdExit ? Max.uge(C) : !Max.isZero()) {
      if (++Trips > BDU_MaxTrips) break;
      Max = Max.udiv(C);
    }
    if (!Trips || Trips > BDU_MaxTrips) continue;
    unsigned Count = std::min(Trips + 1, BDU_MaxTrips);
    unsigned Growth = (LoopInsts + 2) * (Count - 1) + 2;
    if (Growth > BDU_MaxGrowthInstructions) continue;

    Out = {&L, &P, Div, P.getIncomingValue(PreIdx), Pred, Divisor, Trips,
           ConstantInt::get(P.getContext(), R.getUnsignedMax()), Growth};
    return true;
  }
  return false;
}

static PHINode *BDU_FindRecurrence(Loop &L, unsigned Divisor) {
  for (PHINode &P : L.getHeader()->phis()) {
    if (P.getNumIncomingValues() != 2) continue;
    Value *InsideValue = nullptr;
    for (unsigned I = 0; I != 2; ++I)
      if (L.contains(P.getIncomingBlock(I))) InsideValue = P.getIncomingValue(I);
    auto *D = dyn_cast_or_null<BinaryOperator>(InsideValue);
    auto *C = D ? dyn_cast<ConstantInt>(D->getOperand(1)) : nullptr;
    if (D && D->getOpcode() == Instruction::UDiv && D->getOperand(0) == &P &&
        C && C->getValue() == APInt(C->getBitWidth(), Divisor)) return &P;
  }
  return nullptr;
}
// A checked additive recurrence can use an ordinary add only when its known
// constant initial value plus every update in this bounded loop fits exactly.
// The division bound counts backedges, not header visits.
static unsigned BDU_FoldCheckedCounter(Loop &L, unsigned Bound) {
  SmallVector<CallInst *, 4> Erase;
  for (PHINode &P : L.getHeader()->phis()) {
    auto *ST = dyn_cast<StructType>(P.getType());
    if (!ST || ST->getNumElements() != 2 || !ST->getElementType(0)->isIntegerTy() ||
        !ST->getElementType(1)->isIntegerTy(1) || P.getNumIncomingValues() != 2) continue;
    BasicBlock *Pred = L.getLoopPredecessor();
    int InitialIdx = P.getBasicBlockIndex(Pred);
    if (InitialIdx < 0) continue;
    Value *Initial = P.getIncomingValue(InitialIdx);
    auto *Start = dyn_cast_or_null<ConstantInt>(dyn_cast<Constant>(Initial)
                     ? cast<Constant>(Initial)->getAggregateElement(0u) : nullptr);
    auto *InitialOverflow = dyn_cast_or_null<ConstantInt>(dyn_cast<Constant>(Initial)
                     ? cast<Constant>(Initial)->getAggregateElement(1u) : nullptr);
    auto *Call = dyn_cast<IntrinsicInst>(P.getIncomingValue(1 - InitialIdx));
    if (!Start || !InitialOverflow || !InitialOverflow->isZero() || !Call ||
        Call->getIntrinsicID() != Intrinsic::sadd_with_overflow ||
        Call->hasOperandBundles() || Call->isConvergent() ||
        Call->getParent() != P.getIncomingBlock(1 - InitialIdx)) continue;
    ConstantInt *Step = nullptr;
    ExtractValueInst *Counter = nullptr;
    for (unsigned I = 0; I != 2; ++I) {
      auto *C = dyn_cast<ConstantInt>(Call->getArgOperand(I));
      auto *E = dyn_cast<ExtractValueInst>(Call->getArgOperand(1-I));
      if (C && E && E->getAggregateOperand() == &P &&
          E->getNumIndices() == 1 && *E->idx_begin() == 0) {Step=C; Counter=E;}
    }
    if (!Step || !Counter) continue;
    unsigned Width = Start->getBitWidth();
    APInt First = Start->getValue().sext(Width + 6);
    APInt Last = First + Step->getValue().sext(Width + 6) * APInt(Width + 6, Bound);
    if (!First.isSignedIntN(Width) || !Last.isSignedIntN(Width)) continue;
    IRBuilder<> B(Call);
    Value *Sum = B.CreateNSWAdd(Counter, Step, "bounded.counter");
    Value *Pair = B.CreateInsertValue(PoisonValue::get(P.getType()), Sum, 0);
    Pair = B.CreateInsertValue(Pair, B.getFalse(), 1);
    Call->replaceAllUsesWith(Pair);
    Erase.push_back(Call);
  }
  for (CallInst *C : Erase) C->eraseFromParent();
  return Erase.size();
}
} // namespace

extern "C" unsigned elisacoreUnrollBoundedDivisionLoops(LLVMModuleRef Ref) {
  if (!Ref) return 0;
  Module &M = *unwrap(Ref);
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

  unsigned Changed = 0;
  unsigned GrowthBudget = 0;
  unsigned AnalyzedFunctions = 0;
  unsigned AnalyzedLoops = 0;
  for (Function &F : M) {
    if (AnalyzedLoops >= 64) break;
    if (BDU_SkipFunction(F, M)) continue;
    unsigned FunctionInsts = 0;
    for (BasicBlock &BB : F) FunctionInsts += BB.size();
    if (!BDU_MayContainCandidate(F, FunctionInsts)) continue;
    if (++AnalyzedFunctions > 32) break;

    auto &LI = FAM.getResult<LoopAnalysis>(F);
    auto &DT = FAM.getResult<DominatorTreeAnalysis>(F);
    auto &SE = FAM.getResult<ScalarEvolutionAnalysis>(F);
    auto &AC = FAM.getResult<AssumptionAnalysis>(F);
    auto &LVI = FAM.getResult<LazyValueAnalysis>(F);
    auto &TTI = FAM.getResult<TargetIRAnalysis>(F);
    auto &ORE = FAM.getResult<OptimizationRemarkEmitterAnalysis>(F);
    for (Loop *L : LI) {
      if (++AnalyzedLoops > 64) break;
      if (!L) continue;
      BDU_Candidate C;
      if (!BDU_FindCandidate(*L, LVI, C)) continue;
      if (GrowthBudget + C.Growth > BDU_MaxModuleGrowth) continue;
      GrowthBudget += C.Growth;

      // Range proof and shape recognition happen before CFG normalization, on
      // the actual outside predecessor edge. Only a proven candidate is
      // normalized; this avoids rewriting unrelated loops in the function.
      bool DefinedRecurrence = !C.Div->isExact() &&
          isGuaranteedNotToBeUndefOrPoison(C.Initial, &AC, C.Pred->getTerminator(), &DT);
      unsigned Folded = DefinedRecurrence ? BDU_FoldCheckedCounter(*L, C.Bound) : 0;
      if (DefinedRecurrence) {
        // UDiv by a constant >= 2 cannot increase an unsigned value. InitialMax
        // was proved on the unique entry edge. Reject exact division and
        // potentially undef/poison inputs before making the invariant explicit.
        IRBuilder<> B(L->getHeader()->getTerminator());
        Value *Valid = B.CreateICmpULE(C.P, C.InitialMax);
        AC.registerAssumption(cast<AssumeInst>(B.CreateAssumption(Valid)));
        ++Changed;
      }
      Changed += Folded;
      if (Folded || DefinedRecurrence) SE.forgetLoop(L);
      bool Normalized = simplifyLoop(L, &DT, &LI, &SE, &AC, nullptr, false);
      if (L->isLoopSimplifyForm()) Normalized |= formLCSSA(*L, DT, &LI, &SE);
      if (Normalized) ++Changed;
      if (!L->isLoopSimplifyForm()) break; // LVI may have been invalidated.
      PHINode *P = BDU_FindRecurrence(*L, C.Divisor);
      if (!P) break; // Never query the stale pre-normalization LVI again.

      UnrollLoopOptions Options{std::min(C.Bound + 1, BDU_MaxTrips), false, false, false, true, false,
                                nullptr, 1000, true, false};
      Loop *Remainder = nullptr;
      LoopUnrollResult Result = UnrollLoop(L, Options, &LI, &SE, &DT, &AC,
                                           &TTI, &ORE, true, &Remainder);
      if (Result != LoopUnrollResult::Unmodified) {
        ++Changed;
      }
      break; // Normalization/unrolling may invalidate LVI; never inspect next loop.
    }
  }
  return Changed;
}
struct AffineLaggedRecurrence {
  PHINode *Previous = nullptr;
  PHINode *Current = nullptr;
  BinaryOperator *Bias = nullptr;
  BinaryOperator *Sum = nullptr;
  ConstantInt *Offset = nullptr;
};

// With wrapping arithmetic, shifting both states by C turns
// next = previous + current + C into an ordinary two-state sum.
static bool rebaseLaggedRecurrence(const AffineLaggedRecurrence &R, Loop &L) {
  BasicBlock *Header = L.getHeader(), *Entry = L.getLoopPreheader();
  auto *Prev = dyn_cast_or_null<ConstantInt>(R.Previous->getIncomingValueForBlock(Entry));
  auto *Current = dyn_cast_or_null<ConstantInt>(R.Current->getIncomingValueForBlock(Entry));
  if (!Prev || !Current) return false;
  SmallVector<PHINode *, 2> Exits;
  for (User *U : R.Sum->users()) {
    if (U == R.Current) continue;
    auto *Exit = dyn_cast<PHINode>(U);
    if (!Exit || L.contains(Exit->getParent()) || Exit->getNumIncomingValues() != 1 ||
        Exit->getIncomingBlock(0) != Header)
      return false;
    Exits.push_back(Exit);
  }
  LLVMContext &Ctx = Header->getContext();
  R.Previous->setIncomingValueForBlock(Entry, ConstantInt::get(Ctx, Prev->getValue() + R.Offset->getValue()));
  R.Current->setIncomingValueForBlock(Entry, ConstantInt::get(Ctx, Current->getValue() + R.Offset->getValue()));
  R.Sum->replaceUsesOfWith(R.Bias, R.Bias->getOperand(0));
  R.Bias->eraseFromParent();
  for (PHINode *Exit : Exits) {
    IRBuilder<> B(Exit->getParent(), Exit->getParent()->getFirstNonPHIIt());
    auto *Value = cast<Instruction>(B.CreateSub(Exit, R.Offset));
    Exit->replaceUsesWithIf(Value, [Value](Use &U) { return U.getUser() != Value; });
  }
  return true;
}

// Unroll small lagged recurrences by full state rotations. Peel the first
// iteration of two-state loops to keep one-trip inputs out of the remainder.
static unsigned laggedRecurrenceUnrollFactor(BasicBlock &B, AffineLaggedRecurrence &Affine) {
  auto *Branch = dyn_cast<CondBrInst>(B.getTerminator());
  auto *Cmp = Branch ? dyn_cast<ICmpInst>(Branch->getCondition()) : nullptr;
  if (!Cmp || !Cmp->isEquality() || (B.size() != 7 && B.size() != 8) ||
      Branch->getSuccessor(Cmp->getPredicate() == ICmpInst::ICMP_EQ ? 1 : 0) != &B ||
      Branch->getSuccessor(Cmp->getPredicate() == ICmpInst::ICMP_EQ ? 0 : 1) == &B)
    return 0;
  auto *Counter = dyn_cast<PHINode>(Cmp->getOperand(0));
  if (!Counter || Counter->getParent() != &B ||
      !Counter->getType()->isIntegerTy(64) || Counter->getNumIncomingValues() != 2)
    return 0;
  auto *Step = dyn_cast<BinaryOperator>(Counter->getIncomingValueForBlock(&B));
  auto *One = Step ? dyn_cast<ConstantInt>(Step->getOperand(1)) : nullptr;
  if (!Step || Step->getParent() != &B || Step->getOpcode() != Instruction::Add ||
      Step->getOperand(0) != Counter || !One || !One->isOne()) return 0;
  unsigned PhiCount = 0;
  BinaryOperator *Sum = nullptr, *Scale = nullptr, *Bias = nullptr;
  for (Instruction &I : B) {
    if (isa<PHINode>(I)) { ++PhiCount; continue; }
    if (&I == Step || &I == Cmp || &I == Branch) continue;
    if (!Sum && I.getOpcode() == Instruction::Add) {
      Sum = cast<BinaryOperator>(&I);
    } else if (!Scale && !Bias && I.getOpcode() == Instruction::Shl) {
      Scale = cast<BinaryOperator>(&I);
    } else if (!Scale && !Bias && Sum && I.getOpcode() == Instruction::Add) {
      Bias = Sum;
      Sum = cast<BinaryOperator>(&I);
    } else {
      return 0;
    }
  }
  if (!Sum) return 0;
  auto Shift = [&](Value *V) -> PHINode * {
    auto *P = dyn_cast<PHINode>(V);
    return P && P != Counter && P->getParent() == &B &&
           P->getNumIncomingValues() == 2 ? P : nullptr;
  };
  if (Bias) {
    auto *Offset = dyn_cast<ConstantInt>(Bias->getOperand(1));
    if (PhiCount != 3 || !Offset || Offset->isZero() || !Bias->hasOneUse() ||
        Bias->hasNoSignedWrap() || Bias->hasNoUnsignedWrap() ||
        Sum->hasNoSignedWrap() || Sum->hasNoUnsignedWrap())
      return 0;
    Value *Other = Sum->getOperand(0);
    if (Sum->getOperand(1) != Bias) {
      if (Other != Bias) return 0;
      Other = Sum->getOperand(1);
    }
    PHINode *Previous = Shift(Bias->getOperand(0)), *Current = Shift(Other);
    if (!Previous || !Current || Previous == Current) return 0;
    if (Current->getIncomingValueForBlock(&B) == Previous)
      std::swap(Previous, Current);
    if (Previous->getIncomingValueForBlock(&B) != Current ||
        Current->getIncomingValueForBlock(&B) != Sum ||
        !Previous->hasOneUse() || !Current->hasNUses(2))
      return 0;
    Affine = {Previous, Current, Bias, Sum, Offset};
    return 4;
  }
  if (Scale) {
    if (PhiCount != 3 || !Scale->hasOneUse()) return 0;
    auto *OneBit = dyn_cast<ConstantInt>(Scale->getOperand(1));
    auto *Current = Shift(Scale->getOperand(0));
    Value *Other = Sum->getOperand(0);
    if (Sum->getOperand(1) != Scale) {
      if (Other != Scale) return 0;
      Other = Sum->getOperand(1);
    }
    auto *Previous = Shift(Other);
    return OneBit && OneBit->isOne() && Current && Previous && Current != Previous &&
                   Previous->getIncomingValueForBlock(&B) == Current &&
                   Current->getIncomingValueForBlock(&B) == Sum ? 4 : 0;
  }
  PHINode *A = Shift(Sum->getOperand(0)), *Next = Shift(Sum->getOperand(1));
  if (!A || !Next || A == Next) return 0;
  if (A->getIncomingValueForBlock(&B) != Next) std::swap(A, Next);
  if (A->getIncomingValueForBlock(&B) != Next) return 0;
  if (PhiCount == 3)
    return Next->getIncomingValueForBlock(&B) == Sum ? 4 : 0;
  if (PhiCount != 4) return 0;
  auto *Newest = Shift(Next->getIncomingValueForBlock(&B));
  return Newest && Newest != A && Newest != Next &&
         Newest->getIncomingValueForBlock(&B) == Sum ? 3 : 0;
}

// An entry switch may exclude short inputs without exposing the bound
// to ScalarEvolution. The matcher already proves a unit-step counter.
static unsigned laggedRecurrenceSwitchTripBound(Loop &L, LazyValueInfo &LVI) {
  BasicBlock *Header = L.getHeader(), *Entry = L.getLoopPredecessor();
  auto *Dispatch = Entry ? dyn_cast<SwitchInst>(Entry->getTerminator()) : nullptr;
  if (!Dispatch || Dispatch->getDefaultDest() != Header) return 0;
  auto *Cmp = cast<ICmpInst>(cast<CondBrInst>(Header->getTerminator())->getCondition());
  auto *Counter = cast<PHINode>(Cmp->getOperand(0));
  auto *Start = dyn_cast<ConstantInt>(Counter->getIncomingValueForBlock(Entry));
  Value *Limit = Cmp->getOperand(1);
  if (!Start || Limit != Dispatch->getCondition()) return 0;
  ConstantRange Range = LVI.getConstantRangeOnEdge(Limit, Entry, Header, Cmp);
  if (Range.isEmptySet() || Range.getUnsignedMin().ult(Start->getValue()) ||
      Range.getUnsignedMax().isMaxValue())
    return 0;
  APInt Trips = Range.getUnsignedMax() - Start->getValue() + 1;
  return Trips.getLimitedValue(257);
}

extern "C" unsigned elisacoreUnrollLaggedRecurrences(LLVMModuleRef Ref) {
  if (!Ref) return 0;
  Module &M = *unwrap(Ref);
  if (!M.getTargetTriple().isAArch64()) return 0;
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
  unsigned Changed = 0, Analyzed = 0;
  for (Function &F : M) {
    if (BDU_SkipFunction(F, M) || F.size() > 24) continue;
    for (BasicBlock &B : F) {
      AffineLaggedRecurrence Affine;
      unsigned Factor = laggedRecurrenceUnrollFactor(B, Affine);
      if (!Factor) continue;
      if (++Analyzed > 32) return Changed;
      auto &LI = FAM.getResult<LoopAnalysis>(F);
      Loop *L = LI.getLoopFor(&B);
      if (!L || L->getHeader() != &B || L->getParentLoop() || L->getLoopID() ||
          L->getNumBlocks() != 1) break;
      auto &SE = FAM.getResult<ScalarEvolutionAnalysis>(F);
      unsigned MaxTrips = SE.getSmallConstantMaxTripCount(L);
      if (!MaxTrips && Factor == 4)
        MaxTrips = laggedRecurrenceSwitchTripBound(*L, FAM.getResult<LazyValueAnalysis>(F));
      if (MaxTrips < 16 || MaxTrips > 256) break;
      auto &DT = FAM.getResult<DominatorTreeAnalysis>(F);
      auto &AC = FAM.getResult<AssumptionAnalysis>(F);
      auto &TTI = FAM.getResult<TargetIRAnalysis>(F);
      auto &ORE = FAM.getResult<OptimizationRemarkEmitterAnalysis>(F);
      if (simplifyLoop(L, &DT, &LI, &SE, &AC, nullptr, false)) ++Changed;
      if (!L->isLoopSimplifyForm()) break;
      if (formLCSSA(*L, DT, &LI, &SE)) ++Changed;
      if (Factor == 4) {
        if (!canPeel(L)) break;
        if (Affine.Bias) {
          if (!rebaseLaggedRecurrence(Affine, *L)) break;
          SE.forgetLoop(L);
        }
        ValueToValueMapTy FirstIteration;
        peelLoop(L, 1, false, &LI, &SE, DT, &AC, true, FirstIteration);
        ++Changed;
      }
      UnrollLoopOptions Options{Factor, true, true, true, false, false, nullptr, 1000};
      if (UnrollLoop(L, Options, &LI, &SE, &DT, &AC, &TTI, &ORE, true) !=
          LoopUnrollResult::Unmodified) ++Changed;
      break;
    }
  }
  return Changed;
}

#include "llvm_shift_parity.cpp"
#include "llvm_shift_bit_reverse.cpp"
#include "llvm_power_position.cpp"
#include "llvm_range_and.cpp"
#include "llvm_masked_single_bit.cpp"
#include "llvm_conditional_doubling.cpp"
#include "llvm_shift_xor.cpp"
#include "llvm_edge_division_reuse.cpp"
#include "llvm_factored_unsigned_division.cpp"
#include "llvm_remainder_recurrence.cpp"
#include "llvm_constant_paths.cpp"
#include "llvm_literal_divisor_specialization.cpp"
#include "llvm_reverse_byte_fold.cpp"
#include "llvm_stack_view_inline.cpp"
#include "llvm_bounded_quotient_sum.cpp"
#include "llvm_bounded_carry.cpp"

#else
extern "C" unsigned elisacoreUnrollLaggedRecurrences(LLVMModuleRef) { return 0; }
extern "C" unsigned elisacoreUnrollBoundedDivisionLoops(LLVMModuleRef) { return 0; }
#endif
