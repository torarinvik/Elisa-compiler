#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

/*
 * Strong host collector for the profiler ABI smoke test.
 *
 * The callbacks deliberately contain no allocation, locks, stdio, or calls back
 * into Elisa. A production collector can replace this bounded recorder with a
 * per-thread file/ring-buffer implementation, but it must preserve that rule:
 * allocation and region-layout hooks execute on the allocator's hot path.
 */

enum {
    ELISA_PROFILE_ALLOCATION_ALLOC = 1,
    ELISA_PROFILE_ALLOCATION_REALLOC_IN_PLACE = 2,
    ELISA_PROFILE_ALLOCATION_REALLOC_MOVE = 3,
    ELISA_PROFILE_ALLOCATION_RECLAIM = 4,
    ELISA_PROFILE_ALLOCATION_REGION_CREATE = 5,
    ELISA_PROFILE_ALLOCATION_REGION_RESET = 6,
    ELISA_PROFILE_ALLOCATION_REGION_TRIM = 7,
    ELISA_PROFILE_ALLOCATION_REGION_FREE = 8,
    ELISA_PROFILE_ALLOCATION_ARENA_ADOPT = 9,
    ELISA_PROFILE_ALLOCATION_REGION_REWIND = 10,
    ELISA_PROFILE_ALLOCATION_ABI_V1 = 1,
    ELISA_PROFILE_REGION_LAYOUT_ABI_V1 = 1,
    ELISA_PROFILE_MAX_KIND = ELISA_PROFILE_ALLOCATION_REGION_REWIND,
    ELISA_PROFILE_MAX_EVENTS = 4096
};

struct profile_event {
    uint32_t kind;
    uintptr_t address;
    size_t size;
    uintptr_t old_address;
    size_t old_size;
    uintptr_t arena;
    size_t region;
};

static _Atomic uint64_t negotiation_failures;
static _Atomic uint64_t layout_count;
static _Atomic uint64_t event_count;
static _Atomic uint64_t kind_counts[ELISA_PROFILE_MAX_KIND + 1];
static _Atomic uint64_t invalid_events;
static struct profile_event events[ELISA_PROFILE_MAX_EVENTS];

uint32_t elisa_profile_allocation_negotiate(uint32_t requested_version) {
    if (requested_version == ELISA_PROFILE_ALLOCATION_ABI_V1) {
        return ELISA_PROFILE_ALLOCATION_ABI_V1;
    }
    atomic_fetch_add_explicit(&negotiation_failures, 1, memory_order_relaxed);
    return 0;
}

uint32_t elisa_profile_region_layout_negotiate(uint32_t requested_version) {
    if (requested_version == ELISA_PROFILE_REGION_LAYOUT_ABI_V1) {
        return ELISA_PROFILE_REGION_LAYOUT_ABI_V1;
    }
    atomic_fetch_add_explicit(&negotiation_failures, 1, memory_order_relaxed);
    return 0;
}

void elisa_profile_region_layout_v1(
    uintptr_t arena,
    size_t region,
    uintptr_t header,
    uintptr_t data,
    size_t capacity
) {
    (void)arena;
    (void)region;
    if (header == 0 || data == 0 || capacity == 0) {
        atomic_fetch_add_explicit(&invalid_events, 1, memory_order_relaxed);
    }
    atomic_fetch_add_explicit(&layout_count, 1, memory_order_relaxed);
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
    uint64_t slot = atomic_fetch_add_explicit(&event_count, 1, memory_order_relaxed);
    if (kind == 0 || kind > ELISA_PROFILE_MAX_KIND) {
        atomic_fetch_add_explicit(&invalid_events, 1, memory_order_relaxed);
    } else {
        atomic_fetch_add_explicit(&kind_counts[kind], 1, memory_order_relaxed);
    }
    if (slot < ELISA_PROFILE_MAX_EVENTS) {
        events[slot] = (struct profile_event){
            kind, address, size, old_address, old_size, arena, region
        };
    }
}

static int fail(const char *message) {
    fprintf(stderr, "profile collector smoke FAILED: %s\n", message);
    return 1;
}

extern int64_t profile_probe_export(void);

int main(void) {
    int64_t result = profile_probe_export();
    uint64_t layouts = atomic_load_explicit(&layout_count, memory_order_acquire);
    uint64_t events_seen = atomic_load_explicit(&event_count, memory_order_acquire);
    uint64_t allocations = atomic_load_explicit(
        &kind_counts[ELISA_PROFILE_ALLOCATION_ALLOC], memory_order_acquire
    );
    uint64_t creates = atomic_load_explicit(
        &kind_counts[ELISA_PROFILE_ALLOCATION_REGION_CREATE], memory_order_acquire
    );
    uint64_t invalid = atomic_load_explicit(&invalid_events, memory_order_acquire);
    uint64_t failures = atomic_load_explicit(&negotiation_failures, memory_order_acquire);

    if (result != 42) {
        return fail("probe result changed");
    }
    if (failures != 0) {
        return fail("collector negotiated an unsupported ABI");
    }
    if (layouts == 0) {
        return fail("no region-layout event was delivered");
    }
    if (events_seen == 0 || allocations == 0) {
        return fail("no allocation events were delivered");
    }
    if (creates == 0) {
        return fail("no region-create event was delivered");
    }
    if (invalid != 0) {
        return fail("runtime delivered malformed profiler data");
    }
    if (events_seen > ELISA_PROFILE_MAX_EVENTS) {
        return fail("smoke collector ring overflowed");
    }

    printf(
        "profile collector smoke OK: layouts=%llu events=%llu allocations=%llu regions=%llu\n",
        (unsigned long long)layouts,
        (unsigned long long)events_seen,
        (unsigned long long)allocations,
        (unsigned long long)creates
    );
    return 0;
}
