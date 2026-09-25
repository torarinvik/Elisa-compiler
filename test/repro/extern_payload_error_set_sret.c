#include <stdint.h>

typedef struct {
    int32_t code;
    int64_t first;
    int64_t second;
    int64_t third;
} ElisaWideErrorSet;

ElisaWideErrorSet external_probe(int64_t *out_value, int64_t code) {
    *out_value = 0;
    (void)code;
    return (ElisaWideErrorSet){3, 0, 0, 41};
}
