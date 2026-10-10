# Effect-template registration

The parser previously traversed all declarations for every handler installation and searched the complete annotation table for every function. Files with many installations paid this cost even when no function was marked as an abstract-effect helper template.

Registration now collects sparse template markers and matching declarations once, retaining declaration order and module ownership. Each installation visits those templates. With no markers, registration resets the active installation and returns immediately. Clone environments, overload source identities, required argument counts, registration order and helper-to-helper redirection retain their existing behavior.

## Measured workload

A generated file contains one static handler and 2,000 functions, each with an empty handler-installation block. It is 114,136 bytes and 8,009 lines; SHA-256 is `d2bc9f524a2d39a6f19f793acfb5b09e83e124a452680c5dfe4d0a1d646463d7`. This specifically measures registration without helper templates.

Both products were built from f99247d with the same native ARM64 Stage0 ef04267d (binary SHA d6647f1e), explicit -O3, LLVM 21.1.8, and runtime SHA 34789967. The candidate adds the template traversal change. Three samples per product used `-emit check -O0`, one job, phase timings, and the same input. Median results:

| Measurement | Baseline | Candidate |
| --- | ---: | ---: |
| Wall seconds | 25.229169 | 0.182767 |
| Child CPU seconds | 25.002869 | 0.195452 |
| Parse CPU milliseconds | 24813.6 | 8.7 |

All six runs exited zero, with identical output and diagnostics after removing timing rows. Paired unknown-handler, missing-operation and unhandled-effect controls rejected with identical diagnostics. The full compiler-source semantic self-check, broader effect-handler suite and native parser fixtures passed. The mutual-recursion control verifies two installations through an observable captured counter.

This is approximately 138 times faster on this particular installation-heavy input. It is not a compiler-wide multiplier or a comparison against Zig. Handler identity insertion, annotation queries, capture lookup and dense template matching need separate scaling measurements. An earlier comparison against a different compiler build is retained as historical evidence and is not used for patch attribution.

Complete local input, commands, product/source/runtime hashes, six sample logs and negative controls are retained under `parser-effect-template-working/evidence/parser-template/ab-2000-installs-matched-o3` in the local optimization workspace. Baseline product SHA starts 33ec8c3e; candidate starts 91201e75.
