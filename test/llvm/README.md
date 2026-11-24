# LLVM pass tests

These standalone tests exercise the compiler's LLVM passes. Tests of the passes written
in Elisa run them through `elisac llvm-pass` (see `elisa_llvm_pass.py`, which uses `$ELISAC`
or `bin/elisac-stage1`); tests of the passes still in C++ compile small C++ harnesses.
They cover [loop rewrites](loops/), [recursive functions](recursion/),
[memory rewrites](memory/) and [layout and vector rewrites](layout/); the target-specific
passes' tests sit at the top level.

To run a test, set `LLVM_CONFIG` to the `llvm-config` for the LLVM installation
used by the compiler:

```sh
LLVM_CONFIG="$(command -v llvm-config)" python3 test/llvm/loops/test_even_range.py
```

Some tests also require Z3 or an AArch64 host. Tests look for their SMT inputs
next to the Python harness.
