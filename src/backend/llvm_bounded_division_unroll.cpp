// Bounded unrolling for simple monotone unsigned-division loops.
// This pass never weakens the loop's tests or arithmetic checks. The LVI range
// is used only to derive an unroll factor/cap; LLVM's unroller retains runtime
// exit checks. Proven recurrence bounds expose invariants only when the
// initial value is defined and every unsigned division remains defined.
#include <algorithm>
#include <llvm/Config/llvm-config.h>
#include <llvm/IR/Instructions.h>
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

static bool BDU_SkipFunction(const Function &F, const Module &M) {
  if (F.isDeclaration() || F.hasOptNone() || F.hasOptSize() || F.hasMinSize() ||
      F.getSubprogram() || M.getNamedMetadata("llvm.dbg.cu")) return true;
  for (StringRef Flag : {"SanitizeAddress", "SanitizeHWAddress", "SanitizeMemory",
                         "SanitizeThread", "SanitizeRealtime"})
    if (M.getModuleFlag(Flag)) return true;
  for (Attribute::AttrKind Attr : {Attribute::SanitizeAddress, Attribute::SanitizeHWAddress,
        Attribute::SanitizeMemory, Attribute::SanitizeThread, Attribute::SanitizeMemTag,
        Attribute::SanitizeRealtime, Attribute::SanitizeRealtimeBlocking})
    if (F.hasFnAttribute(Attr)) return true;
  return false;
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
#else
extern "C" unsigned elisacoreUnrollBoundedDivisionLoops(LLVMModuleRef) { return 0; }
#endif
