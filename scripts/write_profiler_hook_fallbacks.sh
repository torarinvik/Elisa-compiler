#!/usr/bin/env bash
# Print the C source of the WEAK profiler-hook fallbacks to stdout.
#
# The std's arena calls elisa_profile_* on every allocation so a profiler can be linked in
# without recompiling; when none is, these weak definitions satisfy the references and cost
# a predictable branch. Every link of a stage0-compiled program needs them: the seed product,
# the runtime object, and the test emitters.
#
# ONE copy, on purpose. This source was pasted into elisac_stage1_seed.sh and
# build_runtime_object.sh, and build_emit_native.sh never got its copy -- so the day the std
# started calling elisa_profile_allocation_event_v1, the seed and the runtime linked and
# emit_native did not ("Undefined symbols: _elisa_profile_allocation_event_v1"), taking
# backend_native_smoke down with it. A consumer that links a stage0 object sources this
# script; there is nothing to keep in sync.
set -euo pipefail

cat <<'EOF'
#include <stddef.h>
#include <stdint.h>
#if defined(__GNUC__) || defined(__clang__)
#define ELISA_WEAK __attribute__((weak))
#else
#define ELISA_WEAK
#endif
ELISA_WEAK uint32_t elisa_profile_allocation_negotiate(uint32_t version) { (void)version; return 0; }
ELISA_WEAK uint32_t elisa_profile_region_layout_negotiate(uint32_t version) { (void)version; return 0; }
ELISA_WEAK void elisa_profile_region_layout_v1(uintptr_t arena, size_t region, uintptr_t header, uintptr_t data, size_t capacity) { (void)arena; (void)region; (void)header; (void)data; (void)capacity; }
ELISA_WEAK void elisa_profile_allocation_event_v1(uint32_t kind, uintptr_t address, size_t size, uintptr_t old_address, size_t old_size, uintptr_t arena, size_t region) {
  (void)kind; (void)address; (void)size; (void)old_address; (void)old_size; (void)arena; (void)region;
}
EOF
