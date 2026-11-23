// Pool expensive scalar constants in small, acyclic AArch64 functions.
#include <llvm-c/Core.h>
#include <llvm-c/TargetMachine.h>
#include <llvm/ADT/SCCIterator.h>
#include <llvm/ADT/SmallVector.h>
#include <llvm/IR/Constants.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/Module.h>
#include <llvm/MC/MCSubtargetInfo.h>
#include <llvm/MC/TargetRegistry.h>
#include <llvm/Support/CBindingWrapping.h>
#include <llvm/Target/TargetMachine.h>
#include <llvm/Transforms/Utils/BasicBlockUtils.h>

#include <algorithm>
#include <cstdint>
#include <memory>

#include "llvm_exit_dead_stores.h"

namespace {
using namespace llvm;

struct PoolUse {
  Instruction *instruction;
  unsigned operand;
  unsigned slot;
};

bool needsMultipleImmediateInstructions(const ConstantFP &constant) {
  if (!constant.getType()->isDoubleTy() || !constant.getValueAPF().isNormal())
    return false;
  const uint64_t bits = constant.getValueAPF().bitcastToAPInt().getZExtValue();
  unsigned nonzero = 0;
  unsigned nonones = 0;
  for (unsigned shift = 0; shift < 64; shift += 16) {
    const uint64_t chunk = (bits >> shift) & 0xffff;
    nonzero += chunk != 0;
    nonones += chunk != 0xffff;
  }
  return std::min(nonzero, nonones) >= 3;
}

bool poolFunctionConstants(Function &function) {
  if (function.isDeclaration() || function.size() > 16 ||
      function.hasOptNone() ||
      function.hasFnAttribute("target-cpu") ||
      function.hasFnAttribute("target-features"))
    return false;
  const unsigned instructionCount = function.getInstructionCount();
  if (instructionCount > 160)
    return false;

  SmallVector<Constant *, 8> constants;
  SmallVector<PoolUse, 8> uses;
  bool allReturnEdges = true;
  unsigned comparisonUses = 0;
  unsigned returnEdgeUses = 0;
  for (BasicBlock &block : function) {
    for (Instruction &instruction : block) {
      const bool tinyResult = instructionCount <= 12 &&
          (isa<SelectInst>(instruction) || isa<ReturnInst>(instruction));
      const auto *phi = dyn_cast<PHINode>(&instruction);
      const bool returnPhi = instructionCount <= 16 && phi &&
          phi->getNumIncomingValues() <= 4 && phi->hasOneUse() &&
          isa<ReturnInst>(*phi->user_begin());

      const bool shortSubtraction = instructionCount <= 20 &&
          instruction.getOpcode() == Instruction::FSub;
      if (!shortSubtraction && !returnPhi && !isa<FCmpInst>(instruction) && !tinyResult &&
          instruction.getOpcode() != Instruction::FMul)
        continue;
      for (unsigned operand = 0; operand < instruction.getNumOperands(); ++operand) {
        auto *constant = dyn_cast<ConstantFP>(instruction.getOperand(operand));
        if (!constant || !needsMultipleImmediateInstructions(*constant))
          continue;
        if (returnPhi) {
          BasicBlock *predecessor = phi->getIncomingBlock(operand);
          if (!isa<BranchInst>(predecessor->getTerminator()))
            return false;
          for (unsigned other = 0; other < phi->getNumIncomingValues(); ++other)
            if (other != operand && phi->getIncomingBlock(other) == predecessor)
              return false;
        }
        auto existing = std::find(constants.begin(), constants.end(), constant);
        unsigned slot = static_cast<unsigned>(existing - constants.begin());
        if (existing == constants.end()) {
          if (constants.size() == 24)
            return false;
          constants.push_back(constant);
        }
        if (uses.size() == 24)
          return false;
        uses.push_back({&instruction, operand, slot});
        allReturnEdges &= returnPhi;
        comparisonUses += isa<FCmpInst>(instruction);
        returnEdgeUses += returnPhi;
      }
    }
  }
  const bool small = function.size() <= 12 && instructionCount <= 64;
  const bool distinct = constants.size() == uses.size();
  // In tiny functions the load sequence can replace a long immediate even
  // when only one operand uses it. Larger functions need more opportunities.
  // Three operands can share the table address in short straight-line code.
  const bool shortTable = instructionCount <= 20 && constants.size() >= 3;
  // A dense block can amortize the table address even across calls.
  const bool dense = constants.size() >= 12 && distinct &&
      std::all_of(uses.begin(), uses.end(), [&](const PoolUse &use) {
        return use.instruction->getParent() == uses.front().instruction->getParent();
      });
  const bool profitableInline = dense || (distinct
      ? small && constants.size() <= 8 &&
          (constants.size() >= 4 || instructionCount <= 12 || shortTable)
      : instructionCount <= 100 && constants.size() <= 8 &&
          uses.size() >= 6 && uses.size() <= 12 && constants.size() >= 3);
  // One expensive comparison literal can pay for its own load. The return
  // literal is loaded only on its incoming edge.
  const bool shortComparisonAndReturn = instructionCount <= 16 && distinct &&
      comparisonUses == 1 && returnEdgeUses == 1 && uses.size() == 2;
  if (constants.empty() ||
      (!allReturnEdges && !profitableInline && !shortComparisonAndReturn))
    return false;

  for (auto component = scc_begin(&function); !component.isAtEnd(); ++component)
    if (component.hasCycle())
      return false;

  Module &module = *function.getParent();
  Type *element = Type::getDoubleTy(module.getContext());
  auto *type = ArrayType::get(element, constants.size());
  auto *table = new GlobalVariable(module, type, true, GlobalValue::PrivateLinkage,
                                   ConstantArray::get(type, constants), "elisa.float.constants");
  table->setUnnamedAddr(GlobalValue::UnnamedAddr::Global);
  table->setAlignment(Align(8));
  for (const PoolUse &use : uses) {
    Instruction *insertionPoint = use.instruction;
    if (auto *phi = dyn_cast<PHINode>(use.instruction)) {
      BasicBlock *predecessor = phi->getIncomingBlock(use.operand);
      // The literal must stay on its incoming path so a cold return adds
      // no work to the path computing the normal result.
      if (predecessor->getTerminator()->getNumSuccessors() > 1)
        predecessor = SplitEdge(predecessor, phi->getParent());
      insertionPoint = predecessor->getTerminator();
    }
    IRBuilder<> builder(insertionPoint);
    Value *address = builder.CreateInBoundsGEP(type, table,
                                               {builder.getInt32(0), builder.getInt32(use.slot)});
    Value *value = builder.CreateAlignedLoad(element, address, Align(8));
    use.instruction->setOperand(use.operand, value);
  }
  return true;
}
} // namespace

