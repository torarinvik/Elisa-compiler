#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>

enum {
    PROFILE_ALLOCATION_REGION_FREE = 8,
    PROFILE_ALLOCATION_ABI_V1 = 1,
    PROFILE_REGION_LAYOUT_ABI_V1 = 1
};

static _Atomic uintptr_t watched_arena;
static _Atomic uint64_t watched_region_free_count;

void profile_watch_region_free(uintptr_t arena) {
    atomic_store_explicit(&watched_region_free_count, 0, memory_order_relaxed);
    atomic_store_explicit(&watched_arena, arena, memory_order_relaxed);
}

uint64_t profile_region_free_count(void) {
    return atomic_load_explicit(&watched_region_free_count, memory_order_relaxed);
}

uint32_t elisa_profile_allocation_negotiate(uint32_t version) {
    return version == PROFILE_ALLOCATION_ABI_V1 ? PROFILE_ALLOCATION_ABI_V1 : 0;
}

uint32_t elisa_profile_region_layout_negotiate(uint32_t version) {
    return version == PROFILE_REGION_LAYOUT_ABI_V1 ? PROFILE_REGION_LAYOUT_ABI_V1 : 0;
}

void elisa_profile_region_layout_v1(
    uintptr_t arena,
    size_t region,
    uintptr_t header,
    uintptr_t data_base,
    size_t capacity_bytes
) {
    (void)arena;
    (void)region;
    (void)header;
    (void)data_base;
    (void)capacity_bytes;
}

void elisa_profile_allocation_event_v1(
    uint32_t kind,
    uintptr_t address,
    size_t size,
    uintptr_t old_address,
    size_t old_size,
    uintptr_t arena,
    size_t region
) {
    (void)address;
    (void)size;
    (void)old_address;
    (void)old_size;
    (void)region;
    if (kind == PROFILE_ALLOCATION_REGION_FREE
        && arena == atomic_load_explicit(&watched_arena, memory_order_relaxed)) {
        atomic_fetch_add_explicit(&watched_region_free_count, 1, memory_order_relaxed);
    }
}

extern int64_t profile_arena_free_probe_export(void);

int main(void) {
    int64_t result = profile_arena_free_probe_export();
    uint64_t frees = profile_region_free_count();
    if (result != 42 || frees != 1) {
        fprintf(stderr, "arena-free profiler smoke FAILED: result=%lld matching_events=%llu\n",
                (long long)result, (unsigned long long)frees);
        return 1;
    }
    printf("arena-free profiler smoke OK: matching_events=%llu\n",
           (unsigned long long)frees);
    return 0;
}
