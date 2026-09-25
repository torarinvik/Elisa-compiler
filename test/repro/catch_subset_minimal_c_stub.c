#include <stdint.h>

typedef struct {
    int32_t code;
    int32_t payload;
} ElisaErrorSet;

ElisaErrorSet foo(int64_t *out_value) {
    *out_value = 0;
    return (ElisaErrorSet){2, 42};
}
