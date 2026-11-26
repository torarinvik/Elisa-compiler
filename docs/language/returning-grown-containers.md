# Returning a grown container

The in-place darray methods `push`, `extend`, `reserve`, `resize`, `clear` and `truncate`
change their receiver and yield it as a reference, `mutable darray[E]&`. They don't yield a
new value.

That reference can't be returned from a function declared `-> darray[E]`, because doing so
would copy the value out of a reference:

```elisa
def finish(queue: mutable darray[u8]) -> darray[u8]:
    return queue.push(0)      # error: return type expects darray[u8], got mutable darray[u8]&
```

Thread the change through the binding instead, then return the binding:

```elisa
def finish(queue: mutable darray[u8]) -> darray[u8]:
    queue <- queue.push(0)
    return queue
```

Both compilers reject the first form at check time. Regression fixture:
`test/parity/grown_return_smoke.sh`.
