// Implementation of elisa_llvm_codegen_options.h, and the selective machine scheduler.
#include "elisa_llvm_codegen_options.h"

#include <llvm/Config/llvm-config.h>
#include <llvm/Support/CommandLine.h>
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

extern "C" int ElisaLLVMOptionOccurrences(const char *name) {
  auto &registered = llvm::cl::getRegisteredOptions();
  auto option = registered.find(name);
  return option == registered.end() ? -1 : static_cast<int>(option->second->getNumOccurrences());
}

extern "C" int ElisaLLVMSelectiveSchedulerRegistered(void) {
#if LLVM_VERSION_MAJOR == 23 && defined(__linux__) && defined(__aarch64__)
  return 1;
#else
  return 0;
#endif
}
