// Test a remainder against zero as a subtraction: `X ==/!= Q * D` becomes
// `X - Q * D ==/!= 0`. The optimizer turns `X % D == 0` next to `X / D`
// into the first form (the remainder rebuilt from the quotient), which
// AArch64 selects as `mul`, `cmp` and a conditional branch; the second
// selects as `msub` and `cbz`/`cbnz`, one instruction fewer, and is never
// longer when the result feeds something else. Only a product with no
// other use is folded into the `msub`. It runs after the optimization
// pipeline, whose instruction combiner would turn the subtraction back.
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/Instructions.h>
#include <llvm/IR/Module.h>
#include <llvm/IR/PatternMatch.h>

namespace ElisaRemainderTests {
using namespace llvm;
using namespace llvm::PatternMatch;

static unsigned subtractRemainderTests(Module &Module) {
  unsigned Changed = 0;
  for (Function &Function : Module)
    for (BasicBlock &Block : Function)
      for (Instruction &Instruction : Block) {
        auto *Compare = dyn_cast<ICmpInst>(&Instruction);
        if (!Compare || !Compare->isEquality() || !Compare->getType()->isIntegerTy(1)) continue;
        for (unsigned Side = 0; Side < 2; ++Side) {
          Value *Product = Compare->getOperand(Side), *Whole = Compare->getOperand(1 - Side);
          if (!match(Product, m_Mul(m_Value(), m_Value())) || !Product->hasOneUse() ||
              !Product->getType()->isIntegerTy() || isa<Constant>(Whole))
            continue;
          IRBuilder<> Builder(Compare);
          Value *Remainder = Builder.CreateSub(Whole, Product, "remainder");
          Compare->setOperand(0, Remainder);
          Compare->setOperand(1, Constant::getNullValue(Remainder->getType()));
          ++Changed;
          break;
        }
      }
  return Changed;
}
} // namespace ElisaRemainderTests
