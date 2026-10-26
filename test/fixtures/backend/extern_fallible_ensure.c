#include <stdbool.h>
#include <stdint.h>

int32_t ensure_result(int64_t *out, bool bad) {
    *out = bad ? 41 : 42;
    return 0;
}

int32_t ensure_failure(int64_t *out, bool ignored) {
    (void)out;
    (void)ignored;
    return 1;
}
