// Implementation of elisa_llvm_pass_pipelines.h over PassBuilder.
#include "elisa_llvm_pass_pipelines.h"

#include <llvm/IR/Function.h>
#include <llvm/IR/Module.h>
#include <llvm/Passes/PassBuilder.h>
#include <llvm/Target/TargetMachine.h>

using namespace llvm;

extern "C" void ElisaLLVMRunDefaultO3Pipeline(LLVMModuleRef module, LLVMTargetMachineRef target) {
  PassBuilder builder(reinterpret_cast<TargetMachine *>(target));
  LoopAnalysisManager loops;
  FunctionAnalysisManager functions;
  CGSCCAnalysisManager components;
  ModuleAnalysisManager modules;
  builder.registerModuleAnalyses(modules);
  builder.registerCGSCCAnalyses(components);
  builder.registerFunctionAnalyses(functions);
  builder.registerLoopAnalyses(loops);
  builder.crossRegisterProxies(loops, functions, components, modules);
  ModulePassManager pipeline = builder.buildPerModuleDefaultPipeline(OptimizationLevel::O3);
  pipeline.run(*unwrap(module), modules);
}

extern "C" void ElisaLLVMRunO1FunctionSimplificationPipeline(LLVMValueRef function) {
  PassBuilder builder;
  LoopAnalysisManager loops;
  FunctionAnalysisManager functions;
  CGSCCAnalysisManager components;
  ModuleAnalysisManager modules;
  builder.registerModuleAnalyses(modules);
  builder.registerCGSCCAnalyses(components);
  builder.registerFunctionAnalyses(functions);
  builder.registerLoopAnalyses(loops);
  builder.crossRegisterProxies(loops, functions, components, modules);
  FunctionPassManager pipeline =
      builder.buildFunctionSimplificationPipeline(OptimizationLevel::O1, ThinOrFullLTOPhase::None);
  pipeline.run(*unwrap<Function>(function), functions);
}