extern "C" unsigned elisacorePoolFloatingConstants(LLVMModuleRef module,
                                                   LLVMTargetMachineRef machine) {
  if (!module || !machine)
    return 0;
  auto &target = *reinterpret_cast<llvm::TargetMachine *>(machine);
  // Late, so the bounded length reaches the copy after every inlining.
  unsigned expanded = ElisaBoundedCopies::expandBoundedCopies(*llvm::unwrap(module));
  if (!target.getTargetTriple().isAArch64())
    return expanded;
  // This is the last module pass before emission, which is where the trap
  // exit edges must be added (see llvm_trap_exit_edges.cpp). Stores that
  // only the final cleanups sink into a shared exit block die here first.
  unsigned changed = expanded + ElisaExitDeadStores::removeExitDeadStores(*llvm::unwrap(module));
  changed += ElisaTrapExits::connectTrapExits(*llvm::unwrap(module));
  changed += ElisaBitTests::orderBitTestOperands(*llvm::unwrap(module));
  const std::unique_ptr<llvm::MCSubtargetInfo> subtarget(
      target.getTarget().createMCSubtargetInfo(
          target.getTargetTriple(), target.getTargetCPU(), target.getTargetFeatureString()));
  if (!subtarget || !subtarget->checkFeatures("+fuse-literals"))
    return changed;
  for (llvm::Function &function : *llvm::unwrap(module))
    changed += poolFunctionConstants(function);
  return changed;
}
