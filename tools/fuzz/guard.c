// LD_PRELOAD guard for fuzzed stage1 products: freed arena memory becomes a trap.
//
// The Linux arena backend releases regions with munmap. A dangling view into a released
// region normally reads whatever the next mmap put there (often a fresh, zeroed region at
// the same address), so a use-after-free can still exit 0. Here munmap never unmaps: it
// mprotects the range PROT_NONE and keeps the addresses reserved, so a later read or write
// through a stale pointer faults (SIGSEGV) instead of reading recycled bytes, and no later
// mmap can be handed the same addresses.
//
// Limits (by design, keep fixtures honest instead): the runtime parks up to a few freed
// regions in a reuse cache and recycles darray backings inside a live arena, neither of
// which goes through munmap. That is why fuzz fixtures add a pad allocation after owners:
// the arena tail grows IN PLACE and hides stale reads unless something else is allocated.
//
//   cc -O2 -shared -fPIC -o guard.so guard.c -ldl
//   LD_PRELOAD=$PWD/guard.so ./prog
#define _GNU_SOURCE
#include <sys/mman.h>
#include <unistd.h>

int munmap(void *addr, size_t len) {
    // Keep the reservation; make it inaccessible. Lengths are page-rounded by the kernel.
    return mprotect(addr, len, PROT_NONE);
}
