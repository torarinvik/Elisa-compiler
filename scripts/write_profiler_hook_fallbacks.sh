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
#
# `--host-callbacks` also prints WEAK fallbacks for the native-callback family and
# va_copy/va_end. build_runtime_object.sh folds them into elisacore_runtime.o, so a plain
# `clang prog.o elisacore_runtime.o` links without the driver's own shim file or
# -dead_strip; the driver's weak copies and a strong host callback still win or coexist.
# Compile that output with -fno-builtin (clang refuses to redefine va_copy/va_end otherwise).
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
if [[ "${1:-}" == "--host-callbacks" ]]; then
cat <<'EOF'
ELISA_WEAK void *elisa_native_callback_ptr(uint8_t *name) { (void)name; return NULL; }
ELISA_WEAK uint32_t elisa_native_callback_call_u32_voidp(uint8_t *name, void *arg, uint32_t fallback) { (void)name; (void)arg; return fallback; }
ELISA_WEAK int32_t elisa_native_callback_call_i32_voidp(uint8_t *name, void *arg, int32_t fallback) { (void)name; (void)arg; return fallback; }
ELISA_WEAK uintptr_t elisa_native_callback_call_usize_voidp(uint8_t *name, void *arg, uintptr_t fallback) { (void)name; (void)arg; return fallback; }
ELISA_WEAK intptr_t elisa_native_callback_call_isize_voidp(uint8_t *name, void *arg, intptr_t fallback) { (void)name; (void)arg; return fallback; }
ELISA_WEAK uint32_t elisa_native_callback_spawn_join_u32_voidp(uint8_t *name, void *arg, uint32_t fallback) { (void)name; (void)arg; return fallback; }
ELISA_WEAK void *elisa_native_callback_context_new_u32_voidp(uint8_t *name, void *arg, uint32_t fallback) { (void)name; (void)arg; (void)fallback; return NULL; }
ELISA_WEAK void *elisa_native_callback_context_entry_u32_voidp(void) { return NULL; }
ELISA_WEAK int32_t elisa_native_callback_context_start_u32_voidp(void *ctx, uintptr_t *thread) { (void)ctx; (void)thread; return -1; }
ELISA_WEAK uint32_t elisa_native_callback_context_join_u32_voidp(uintptr_t handle, void *ctx, uint32_t fallback) { (void)handle; (void)ctx; return fallback; }
ELISA_WEAK uint32_t elisa_native_callback_context_spawn_join_u32_voidp(void *ctx, uint32_t fallback) { (void)ctx; return fallback; }
ELISA_WEAK uint32_t elisa_native_callback_context_result_u32(void *ctx, uint32_t fallback) { (void)ctx; return fallback; }
ELISA_WEAK void elisa_native_callback_context_free(void *ctx) { (void)ctx; }
ELISA_WEAK void *va_copy(void *source) { return source; }
ELISA_WEAK void va_end(void *argument) { (void)argument; }
EOF
fi
