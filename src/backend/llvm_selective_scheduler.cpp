// Select a scheduler per function while retaining the target default otherwise.
#include <llvm/Config/llvm-config.h>
#if LLVM_VERSION_MAJOR == 23 && defined(__linux__) && defined(__aarch64__)
#include <llvm/CodeGen/MachineFunction.h>
#include <llvm/CodeGen/MachineScheduler.h>
#include <llvm/IR/Function.h>
#include <llvm/Target/TargetMachine.h>

namespace {
llvm::ScheduleDAGInstrs *elisaSelectiveSchedule(llvm::MachineSchedContext *C) {
  const llvm::Function &F = C->MF->getFunction();
  if (F.hasFnAttribute("elisa.ordered.ilp")) {
    for (auto *R = llvm::MachineSchedRegistry::getList(); R; R = R->getNext())
      if (R->getName() == "ilpmax")
        return R->getCtor()(C);
  }
  if (auto *S = C->TM->createMachineScheduler(C))
    return S;
  return llvm::createSchedLive(C);
}

llvm::MachineSchedRegistry
    elisaSelectiveScheduler("elisa-ordered-selective",
                            "Use ILP scheduling for marked functions",
                            elisaSelectiveSchedule);
} // namespace
#endif
