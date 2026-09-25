#include <stdint.h>

/* Characterization only: this C ABI stub does not match the raw LLVM aggregate-return ABI
 * currently emitted for Elisa error-set externs on this target. See IMPLEMENTATION_PLAN.md. */
typedef struct {
    int32_t code;
    int32_t payload;
} ElisaErrorSet;

ElisaErrorSet external_probe(int64_t *out_value, int64_t code) {
    *out_value = 0;
    (void)code;
    return (ElisaErrorSet){2, 41};
}
