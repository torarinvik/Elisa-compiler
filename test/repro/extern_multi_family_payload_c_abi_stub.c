#include <stdint.h>

/* C representation used by the extern declaration: C returns this aggregate in the target's
 * native C ABI registers while Elisa's internal error dispatcher uses its own aggregate form. */
typedef struct {
    int32_t code;
    int32_t payload;
} ElisaErrorSet;

ElisaErrorSet external_probe(int64_t *out_value, int64_t code) {
    *out_value = 0;
    (void)code;
    return (ElisaErrorSet){2, 41};
}
