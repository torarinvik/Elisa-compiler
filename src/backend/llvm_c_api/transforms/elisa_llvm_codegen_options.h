/* C API for the LLVM command-line options the code generator installs.
 *
 * LLVMParseCommandLineOptions sets an option but cannot tell whether one was already
 * given, and the C API cannot register a machine scheduler. The scheduler that runs
 * functions marked `elisa.ordered.ilp` under ILP scheduling (Linux AArch64, LLVM 23)
 * is registered by this library when it is linked. */
#ifndef ELISA_LLVM_CODEGEN_OPTIONS_H
#define ELISA_LLVM_CODEGEN_OPTIONS_H

#ifdef __cplusplus
extern "C" {
#endif

/* How many times the option NAME was given; -1 when no such option is registered. */
int ElisaLLVMOptionOccurrences(const char *name);

/* 1 when the `elisa-ordered-selective` machine scheduler is registered, else 0. */
int ElisaLLVMSelectiveSchedulerRegistered(void);

#ifdef __cplusplus
}
#endif

#endif
