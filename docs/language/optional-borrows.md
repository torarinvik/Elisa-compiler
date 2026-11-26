# Optional borrows (`T&?`)

An optional borrow is a reference that may be null. It is a nullable pointer, so it costs
nothing over a plain borrow. Use it for an output a caller may or may not want, instead of a
`bool` flag plus a dummy buffer.

```elisa
def enqueue(value: usize, edges: mutable darray[usize]&?) -> void can[Memory.Allocate]:
    if edges is e:
        e.push(value)

def main() -> i32 can[Memory.Allocate]:
    buffer: mutable darray[usize] = []
    enqueue(3, &buffer)   # records the edge
    enqueue(4, null)      # nothing to record
    0
```

## Spelling

`T&?` is an optional borrow: maybe a reference to a `T`. The suffixes read left to right, so
`mutable darray[usize]&?` is a mutable borrow of a `darray[usize]`, which may be absent.

`T?&` is rejected. Both compilers report:

```text
`?&` is not a type suffix: write `&?` for an optional borrow (`T&?`, a reference that may be null)
```

## Using one

An optional borrow is used only after narrowing. There is no implicit unwrap: `edges.count` on
an unnarrowed `edges` is an error ("field access requires proven non-null reference").

Narrow with either spelling:

- `if edges is e:` binds `e` for the `then` block.
- `e = get edges else return` binds `e` for the rest of the block. A written type works too:
  `e: mutable darray[usize]& = get edges else return`.

Inside, `e` is an ordinary borrow under the normal borrow rules.

Pass `&buffer` or `null` at the call site. An optional borrow can also be forwarded unchanged
to another function that takes one.

## Growth and regions

Growing a container through a narrowed optional borrow (`e.push(x)`) allocates in the
**caller's** region, exactly as `edges.push(x)` does through a plain `mutable darray[T]&`
parameter. The compiler threads the caller's region into the function for you.

A call that passes `null` for every argument tied to that region grows nothing, so the
region binds to the program-lifetime region and the call needs no region of its own.

The plain borrow's escape rules apply unchanged:

- Returning an optional borrow of a local is rejected.
- Storing a forwarded optional borrow into longer-lived storage is rejected.
- Pushing a locally built container into the caller's container through `e` is rejected, as
  it is through `T&`.

A typed reference alias of a borrow parameter (`alias: mutable darray[usize]& = edges`) names
the same container, so growth through it also lands in the caller's region.

## Struct fields and returns

`T&?` is accepted as a struct field and as a return type, as `T&` is. Existing code relies on
both: the C-library bindings return nullable handles (`-> void&?`), and `arena_dict_get_mut`
returns `mutable T&?`. They are checked by the same escape rules as `T&`.

Regression fixture: `test/repro/optional_borrow_growth.elisa`, run by
`test/parity/optional_borrow_smoke.sh`.
