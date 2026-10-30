//go:build cgo
#include <llvm/Config/llvm-config.h>
#include <llvm-c/Core.h>
#if LLVM_VERSION_MAJOR == 23
#include <llvm/IR/Dominators.h>
#include <llvm/IR/Instructions.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/Intrinsics.h>
#include <llvm/Transforms/Utils/Mem2Reg.h>
#include <llvm/IR/Module.h>
#include <llvm/Passes/PassBuilder.h>
#include <llvm/Analysis/AssumptionCache.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/Analysis/OptimizationRemarkEmitter.h>
#include <llvm/Analysis/TargetTransformInfo.h>
#include <llvm/Analysis/ScalarEvolution.h>
#include <llvm/Support/CBindingWrapping.h>
#include <llvm/Transforms/Utils/LoopPeel.h>
#include <llvm/Transforms/Utils/LoopSimplify.h>
#include <llvm/Transforms/Utils/LoopUtils.h>
#include <llvm/Transforms/Utils/UnrollLoop.h>
using namespace llvm;
extern "C" unsigned elisacorePeelSmallValidationLoops(LLVMModuleRef moduleRef) {
  if (!moduleRef) return 0;
  Module &module = *unwrap(moduleRef);
  PassBuilder PB;
  LoopAnalysisManager LAM; FunctionAnalysisManager FAM;
  CGSCCAnalysisManager CGAM; ModuleAnalysisManager MAM;
  PB.registerModuleAnalyses(MAM); PB.registerCGSCCAnalyses(CGAM);
  PB.registerFunctionAnalyses(FAM); PB.registerLoopAnalyses(LAM);
  PB.crossRegisterProxies(LAM, FAM, CGAM, MAM);
  unsigned count = 0;
  for (Function &F : module) {
    if (F.isDeclaration() || F.hasOptNone() || F.hasMinSize() || F.hasOptSize()) continue;
    auto &LI = FAM.getResult<LoopAnalysis>(F);
    auto &DT = FAM.getResult<DominatorTreeAnalysis>(F);
    auto &SE = FAM.getResult<ScalarEvolutionAnalysis>(F);
    auto &AC = FAM.getResult<AssumptionAnalysis>(F);
    for (Loop *L : LI) {
      if (!L->getSubLoops().empty() || L->getNumBlocks() != 2 || L->getLoopID()) continue;
      unsigned loads = 0, instructions = 0, exits = 0, cmps = 0;
      bool safe = true;
      for (BasicBlock *BB : L->blocks()) for (Instruction &I : *BB) {
        ++instructions;
        if (auto *load = dyn_cast<LoadInst>(&I)) { if (!load->isSimple()) safe = false; ++loads; }
        else if (I.mayHaveSideEffects() && !isa<BranchInst>(I)) safe = false;
        if (isa<ICmpInst>(I)) ++cmps;
        if (auto *branch = dyn_cast<CondBrInst>(&I))
          for (auto *successor : branch->successors()) if (!L->contains(successor)) ++exits;
      }
      if (!safe || loads != 1 || instructions > 16 || exits != 2 || cmps != 2) continue;
      simplifyLoop(L, &DT, &LI, &SE, &AC, nullptr, false);
      if (!L->isLoopSimplifyForm() || !canPeel(L)) continue;
      formLCSSA(*L, DT, &LI, &SE);
      ValueToValueMapTy values;
      peelLoop(L, 1, false, &LI, &SE, DT, &AC, true, values);
      // Preserve every load and early exit in order. LLVM's unroller handles
      // the runtime remainder without speculating accesses past an invalid item.
      auto &TTI = FAM.getResult<TargetIRAnalysis>(F);
      auto &ORE = FAM.getResult<OptimizationRemarkEmitterAnalysis>(F);
      UnrollLoopOptions options{4, true, true, false, true, false, nullptr, 1000, true, false};
      UnrollLoop(L, options, &LI, &SE, &DT, &AC, &TTI, &ORE, true);
      ++count;
      break; // Invalidate function analyses before inspecting another loop.
    }
  }
  return count;
}
// A positive signed W-bit value divided by B >= 2 reaches zero in at
// most W-1 iterations. Each remainder is in [0,B-1], so a zero-based
// accumulator is bounded by (W-1)*(B-1). The recognizer checks the exact
// PHI recurrences, positive header guard, and signed maximum before elision.
// Other initializers, divisors, guards and update shapes retain their checks.
namespace {
struct DigitBound : PassInfoMixin<DigitBound> {
  PreservedAnalyses run(Function &F, FunctionAnalysisManager &AM) {
    auto &LI = AM.getResult<LoopAnalysis>(F);
    auto &DT = AM.getResult<DominatorTreeAnalysis>(F);
    SmallVector<Loop *, 16> work;
    for (auto *L : LI)
      work.push_back(L);
    bool changed = false;
    while (!work.empty()) {
      Loop *L = work.pop_back_val();
      for (auto *S : *L)
        work.push_back(S);
      BasicBlock *H = L->getHeader(), *P = L->getLoopPreheader(),
                 *B = L->getLoopLatch();
      if (!P || !B)
        continue;
      auto *br = dyn_cast<BranchInst>(H->getTerminator());
      if (!br || !br->isConditional())
        continue;
      auto *cmp = dyn_cast<ICmpInst>(br->getCondition());
      if (!cmp || cmp->getPredicate() != ICmpInst::ICMP_SGT)
        continue;
      auto *n = dyn_cast<PHINode>(cmp->getOperand(0));
      auto *zero = dyn_cast<ConstantInt>(cmp->getOperand(1));
      if (!n || n->getParent() != H || !zero || !zero->isZero() ||
          n->getNumIncomingValues() != 2)
        continue;
      auto *ty = dyn_cast<IntegerType>(n->getType());
      if (!ty || ty->getBitWidth() < 3 || ty->getBitWidth() > 64)
        continue;
      auto *div = dyn_cast<BinaryOperator>(n->getIncomingValueForBlock(B));
      if (!div || div->getOpcode() != Instruction::SDiv ||
          div->getOperand(0) != n || !L->contains(div))
        continue;
      auto *base = dyn_cast<ConstantInt>(div->getOperand(1));
      if (!base || base->isNegative() || base->getValue().ult(2))
        continue;
      uint64_t limit =
          APInt::getSignedMaxValue(ty->getBitWidth()).getZExtValue();
      uint64_t b = base->getZExtValue();
      if (b - 1 > limit / (ty->getBitWidth() - 1))
        continue;
      for (PHINode &total : H->phis()) {
        if (total.getType() != ty || total.getNumIncomingValues() != 2)
          continue;
        auto *init = dyn_cast<ConstantInt>(total.getIncomingValueForBlock(P));
        auto *value =
            dyn_cast<ExtractValueInst>(total.getIncomingValueForBlock(B));
        if (!init || !init->isZero() || !value || value->getNumIndices() != 1 ||
            *value->idx_begin() != 0)
          continue;
        auto *call = dyn_cast<IntrinsicInst>(value->getAggregateOperand());
        if (!call || call->getIntrinsicID() != Intrinsic::sadd_with_overflow ||
            !L->contains(call) || call->getParent() == H ||
            br->getSuccessor(0) == H ||
            !DT.dominates(br->getSuccessor(0), call->getParent()) ||
            L->contains(br->getSuccessor(1)))
          continue;
        Value *other = nullptr;
        if (call->getArgOperand(0) == &total)
          other = call->getArgOperand(1);
        else if (call->getArgOperand(1) == &total)
          other = call->getArgOperand(0);
        auto *rem = dyn_cast_or_null<BinaryOperator>(other);
        if (!rem || rem->getOpcode() != Instruction::SRem ||
            rem->getOperand(0) != n || rem->getOperand(1) != base)
          continue;
        IRBuilder<> builder(call);
        Value *sum = builder.CreateAdd(
            call->getArgOperand(0), call->getArgOperand(1), "proved.digit.sum");
        Value *result = PoisonValue::get(call->getType());
        result = builder.CreateInsertValue(result, sum, 0);
        result = builder.CreateInsertValue(result, builder.getFalse(), 1);
        call->replaceAllUsesWith(result);
        call->eraseFromParent();
        changed = true;
        break;
      }
    }
    return changed ? PreservedAnalyses::none() : PreservedAnalyses::all();
  }
};
} // namespace

