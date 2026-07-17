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

## generics: design constraint found before implementing (2026-07-17)

Attempted monomorphization, got the machinery working (template registration from the
file-level `generic_param_names`/`generic_param_lines` side table keyed by function LINE;
binding-aware type resolution; `identity` + [i64] -> `identity__i64` mangling matching
stage0; declare-at-callsite + worklist for bodies) — then hit a REAL region constraint and
backed it out rather than force it. What was learned, so the next attempt starts here:

### 1. Type bindings must live in an already-threaded table, not a new parameter

`no_type_bindings()` returning a fresh empty `TypeBindings` is REGION-POLYMORPHIC, so it
cannot be called from a non-region-inferable context ("must occur where a region can be
inferred"). Constructing an empty owned container per call site does not work. Put the
current instantiation's bindings in `StructTable` (already threaded everywhere a type is
resolved), set on entry to an instantiation and cleared on exit.

### 2. Mangled-name STORAGE is the real problem

An `sview` is a (ptr, len) VIEW. Building a mangled name into a local `darray[u8]` and
pushing it into a longer-lived table copies only the outer {ptr,count,cap} — the BYTES stay
in the function's auto region and are freed at return. Elisa's region checker catches this
exactly:

    value in region "__auto_N" is stored into longer-lived region "__rg_generics" via a
    by-value copy; region "__auto_N" is freed first, leaving a dangling element

(The backend's own region model catching a real dangling reference in the backend is a good
sign for the language; it is still a design problem to solve.)

Neither easy option is right:
  * `darray[darray[u8]]` — the inner buffer must be allocated in the TABLE's region, not
    built locally and pushed. Needs the name built in place, through a mutable reference to
    a slot that already lives in that region.
  * a flat `darray[u8]` pool + (start, len) — an sview into the pool DANGLES if the pool
    reallocs. Would have to re-derive the view at each use and never hold one.

The clean answer is probably a region-parameterized name builder (`def build_name[@r](...)
-> sview @r`) so the bytes are allocated in the table's region by construction. That is a
design pass, not a patch.

### 3. Scope for the eventual attempt

stage0 supports inferred (`identity(42)`) and explicit (`identity[i64](42)`) calls; the
explicit form makes the callee an `Expr.Index`, not an `Expr.Ident`. Start with ONE type
parameter and scalar type arguments; multi-parameter inference is separate.
