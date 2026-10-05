#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MAP_ANONYMOUS
#define MAP_ANONYMOUS MAP_ANON
#endif

typedef struct {
    const uint8_t *data;
    int64_t length;
} SView;

extern bool sview_equality_guard_probe(SView left, SView right);

static bool equal(const uint8_t *left, int64_t left_length,
                  const uint8_t *right, int64_t right_length) {
    return sview_equality_guard_probe((SView){left, left_length},
                                      (SView){right, right_length});
}

static uint8_t *guarded_page(size_t page_size) {
    uint8_t *mapping = mmap(NULL, page_size * 2, PROT_READ | PROT_WRITE,
                            MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (mapping == MAP_FAILED) return NULL;
    if (mprotect(mapping + page_size, page_size, PROT_NONE) != 0) {
        munmap(mapping, page_size * 2);
        return NULL;
    }
    return mapping + page_size;
}

int main(void) {
    long page_size_long = sysconf(_SC_PAGESIZE);
    if (page_size_long <= 0) return 90;
    size_t page_size = (size_t)page_size_long;
    uint8_t *left_end = guarded_page(page_size);
    uint8_t *right_end = guarded_page(page_size);
    if (!left_end || !right_end) return 91;

    uint8_t *left = left_end - 4;
    uint8_t *right = right_end - 4;
    memcpy(left, "abc\xff", 4);
    memcpy(right, "abc\xff", 4);

    if (!equal(left, 4, right, 4)) return 1; /* late hit */
    right[2] = 'x';
    if (equal(left, 4, right, 4)) return 2; /* late-byte miss */
    right[2] = 'c';
    right[0] = 'z';
    if (equal(left, 4, right, 4)) return 3; /* first-byte miss */
    right[0] = 'a';

    /* A one-byte view ends exactly at the inaccessible page. The first-byte fast path
       must load the sole valid byte, and must not read a second byte. */
    if (!equal(left_end - 1, 1, right_end - 1, 1)) return 4;
    right_end[-1] = 0x7f;
    if (equal(left_end - 1, 1, right_end - 1, 1)) return 5;
    if (!equal(left_end - 1, 1, left_end - 1, 1)) return 6;

    munmap(left_end - page_size, page_size * 2);
    munmap(right_end - page_size, page_size * 2);
    return 0;
}
