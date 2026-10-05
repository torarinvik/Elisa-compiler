#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef struct { const uint8_t *p; int64_t n; } SV;
int main(void) {
    const size_t n = 4000;
    uint8_t *bytes = malloc(n * 14);
    uint8_t *word = malloc(6);
    if (!bytes || !word) return 99;
    uint64_t state = 4242;
    for (size_t w = 0; w < n; ++w) {
        for (size_t j = 0; j < 6; ++j) {
            state = state * 6364136223846793005ULL + 1442695040888963407ULL;
            word[j] = (uint8_t)(97 + (state >> 59));
            bytes[w * 14 + j] = word[j];
            bytes[w * 14 + 8 + j] = word[j];
        }
    }
    int64_t hits = 0;
    for (size_t q = 0; q < 50000000; ++q) {
        size_t index = q % n;
        SV left = {bytes + index * 14, 6};
        SV right = {bytes + index * 14 + 8, 6};
        if (left.n == right.n && (left.p == right.p || memcmp(left.p, right.p, (size_t)left.n) == 0)) ++hits;
    }
    return (int)(hits % 251);
}
