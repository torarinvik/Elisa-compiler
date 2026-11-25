//go:build cgo
#include <llvm/Config/llvm-config.h>
#include <llvm-c/Core.h>
#include <llvm-c/TargetMachine.h>
#if LLVM_VERSION_MAJOR == 23
#include <llvm/ADT/APInt.h>
#include <llvm/ADT/DenseMap.h>
#include <llvm/IR/Dominators.h>
#include <llvm/IR/Instructions.h>
#include <llvm/IR/InstIterator.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/IR/Intrinsics.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/Transforms/Utils/Mem2Reg.h>
#include <llvm/IR/Module.h>
#include <llvm/Passes/PassBuilder.h>
#include <llvm/Analysis/AssumptionCache.h>
#include <llvm/Analysis/CaptureTracking.h>
#include <llvm/Analysis/ValueTracking.h>
#include <llvm/Analysis/CFG.h>
#include <llvm/IR/ConstantRange.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/IntrinsicInst.h>
#include <llvm/Analysis/LoopInfo.h>
#include <llvm/Analysis/InlineCost.h>
#include <llvm/Analysis/OptimizationRemarkEmitter.h>
#include <llvm/Analysis/TargetTransformInfo.h>
#include <llvm/Analysis/ScalarEvolution.h>
#include <llvm/Support/CBindingWrapping.h>
#include <llvm/MC/MCSubtargetInfo.h>
#include <llvm/MC/TargetRegistry.h>
#include <llvm/Target/TargetMachine.h>
#include <llvm/ADT/SmallVector.h>
#include <llvm/Transforms/Utils/Cloning.h>
#include <llvm/Transforms/Utils/LoopPeel.h>
#include <llvm/Transforms/Utils/LoopSimplify.h>
#include <llvm/Transforms/Utils/LoopUtils.h>
#include <llvm/Transforms/Utils/UnrollLoop.h>
#include <llvm/Transforms/Utils/Local.h>
#include "llvm_array_value_ranges.h"
#include "llvm_dead_trap_exits.h"
#include "llvm_path_ranges.h"
#include "llvm_index_bounds.h"
#include "llvm_view_bounded_fills.h"
#include "llvm_indexed_prefix.h"
#include "llvm_validated_reads.h"

using namespace llvm;

#endif

// Keep Apple ARM layout policy identical to Stage0's O3 emitter.
#include <llvm-c/Support.h>
#include <llvm-c/Transforms/PassBuilder.h>
#include <llvm-c/Error.h>
#include "llvm_selective_scheduler.cpp"
// Install before the first optimization, independent of optimization-level
// ordering. Linux retains its faster Stage1 bounded-loop policy from LLVM.
extern "C" void elisacoreConfigureBoundedUnroll() {
#if defined(__APPLE__) && defined(__aarch64__)
  static bool installed = false;
  if (installed) return;
  installed = true;
  const char *args[] = {"elisac", "-unroll-max-upperbound=4"};
  LLVMParseCommandLineOptions(2, args, nullptr);
#endif
}
extern "C" void elisacoreConfigureAppleCodeLayout() {
#if defined(__APPLE__) && defined(__aarch64__)
  // Let PHI elimination move exit-only copies onto loop exit edges.
  static bool installed = false;
  if (installed) return;
  installed = true;
  const char *args[] = {"elisac", "-enable-ext-tsp-block-placement=true",
                        "-aarch64-enable-early-ifcvt=false",
                        "-no-phi-elim-live-out-early-exit"};
  LLVMParseCommandLineOptions(4, args, nullptr);
#elif defined(__aarch64__)
  static bool installed = false;
  if (installed) return;
  installed = true;
#if LLVM_VERSION_MAJOR == 23 && defined(__linux__)
  // Respect an explicitly selected scheduler; otherwise use a selector that
  // delegates unmarked functions to the target's unchanged default.
  auto &registered = llvm::cl::getRegisteredOptions();
  auto scheduler = registered.find("misched");
  if (scheduler != registered.end() && scheduler->second->getNumOccurrences() == 0) {
    const char *args[] = {"elisac", "-aarch64-enable-early-ifcvt=false",
                          "-misched=elisa-ordered-selective",
                          "-no-phi-elim-live-out-early-exit"};
    LLVMParseCommandLineOptions(4, args, nullptr);
    return;
  }
#endif
  const char *args[] = {"elisac", "-aarch64-enable-early-ifcvt=false",
                        "-no-phi-elim-live-out-early-exit"};
  LLVMParseCommandLineOptions(3, args, nullptr);
#endif
}
#include <algorithm>
#include <llvm/Config/llvm-config.h>
#include <llvm/IR/Instructions.h>
#include <llvm/IR/InstIterator.h>
#include <llvm/Analysis/TargetLibraryInfo.h>
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
#include <llvm/Transforms/Utils/LoopPeel.h>
#include <llvm/Transforms/Utils/ValueMapper.h>
#include <llvm/Transforms/Utils/BasicBlockUtils.h>
#include <llvm/Transforms/Utils/UnrollLoop.h>
#include <llvm/Support/CBindingWrapping.h>
#include <llvm/Analysis/LoopIterator.h>
#include <optional>
#include <llvm/ADT/APInt.h>
#include <llvm/ADT/SmallPtrSet.h>
using namespace llvm;

// The late scalar cleanup sequence lives in Elisa
// (llvm_passes/late_cleanup/late_scalar_cleanup.elisa); these are its entries.
#include "llvm_late_cleanup_entries.h"
