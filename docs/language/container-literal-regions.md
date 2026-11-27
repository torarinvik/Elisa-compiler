# Where container literals and comprehensions allocate

A non-empty `darray`, `dict` or `set` literal, and every `[x for x in ...]` comprehension,
allocates. It takes its region from its **destination**. These positions supply one:

- a binding, typed or inferred: `xs: darray[i64] = [x for x in 0..<n]`;
- an assignment: `xs <- [x for x in 0..<n]`;
- a struct field: `Holder{items: [x for x in 0..<n]}`;
- the body of a function whose return type is a container, or whose body already allocates
  without an `Arena` parameter (the compiler wraps such bodies in an automatic region);
- anything inside a `region NAME(...):` or `in OWNER:` block;
- for a comprehension only, the single argument of `xs.extend(...)`, which appends straight
  into `xs`. `xs.push([...])` and `xs.extend(&[...])` still need a destination.

Everywhere else there is no destination, and both compilers reject the expression:

```
comprehension has no region to allocate in; it takes one from its destination: annotate the
binding, use a matching return type, or store it in a struct field (a call argument supplies none)
```

For a comprehension, that covers:

- a call argument, by value or borrowed with `&`, for any callee (plain, module-qualified, a
  method, or generic);
- a `for` iterable;
- the receiver of a field or method access.

For a literal, the check fires only where the parameter at that position is written as a
`darray`, `dict` or `set`. A literal can also become a fixed `array[T, N]`, which needs no
region.

## Fix

Bind the value first, then pass the binding:

```
items: darray[i64] = [x.i64() for x in 0..<count]
total(&items)
```

A borrowed literal such as `&[1, 2, 3]` is a fixed array, not a darray. Passing it to a
`darray[T]&` parameter is a type mismatch, not a region error.
