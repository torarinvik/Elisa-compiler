/* A foreign LLVM API must be rejected before receiving instruction handles. */
#include <stdlib.h>
int LLVMGetNUW(void *instruction) {
    (void)instruction;
    abort();
}
