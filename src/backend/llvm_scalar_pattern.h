#pragma once

#include <llvm/IR/Constants.h>
#include <llvm/IR/Instructions.h>

inline llvm::BinaryOperator *scalarLoopBinOp(llvm::Value *V, unsigned Opcode, llvm::BasicBlock &Loop) {
  auto *Bin = llvm::dyn_cast_or_null<llvm::BinaryOperator>(V);
  return Bin && Bin->getOpcode() == Opcode && Bin->getParent() == &Loop ? Bin : nullptr;
}

inline bool scalarLoopHasConstant(llvm::Value *V, uint64_t Expected) {
  auto *C = llvm::dyn_cast<llvm::ConstantInt>(V);
  return C && C->equalsInt(Expected);
}

inline bool scalarLoopPair(llvm::BinaryOperator &Bin, llvm::Value *X, llvm::Value *Y) {
  return (Bin.getOperand(0) == X && Bin.getOperand(1) == Y) ||
         (Bin.getOperand(0) == Y && Bin.getOperand(1) == X);
}
