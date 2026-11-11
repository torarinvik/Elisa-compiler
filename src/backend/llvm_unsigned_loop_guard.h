#pragma once

#include <llvm/IR/Instructions.h>

inline llvm::ICmpInst *rangeAndContinueTest(llvm::CondBrInst &Branch, llvm::BasicBlock *Continue,
                                    llvm::Value *Upper, llvm::Value *&Lower) {
  using llvm::ICmpInst;
  auto *Cmp = llvm::dyn_cast<ICmpInst>(Branch.getCondition());
  if (!Cmp || !Cmp->hasOneUse() || Branch.hasMetadataOtherThanDebugLoc() ||
      Branch.getSuccessor(0) == Branch.getSuccessor(1)) return nullptr;
  bool TrueEdge = Branch.getSuccessor(0) == Continue;
  if (!TrueEdge && Branch.getSuccessor(1) != Continue) return nullptr;
  auto Pred = TrueEdge ? Cmp->getPredicate() : Cmp->getInversePredicate();
  if (Pred == ICmpInst::ICMP_ULT && Cmp->getOperand(1) == Upper) {
    Lower = Cmp->getOperand(0);
    return Cmp;
  }
  if (Pred == ICmpInst::ICMP_UGT && Cmp->getOperand(0) == Upper) {
    Lower = Cmp->getOperand(1);
    return Cmp;
  }
  return nullptr;
}
