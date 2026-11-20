# Structured concurrency

Use `nursery` for a batch of tasks that should finish before the surrounding code
continues. The nursery owns its worker pool, collects every unqualified `submit`,
waits for the tasks when its block ends, and then shuts the pool down.

```elisa
def visit(index: usize) -> usize:
    return index

def visit_all(count: usize) -> void:
    can Parallel:
        nursery workers(4):
            for i in 0..<count:
                submit visit(i)
```

Start with `nursery:` to use the runtime's default worker count. Use
`nursery workers(count):` when the workload calls for a fixed worker count. A
`submit` inside a nursery returns no task handle; its worker is joined before the
block exits. Unqualified submissions automatically use the nursery's pool.
An explicit `submit[pool] work(arg)` remains a separate task handle, even when it names the
nursery's pool; it is not joined by the nursery. Await that handle or add it to a `TaskGroup`.

When a computation needs a value back, use a data-parallel helper such as
`each`, `par_map`, or `reduce`. These helpers partition the input, run a nursery,
and return only after its workers have joined. A reduction operation must be
associative and its identity must be a unit for that operation.

```elisa
def add(left: usize, right: usize) -> usize:
    return left + right

def total(values: Slice[usize]) -> usize:
    return reduce(values, 0.usize(), add)
```

Use `nursery on(pool):` when a caller-owned pool should serve multiple batches.
Each block joins its unqualified `submit` calls while leaving the pool alive for the
caller. An explicit `submit[pool] work(arg)` still returns a task handle that must
be awaited or added to a `TaskGroup`:

```elisa
def submit_batch(pool: mutable ThreadPool&, count: usize) -> void:
    can Parallel:
        nursery on(pool):
            for i in 0..<count:
                submit visit(i)
```

Use `TaskGroup` directly when you need to choose the group creation or wait point
yourself. Add only the submissions that should be joined at that point:

```elisa
def run_group() -> void:
    can Parallel:
        pool: mutable ThreadPool = pool_new(4)
        group: mutable TaskGroup = task_group_new()
        first: Task[usize, Pending] = submit[pool] visit(1.usize())
        second: Task[usize, Pending] = submit[pool] visit(2.usize())
        task_group_add(group, move first)
        task_group_add(group, move second)
        wait all group
        pool_shutdown(&pool)
```

Adding a task consumes its handle, and `wait all` discards its result. Keep
individual handles and await them when their results are needed; use `par_map` or
`reduce` for common bulk-result patterns. The pool's owner remains responsible for
shutting it down after all work has joined.

Pass values that are safe to transfer to a worker. The compiler checks thread
shareability and whether borrowed storage stays valid until the nursery or task
group joins. Moving owned job data into a worker is the usual choice when that
data must not be accessed concurrently by the caller.
