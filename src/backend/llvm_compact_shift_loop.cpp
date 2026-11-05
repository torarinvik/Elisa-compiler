// Keep short fixed-trip bit-at-a-time recurrences compact. Unrolling dozens of
// variable-shift iterations can overwhelm the hot instruction stream. This
// changes only LLVM's unroll policy; all original checks and operations remain.
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/Analysis/ScalarEvolution.h>
#include <llvm/Analysis/ScalarEvolutionExpressions.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/IR/Metadata.h>
#include <llvm/IR/Module.h>
using namespace llvm;
namespace {
static unsigned markCompactShiftLoops(Module &M) {
  if (!M.getTargetTriple().isAArch64() || M.getNamedMetadata("llvm.dbg.cu")) return 0;
  unsigned Changed = 0;
  for (Function &F : M) {
    if (F.isDeclaration() || F.hasOptNone() || F.hasOptSize() || F.hasMinSize() ||
        F.hasFnAttribute(Attribute::SanitizeAddress) || F.hasFnAttribute(Attribute::SanitizeMemory) ||
        F.hasFnAttribute(Attribute::SanitizeThread) || F.hasFnAttribute(Attribute::SanitizeHWAddress) ||
        F.getInstructionCount() > 1000) continue;
    // Avoid constructing loop and scalar-evolution analyses for the many
    // functions that do not contain this mix of variable shifts.
    unsigned CandidateLeft=0, CandidateRight=0;
    for (BasicBlock &B : F) for (Instruction &I : B)
      if (auto *Op=dyn_cast<BinaryOperator>(&I); Op && !isa<ConstantInt>(Op->getOperand(1))) {
        CandidateLeft += Op->getOpcode()==Instruction::Shl;
        CandidateRight += Op->getOpcode()==Instruction::LShr || Op->getOpcode()==Instruction::AShr;
      }
    if (CandidateLeft < 2 || CandidateRight < 1) continue;
    DominatorTree DT(F); LoopInfo LI(DT);
    TargetLibraryInfoImpl TLII(M.getTargetTriple()); TargetLibraryInfo TLI(TLII);
    AssumptionCache AC(F); ScalarEvolution SE(F, TLI, AC, DT, LI);
    for (Loop *L : LI.getLoopsInPreorder()) {
      if (L->getLoopID() || !L->getSubLoops().empty() || !L->getLoopLatch() || L->getNumBlocks() > 12) continue;
      auto *Max = dyn_cast<SCEVConstant>(SE.getConstantMaxBackedgeTakenCount(L));
      if (!Max || Max->getAPInt().getActiveBits() > 7 || Max->getAPInt().getZExtValue() < 16 || Max->getAPInt().getZExtValue() > 64) continue;
      unsigned ShiftsLeft=0, ShiftsRight=0, Instructions=0;
      for (BasicBlock *B : L->blocks()) for (Instruction &I : *B) {
        ++Instructions;
        if (auto *Op=dyn_cast<BinaryOperator>(&I); Op && !isa<ConstantInt>(Op->getOperand(1))) {
          ShiftsLeft += Op->getOpcode()==Instruction::Shl;
          ShiftsRight += Op->getOpcode()==Instruction::LShr || Op->getOpcode()==Instruction::AShr;
        }
      }
      if (Instructions > 80 || ShiftsLeft < 2 || ShiftsRight < 1) continue;
      LLVMContext &C=M.getContext(); Metadata *Entries[]={nullptr,MDNode::get(C,MDString::get(C,"llvm.loop.unroll.disable"))};
      MDNode *ID=MDNode::getDistinct(C,Entries); ID->replaceOperandWith(0,ID); L->setLoopID(ID); ++Changed;
    }
  }
  return Changed;
}
}
