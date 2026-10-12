#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct {
    int64_t *items;
    size_t count;
    size_t capacity;
} DArray;

static int darray_reserve(DArray *xs, size_t capacity) {
    xs->items = malloc(capacity * sizeof(*xs->items));
    if (xs->items == NULL) return 0;
    xs->count = 0;
    xs->capacity = capacity;
    return 1;
}

static inline int darray_push(DArray *xs, int64_t value) {
    if (xs->count >= xs->capacity) return 0;
    xs->items[xs->count] = value;
    xs->count += 1;
    return 1;
}

int main(void) {
    const size_t n = 4000000;
    uint64_t s = 12345;
    DArray xs = {0};
    if (!darray_reserve(&xs, n)) return 1;

    for (size_t i = 0; i < n; ++i) {
        s = s * 6364136223846793005ULL + 1442695040888963407ULL;
        if (!darray_push(&xs, (int64_t)(s >> 33))) {
            free(xs.items);
            return 1;
        }
    }

    int64_t total = 0;
    for (int64_t r = 0; r < 200; ++r) {
        for (size_t i = 0; i < xs.count; ++i) total += xs.items[i] ^ r;
        for (const int64_t *value = xs.items; value < xs.items + xs.count; ++value) total -= *value >> 3;
    }

    printf("%lld\n", (long long)total);
    return (int)(total % 251);
}
