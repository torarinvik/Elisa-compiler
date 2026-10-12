#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct {
    int64_t *items;
    size_t count;
    size_t capacity;
} DArray;

static int darray_push(DArray *xs, int64_t value) {
    if (xs->count == xs->capacity) {
        size_t new_capacity = xs->capacity == 0 ? 8 : xs->capacity * 2;
        int64_t *grown = realloc(xs->items, new_capacity * sizeof(*grown));
        if (grown == NULL) return 0;
        xs->items = grown;
        xs->capacity = new_capacity;
    }
    xs->items[xs->count] = value;
    xs->count += 1;
    return 1;
}

int main(void) {
    const size_t n = 4000000;
    DArray xs = {0};
    uint64_t s = 12345;
    size_t i = 0;
    while (i < n) {
        s = s * 6364136223846793005ULL + 1442695040888963407ULL;
        if (!darray_push(&xs, (int64_t)(s >> 33))) {
            free(xs.items);
            return 1;
        }
        i += 1;
    }

    int64_t total = 0;
    for (size_t index = 0; index < xs.count; ++index) total += xs.items[index] ^ 73;
    for (const int64_t *value = xs.items; value < xs.items + xs.count; ++value) total -= *value >> 3;
    printf("%lld\n", (long long)total);
    return (int)(total % 251);
}
