# Integer widths and C bindings

Elisa `int` is a signed pointer-sized integer, like `isize`. It is **not C `int`**.

| Elisa type | 64-bit target | wasm32 / 32-bit target |
| --- | --- | --- |
| `int`, `isize` | 64 bits | 32 bits |
| `usize`, `uintptr` | 64 bits | 32 bits |
| `i32`, `u32` | 32 bits | 32 bits |
| `i64`, `u64` | 64 bits | 64 bits |

Both compilers use these widths. Use explicit-width types for file formats,
network protocols, or values that must have the same width across targets.
On wasm32, generated JavaScript/TypeScript bindings expose `int` as `number`;
`i64` and `u64` remain `bigint`.

C declarations must match the target C ABI, including arguments, return values,
struct fields, callback signatures, and pointed-to values. On supported targets,
C `int` and `unsigned int` are 32-bit even when pointers are 64-bit:

```elisa
extern close(fd: i32) -> i32
extern read(fd: i32, buffer: u8&, count: usize) -> isize
extern strcmp(left: u8&, right: u8&) -> i32
```

A C return of `-1` must first be received as `i32`; conversion to Elisa `int`
then sign-extends correctly. Declaring that return as `int` on a 64-bit target
can read an unspecified or zero-extended upper half instead.

C `size_t` maps to `usize`, and POSIX `ssize_t` maps to `isize`. C `long` is
32-bit on Windows, but pointer-sized on the supported POSIX targets: do not
use one unconditional `int` or `i64` declaration for it across those platforms.
Windows `DWORD` maps to `u32`, and Windows `BOOL` maps to `i32`, not Elisa `bool`.

An `extern` in an Elisa `.elisai` interface may describe another Elisa function.
Such declarations must retain that function's Elisa signature; they are not
all C bindings.

Validation: `bash test/parity/int_c_abi_smoke.sh` runs native and wasm32 probes
against both compilers, including signed C returns and generated JS bindings.