extern "C" unsigned elisacoreElideBoundedDivisionSums(LLVMModuleRef moduleRef) {
  if (!moduleRef)
    return 0;
  Module &M = *unwrap(moduleRef);
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
  unsigned candidates = 0;
  for (Function &F : M) {
    if (F.isDeclaration() || F.hasOptNone() || F.hasOptSize() || F.hasMinSize())
      continue;
    bool div = false, rem = false, add = false;
    for (BasicBlock &B : F)
      for (Instruction &I : B) {
        div |= I.getOpcode() == Instruction::SDiv;
        rem |= I.getOpcode() == Instruction::SRem;
        if (auto *C = dyn_cast<IntrinsicInst>(&I))
          add |= C->getIntrinsicID() == Intrinsic::sadd_with_overflow;
      }
    if (!(div && rem && add))
      continue;
    FunctionPassManager FPM;
    FPM.addPass(PromotePass());
    FPM.addPass(LoopSimplifyPass());
    FPM.addPass(DigitBound());
    FPM.run(F, FAM);
    ++candidates;
  }
  return candidates;
}

#else
extern "C" unsigned elisacoreElideBoundedDivisionSums(LLVMModuleRef) {
  return 0;
}
extern "C" unsigned elisacorePeelSmallValidationLoops(LLVMModuleRef) { return 0; }
#endif
