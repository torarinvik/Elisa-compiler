# Joinable thread readiness

`poll_ready[R](thread: Thread[R, Joinable]) -> ThreadReadiness[R]` is an
ownership-preserving, nonblocking completion query. It is available only for the
generic joinable thread carrier; pool `Task` values continue to use `pool_await`
or their task-group wait. The result carries the same affine handle and a
completion flag, so the caller can move the handle to another poll or to `join`.

The worker state has two references at creation: one owned by the joinable
handle, and one owned by the worker. The handle reference keeps the state alive
through the consuming poll. The worker writes the result storage, release-stores
`1` to `completed`, and then releases its reference. `poll_ready` acquire-loads
`completed`; a true result therefore follows publication of the result bytes.
The poll does not read or consume those bytes. `join` remains the only typed
result consumer and releases the handle reference after joining.

`detach` consumes and releases the handle reference; the worker reference keeps
the state alive until after its release-store. Detached work has no remaining
handle to poll. Pool tasks use the same result-state worker entry, but
`pool_await` synchronizes through the pool's done condition and
`task_group_wait_all` waits for every queued task before releasing group state.
Neither pool task carrier exposes a nonblocking poll through this API.

The completion flag is set on normal callback return. Thread creation and join
failures retain the existing `Abort.Panic` behavior and do not return a handle
that can be polled. Callback panic handling is outside this readiness protocol.

The lifecycle laws are:

1. `completed` starts at `0` before the worker is started.
2. The worker sets it to `1` only after `ctx_concurrency_result_write` returns.
3. `poll_ready` returns false for a zero thread handle or missing state, and true
   only when the acquired value is `1`.
4. The affine `ThreadReadiness[R]` carries the one owner of the handle. Moving
   that handle out for another poll or `join` consumes the prior wrapper.
5. `complete == true` guarantees completion and result publication, but does not
   grant a second result read or make a moved/consumed handle valid.

These are source-level lifecycle and publication contracts. They are not an SMT
proof of the compiler's concurrent memory model. The `AtomicSlot[i64]` load and
store lower through the compiler's atomic backend with Acquire and Release
ordering on threaded native targets. The current WebAssembly runtime is
single-threaded and its atomic helpers are no-ops, so this interface does not
provide cross-worker synchronization there.
