# Cloning values

`clone` makes an independent deep copy. It has three spellings:

```
copy = path.clone()                       # method: the type comes from `path`
copy = clone(path)                        # function: the same, as a call
copy: darray[u8] = clone[darray[u8]](path)  # explicit target type
```

All three read through a reference. With `path: darray[u8]&`, each gives an owned
`darray[u8]`, so you no longer have to copy element by element:

```
copy: darray[u8] = [path[item] for item in 0..<path.count]   # before
copy = path.clone()                                            # now
```

## What can be cloned

- Scalars, `sview`, `cstr` and packed enum handles are copied as they are.
- `darray`, fixed arrays, optionals and error unions are copied element by element.
- Cloning a `view[T]` gives an owned `darray[T]`.
- **Structs and tuples clone automatically, field by field, when every field can be
  cloned.** No derive or protocol is needed.
- `affine` and `linear` values cannot be cloned, and neither can a struct that holds one. A
  copy would duplicate a unique owner. To make a type uncopyable, declare it `affine`:

```
clone cannot clone Handle& into Handle in v1
```

- References, function values and value enums cannot be cloned yet.

## Names

`x.clone()` is the builtin unless something user-defined takes it: a field or method named
`clone`, an extension method, or a one-argument function `clone` whose parameter has the
receiver's type. A user function named `clone` also takes the plain spelling `clone(x)`. The
method spelling still reaches the builtin for receivers that function doesn't accept.

## Where the copy lives

A clone allocates, so like a container literal it takes its region from its destination (see
[where container literals and comprehensions allocate](container-literal-regions.md)). A
function that clones gets an automatic region, unless it receives an `Arena` parameter. In
that case the clone needs an `in <owner>:` block.
