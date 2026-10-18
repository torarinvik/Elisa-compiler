# Annotation hash loop proof repair

The three annotation byte-fold loops now state `invariant 0 <= offset` alongside their upper bounds. The loop index is modeled as a signed integer; an upper bound alone admits negative arbitrary induction states and cannot establish the recursive prefix preconditions. The new bound is established from the range start and preserved by iteration. Existing assertions, fold invariants, and postconditions remain intact.

The exact production row/pair helper extraction passes strict semantic analysis on Core 434cc791 (including char conversion and XOR congruence fixes): zero diagnostics, test package 1.285 seconds. Before adding the bounds, the same extraction reported three unproven fold invariants. This is a focused correctness result, not a full Stage1 build or compile-time benchmark.

The row source-bound proof gate passes its structural checks. The pair helper shapes pass after synchronizing its expected shape with the existing production step assertions and the new bounds; the complete pair structural gate later stops at a separate existing module-cache invalidation shape mismatch. Independent proof-product replay has not run. Raw strict result, extracted source, hashes, and baseline query trace are saved under `build/verification/annotation-hash-lower-bounds-20261018/`.
