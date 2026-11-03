// Share reciprocal formation only where the source IR explicitly permits it.
#include <llvm-c/Core.h>
#include <llvm/ADT/MapVector.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/Module.h>
#include <llvm/Support/CBindingWrapping.h>
using namespace llvm;

static unsigned elisacoreShareReciprocals(LLVMModuleRef ref) {
  if (!ref) return 0;
  unsigned changed = 0;
  for (Function &F : *unwrap(ref)) {
    if (F.isDeclaration() || F.hasOptNone() || F.hasFnAttribute(Attribute::StrictFP)) continue;
    MapVector<Value *, SmallVector<BinaryOperator *, 8>> groups;
    unsigned instructions = 0;
    for (BasicBlock &BB : F) for (Instruction &I : BB) {
      ++instructions;
      auto *D = dyn_cast<BinaryOperator>(&I);
      if (!D || D->getOpcode() != Instruction::FDiv ||
          (!D->getType()->isFloatTy() && !D->getType()->isDoubleTy()) || !D->hasAllowReciprocal() ||
          isa<Constant>(D->getOperand(1)) || D->hasMetadataOtherThanDebugLoc()) continue;
      groups[D->getOperand(1)].push_back(D);
    }
    // Bound compile-time work. At least three divisions must share a denominator to justify
    // creating a reciprocal and extending its live range.
    if (instructions > 2000) continue;
    bool candidate = false;
    for (auto &G : groups) if (G.second.size() >= 3) candidate = true;
    if (!candidate) continue;
    DominatorTree DT(F);
    for (auto &G : groups) {
      auto &divisions = G.second;
      if (divisions.size() < 3 || divisions.size() > 64) continue;
      BinaryOperator *first = nullptr;
      for (auto *D : divisions) {
        bool dominates = true;
        for (auto *Other : divisions) if (D != Other && !DT.dominates(D, Other)) dominates = false;
        if (dominates) { first = D; break; }
      }
      // Do not speculate FP operations onto paths that never divided, or move
      // them across control flow merely to find a common dominator.
      if (!first) continue;
      IRBuilder<> B(first);
      B.SetCurrentDebugLocation(first->getDebugLoc());
      FastMathFlags flags;
      flags.setAllowReciprocal();
      flags.setAllowContract(first->hasAllowContract());
      B.setFastMathFlags(flags);
      Value *denominator = B.CreateFreeze(first->getOperand(1), "recip.denominator");
      Value *reciprocal = B.CreateFDiv(ConstantFP::get(first->getType(), 1.0),
                                     denominator, "shared.reciprocal");
      for (auto *D : divisions) {
        B.SetInsertPoint(D);
        B.SetCurrentDebugLocation(D->getDebugLoc());
        FastMathFlags multiplyFlags;
        multiplyFlags.setAllowContract(D->hasAllowContract());
        B.setFastMathFlags(multiplyFlags);
        // In particular, do not put nnan/ninf on the new intermediate: a
        // reciprocal can overflow even when the original quotient is finite.
        Value *result = B.CreateFMul(D->getOperand(0), reciprocal, "recip.product");
        D->replaceAllUsesWith(result);
        D->eraseFromParent();
        ++changed;
      }
    }
  }
  return changed;
}
