/* Windows stand-ins for the thread entries elisacore_runtime_concurrency.elisa
 * declares as EXTERNS on this target.
 *
 * Every other platform defines ctx_thread_* in Elisa over pthreads. The Windows
 * arm deliberately does not: it declares them and expects the host link to
 * supply them, the same arrangement as the profiler hooks and the native-callback
 * family. Without this file a Windows image cannot link at all, which is what
 * kept elisa-ui's win32 gate at objects only.
 *
 * Link it alongside the object published by write_profiler_hook_fallbacks.sh and
 * pymodule_runtime_fallback.c.
 */
#include <windows.h>
#include <stdint.h>
#include <stdlib.h>

/* The entry the Elisa side hands us is pthread-shaped (void *(*)(void *)); a
 * Win32 thread wants DWORD WINAPI (*)(LPVOID). The shapes agree on x86_64 but
 * the RETURN types do not, so go through a trampoline rather than casting a
 * function pointer and hoping. The start record is owned by the new thread. */
typedef void *(*elisa_thread_entry)(void *);

struct elisa_thread_start {
    elisa_thread_entry entry;
    void *arg;
};

static DWORD WINAPI elisa_thread_trampoline(LPVOID raw)
{
    struct elisa_thread_start *start = (struct elisa_thread_start *)raw;
    elisa_thread_entry entry = start->entry;
    void *arg = start->arg;
    free(start);
    if (entry != NULL) {
        (void)entry(arg);
    }
    return 0;
}

int ctx_thread_create(uintptr_t *thread, void *entry, void *arg)
{
    if (thread == NULL) {
        return -1;
    }
    struct elisa_thread_start *start =
        (struct elisa_thread_start *)malloc(sizeof *start);
    if (start == NULL) {
        return -1;
    }
    start->entry = (elisa_thread_entry)entry;
    start->arg = arg;
    HANDLE handle = CreateThread(NULL, 0, elisa_thread_trampoline, start, 0, NULL);
    if (handle == NULL) {
        free(start);
        return -1;
    }
    *thread = (uintptr_t)handle;
    return 0;
}

int ctx_thread_join(uintptr_t thread)
{
    HANDLE handle = (HANDLE)thread;
    if (handle == NULL) {
        return -1;
    }
    if (WaitForSingleObject(handle, INFINITE) != WAIT_OBJECT_0) {
        return -1;
    }
    /* Joining consumes the handle, as pthread_join consumes the thread. */
    return CloseHandle(handle) ? 0 : -1;
}

int ctx_thread_detach(uintptr_t thread)
{
    HANDLE handle = (HANDLE)thread;
    if (handle == NULL) {
        return -1;
    }
    /* The thread keeps running; we simply stop holding a handle to it. */
    return CloseHandle(handle) ? 0 : -1;
}

void thread_yield(void)
{
    (void)SwitchToThread();
}

void thread_sleep_usec(uint64_t usec)
{
    /* Sleep's resolution is milliseconds: round UP so a caller asking for a
     * non-zero wait never spins on a zero-length sleep. */
    DWORD millis = (DWORD)((usec + 999u) / 1000u);
    Sleep(millis);
}
