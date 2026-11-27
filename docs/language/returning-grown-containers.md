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

The same applies when the reference is copied into a by-value initializer. That includes a call
on another call's result and a value block that ends in the in-place call:

```elisa
receipt: darray[u8] = encode(prefix).push(10)   # error: variable "receipt" expects darray[u8], got mutable darray[u8]&
target: darray[u8] =
    buffer: mutable darray[u8] = []
    buffer.resize(n)                             # error: the block's value is the reference
```

Bind the value first, then thread it: `receipt: mutable darray[u8] = encode(prefix)`, then
`receipt <- receipt.push(10)`. In a block, write `buffer <- buffer.resize(n)` and end the block
with `buffer`.

Both compilers reject these forms at check time. Regression fixture:
`test/parity/grown_return_smoke.sh`.
