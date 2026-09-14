#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

static uintptr_t last_header;
static size_t last_capacity;
static unsigned creates, layouts;
uint32_t elisa_profile_allocation_negotiate(uint32_t version) { return version == 1; }
uint32_t elisa_profile_region_layout_negotiate(uint32_t version) { return version == 1; }
void elisa_profile_allocation_event_v1(uint32_t kind, uintptr_t address,
    size_t size, uintptr_t old_address, size_t old_size, uintptr_t arena, size_t region) {
    (void)old_address; (void)old_size; (void)arena; (void)region;
    if (kind == 5) {
        last_header = address;
        last_capacity = size;
        ++creates;
    }
}
void elisa_profile_region_layout_v1(uintptr_t arena, size_t region,
    uintptr_t header, uintptr_t data, size_t capacity) {
    (void)arena; (void)region; (void)data;
    assert(header == last_header);
    assert(capacity == last_capacity);
    ++layouts;
}
__attribute__((destructor)) static void verify_events(void) {
    assert(creates == 2);
    assert(layouts >= 2);
}
