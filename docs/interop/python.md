# Python extensions

An Elisa source file with an `export pymodule` declaration can be compiled
into a CPython extension with a typed `.pyi` interface. This example builds
the repository's `fastmath` fixture for the selected Python interpreter.
Install that interpreter's CPython development headers before building.

```sh
mkdir -p build/python
PYTHON_BIN=python3 scripts/elisac_stage1.sh -emit pymodule-so \
    -o build/python/fastmath.so test/repro/pymodule_export.elisa
PYTHONPATH=build/python python3 -c 'import fastmath; print(fastmath.add(20, 22))'
```

Compile with the same Python version that will import the module. To generate
only the interface, use `-emit pymodule-pyi` with a `.pyi` output path.

## Type conversion

Use records for structured results rather than packing unrelated values into
numeric arrays. A function returning `Result?` maps to a Python
`Result | None`; `Result` is a generated `TypedDict` with named fields.
Supported scalar, text, nested-record and array fields use the ordinary record
converters. Arrays become independently owned lists, including nested rows;
text becomes `str`, and Python object fields retain their references. Conversion
finishes before temporary native arenas and input owners are released.
Throwing functions retain the ordinary typed Elisa exception interface, with
`None` representing successful absence rather than an error. Nullable record
inputs and nullable record-valued fields are not yet supported.

Text inputs accept `str` or UTF-8 `bytes`, including inside records and
containers. Invalid UTF-8 is rejected before calling native code. `cstr`
rejects embedded NULs; `sview` preserves them. Nullable text also accepts
`None`. Generated converters call Elisa's text helper explicitly, leaving
the CPython API unchanged and avoiding redundant Unicode validation.

Native collection methods require the standard-library collection helpers in
scope. Text set queries support `set[cstr]` and `set[sview]`. String-view keys use
length-aware byte-content hashing and equality, preserving embedded NULs.
Borrowed key storage must remain alive and unchanged while the set uses it.

Numeric read-only views borrow compatible one-dimensional C-contiguous,
natively aligned buffers; other sequences and incompatible read-only buffers
are converted into temporary native storage. Mutable numeric views require a
writable buffer with matching type, layout and alignment, since copying would
discard updates. Rejected borrows release the buffer before conversion or error.

Generated annotations describe numeric view inputs as `Sequence[T] | Buffer`
and writable view inputs as `Buffer`. This accepts NumPy and other buffer
exporters without widening writable arguments to `Any`. Element format,
rank, contiguity, alignment and write permission remain runtime constraints.
The stubs use `collections.abc.Buffer` on Python 3.12+, and the official
`typing_extensions.Buffer` backport under a type-checking-only import for
older Python targets. Native module imports gain no backport dependency.
