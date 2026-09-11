#!/usr/bin/env bash
# The objects a parity link must add so an OPTIONAL hook is a no-op and not
# address zero.
#
# Elisa's runtime calls hooks a normal program does not provide: the profiler
# ABI (elisa_profile_*) and the native-callback family (elisa_native_callback_*,
# plus va_copy/va_end). A real link resolves them to the weak fallbacks the
# compiler publishes. These parity programs link with
# `-Wl,-undefined,dynamic_lookup`, which Elisa's non-PIC objects need on macOS
# and which turns an unresolved symbol into a NULL ADDRESS rather than a link
# error. The first call to one then jumps to 0x0 and the program dies with
# SIGSEGV -- which is exactly what resolve_smoke.sh and check_self_hostable.sh
# were doing (lldb: `frame #0: 0x0000000000000000`), reported by the gate as two
# failing checks with no hint that they shared a cause.
#
# SOURCED, NOT PASTED. write_profiler_hook_fallbacks.sh's own header records
# what happened the last time this kind of source lived in three places and one
# of them missed an update.
# Sets ELISA_OPTIONAL_HOOK_OBJECTS to the objects to add to a link. An array
# rather than stdout: macOS ships bash 3.2, which has no `mapfile`.
elisa_native_optional_hook_objects() {
  local work="$1" root="$2"
  local profiler_object="$work/elisa_profiler_hook_fallbacks.o"
  local callback_object="$work/elisa_native_callback_fallbacks.o"
  bash "$root/scripts/write_profiler_hook_fallbacks.sh" >"$work/elisa_profiler_hook_fallbacks.c"
  cp "$root/scripts/pymodule_runtime_fallback.c" "$work/elisa_native_callback_fallbacks.c"
  # -fno-builtin: the callback fallback defines va_copy and va_end, which a
  # current clang refuses to let a program redeclare over its own builtins.
  clang -fno-builtin -c -o "$profiler_object" "$work/elisa_profiler_hook_fallbacks.c"
  clang -fno-builtin -c -o "$callback_object" "$work/elisa_native_callback_fallbacks.c"
  ELISA_OPTIONAL_HOOK_OBJECTS=("$profiler_object" "$callback_object")
}
