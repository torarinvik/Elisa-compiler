#include <stdint.h>
/* Keep the consumer opaque to LLVM, and make each measured iteration observable. */
int64_t memory_benchmark_consume(int64_t value) {
    __asm__ volatile("" : "+r"(value) : : "memory");
    return value;
}
