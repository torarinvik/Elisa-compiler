# Semantic placeholder allocation removal

This change removes 17 `Expr.Absent` construction sites without changing the meaning
of absent source expressions. Value-threading sites carry an optional target (four
sites). Never-leak block traversal carries an optional tail (eleven sites), retaining
real absent AST nodes as present values when supplied by the source. Quantifier and
where-predicate lookups return a success flag and reuse their input as the unobserved
failure payload (two sites); every caller checks the flag before consuming that payload.

The source audit identifies eight additional semantic passes as append-only after
these changes. This establishes eligibility for parallel execution, not measured speed.

## Remote verification

All builds and tests ran on the Linux box in `/root/work/codex-semantic-sentinels`.
Stage0 was the private core778c8281 product. Retained main `m1` built the experimental
O2 `bin/gen1`, linked with the matching main runtime `/root/work/r7/rt.o`.

- Stage0 accepts the complete compiler source semantically.
- Main accepts the complete compiler source semantically.
- The experimental compiler builds and its self-check diagnostics match main exactly.
- Never-leak warning text and strict/gentle counts are pinned; rewritten programs run.
- Value-threading semantic tests pass, and 13 codegen pairs have identical machine code
  at both O0 and O2.
- Struct-field refinement shadow, refinement argument scope collision, quantified
  refinement overflow, and refinement return range overflow smokes pass.

Logs are in `/root/work/codex-semantic-sentinels/build` and
`/root/work/codex-semantic-sentinels-checks`. The focused smoke script intentionally
uses the documented stale-product override for this main-built experimental binary;
it does not claim fresh-seed provenance. Fresh seed/self-host fixpoint, full semantic
corpus comparison and quiet timing remain before production integration.
