# stage1 backend port — scoping notes

## What the remaining work actually depends on

Measured, not estimated. stage0's backend is 54,417 lines / 156 files of cgo.

### dict is gated behind GENERICS (found 2026-07-17)

dict is NOT analogous to darray. stage0 lowers a darray INLINE, needing only two runtime
primitives (`arena_alloc`, `arena_realloc`) — so it could be mirrored by reading stage0's
`-emit llvm` output.

A dict instead calls **monomorphized std generics**:

    arena_dict_get_mut__i64__i64
    arena_dict_find_index__i64__i64
    arena_dict_get_or_insert__cstr_key_shape__i64

and pulls the std into the module: a three-line dict program emits **102 functions**.
`%DynDict__K__V = type { ptr, i64, i64, i64, ptr }`, `%DictBucket__K__V = { ptr, i64, i8 }`.
A dict program also does not compile at all without `elisacore_std/collections.elisa`
included (`undefined identifier "arena_dict_get_mut"`).

So supporting dict requires, in order:
1. **Generic function instantiation / monomorphization** (`f[K,T]` -> `f__i64__i64`).
2. Compiling `elisacore_std/collections.elisa`, which itself needs error unions
   (`error[RuntimeError]`), references, and optional-of-reference (`mutable T&?`).

That is a subsystem, not a slice. Generics are the real gate, and they unlock user generics
too — so generics, not dict, is the next structural target.

Note the dict SYNTAX also differs from the guess: `d[k] <- v` does NOT insert
(`arena_dict_get_mut` returns `mutable T&?`, so it is a type error). The working forms are
a dict literal `{1: 40, 2: 2}` and `d.entry(k).insert(v)`; `d[k]` reads.

### Ordering implied by this

- generics/monomorphization  -> unlocks dict, set, user generics, most of the std
- region inference proper    -> auto regions exist (0d24d40) but nothing smarter: no region
                                parameters, no polymorphism, no death-time
- packed enums               -> needs the AoS store model
- effects, DWARF, -Wperf     -> independent, later

### Method that works

READ THE REFERENCE'S IR. `elisac -emit llvm x.elisa` hands over the exact representation,
runtime signatures, and constants (darray's 256 initial capacity, the Arena strategy=2
field, the grow rule). Every ABI in this port came from there rather than from guessing.
