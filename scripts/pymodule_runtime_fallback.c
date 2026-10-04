#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

/* Extension modules do not have an Elisa executable host to provide these optional
 * callbacks.  Preserve the runtime's documented fallback/no-op behavior instead. */
void *elisa_native_callback_ptr(uint8_t *name) {
    (void)name;
    return NULL;
}
uint32_t elisa_native_callback_call_u32_voidp(uint8_t *name, void *arg, uint32_t fallback) {
    (void)name; (void)arg; return fallback;
}
int32_t elisa_native_callback_call_i32_voidp(uint8_t *name, void *arg, int32_t fallback) {
    (void)name; (void)arg; return fallback;
}
uintptr_t elisa_native_callback_call_usize_voidp(uint8_t *name, void *arg, uintptr_t fallback) {
    (void)name; (void)arg; return fallback;
}
intptr_t elisa_native_callback_call_isize_voidp(uint8_t *name, void *arg, intptr_t fallback) {
    (void)name; (void)arg; return fallback;
}
uint32_t elisa_native_callback_spawn_join_u32_voidp(uint8_t *name, void *arg, uint32_t fallback) {
    (void)name; (void)arg; return fallback;
}
void *elisa_native_callback_context_new_u32_voidp(uint8_t *name, void *arg, uint32_t fallback) {
    (void)name; (void)arg; (void)fallback; return NULL;
}
void *elisa_native_callback_context_entry_u32_voidp(void) {
    return NULL;
}
int32_t elisa_native_callback_context_start_u32_voidp(void *ctx, uintptr_t *thread) {
    (void)ctx; (void)thread; return -1;
}
uint32_t elisa_native_callback_context_join_u32_voidp(uintptr_t handle, void *ctx, uint32_t fallback) {
    (void)handle; (void)ctx; return fallback;
}
uint32_t elisa_native_callback_context_spawn_join_u32_voidp(void *ctx, uint32_t fallback) {
    (void)ctx; return fallback;
}
uint32_t elisa_native_callback_context_result_u32(void *ctx, uint32_t fallback) {
    (void)ctx; return fallback;
}
void elisa_native_callback_context_free(void *ctx) {
    (void)ctx;
}
#define ELISA_WEAK
#if (defined(__x86_64__) && !defined(_WIN32)) || (defined(__aarch64__) && !defined(__APPLE__) && !defined(_WIN32))
#define ELISA_VA_LIST_BY_REF 1
#endif
ELISA_WEAK void *va_copy(void *source) {
#ifdef ELISA_VA_LIST_BY_REF
  __builtin_va_list *copy = (__builtin_va_list *)malloc(sizeof(__builtin_va_list));
  if (copy == NULL) abort();
  __builtin_va_copy(*copy, *(__builtin_va_list *)source);
  return (void *)copy;
#else
  return source;
#endif
}
ELISA_WEAK void va_end(void *argument) {
#ifdef ELISA_VA_LIST_BY_REF
  if (argument != NULL) { __builtin_va_end(*(__builtin_va_list *)argument); free(argument); }
#else
  (void)argument;
#endif
}
