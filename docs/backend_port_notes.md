# stage1 backend port — scoping notes

> **Current-audit note (2026-08-31):** This document contains historical investigations as
> well as the live ledger. Several old blockers below have since landed: generic
> monomorphization, error-union return/catch lowering, nested variant matching, darray and
> fixed-array composition, and state-machine lowering. In particular, `machine over` must not
> be replaced with ordinary loops: the current parser keeps the machine and uses a helper for
> the bit-group member body so temporary AST values are not captured in an unstable transition.
> The local stage1 product lowers `test/breadth/emit_native.elisa` without dropping
> `parse_bit_group_members`, and `test/parity/state_machine_parser_selfhost_smoke.sh` guards it.
> **Extern/iterator follow-up (2026-09-01):** the compact extern side table now retains applied
> container element names, so `view[T]` and `darray[T]` parameters use their normal by-value ABI;
> mutable array-like iteration binds the element address over stage0's iterator copy. The focused
> ABI regression is `test/parity/extern_view_abi_smoke.sh`.
> **Error-union follow-up (2026-09-01):** first-class error unions now preserve the complete
> payload-carrying status, and `try`/`catch` supports direct calls, stored unions, function
> values, generic errorsets, and single- or multi-field payload bindings. The native parity
> regressions live in `test/parity/backend_native_smoke.sh`; `errorset_payload_catch_fields.elisa`
> and `errorset_payload_fn_value.elisa` are standalone repros.
> Treat the sections below as evidence and root-cause notes; verify their status against the
> current parity gate before reopening any item.

The notes below were written as the port went, so each one is dated and says what was
MEASURED rather than assumed. They are split by subject; this page is the index.

- [stage1 backend port — generics](backend_port_generics.md)
  - generics: design constraint found before implementing (2026-07-17)
  - nested generics: diagnosed to the exact line, not yet fixed (2026-07-17)
  - dict/set — genuinely blocked, chain traced end to end
  - dict/set — the ACCURATE dependency chain (correcting "one AST field away")
- [stage1 backend port — references and error unions](backend_port_references_errors.md)
  - references (`T&`): LANDED (68402af)
  - references (superseded — the wrong diagnosis, kept for the lesson)
  - error unions: ABI fully mapped, not yet implemented (2026-07-17)
  - Historical error unions (#17) — ABI investigation and earlier blocker notes
- [stage1 backend port — the features that landed](backend_port_landed.md)
  - Modules — LANDED
  - Externs — LANDED (the AST gap was fixed)
  - Tuples — BLOCKED on the stage1 AST (labels discarded)
  - Region threading (cross-fn) — LANDED
  - `packed enum` / the AoS store — LANDED (scalar-payload subset)
  - Struct-composition gaps — BOTH CLOSED (kept for the pickup notes)
  - MILESTONE (2026-07-28) — self-host CRASH FIXED (Elisa-core fd5cffee)
- [stage1 backend port — verified as nothing to port, and the tooling passes](backend_port_verified_absent.md)
  - Effects — NOTHING TO PORT (verified, not assumed)
  - DWARF — scoped: one 490-line file, and `-g` does NOT reach `-emit llvm`
  - `-Wperf` — LANDED (tagging + post-pass verdict)
  - DWARF and `-Wperf` — BOTH LANDED (the shared blocker is gone)
  - Death-time — NOT backend work (verified, like effects)

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
