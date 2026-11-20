# LLVM pass tests

These standalone tests compile small C++ harnesses against the compiler's LLVM
passes. They cover [loop rewrites](loops/), [recursive functions](recursion/),
and [layout and vector rewrites](layout/).

To run a test, set `LLVM_CONFIG` to the `llvm-config` for the LLVM installation
used by the compiler:

```sh
LLVM_CONFIG="$(command -v llvm-config)" python3 test/llvm/loops/test_even_range.py
```

Some tests also require Z3 or an AArch64 host. Tests look for their SMT inputs
next to the Python harness.
