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

## Optional refinement lookup follow-up

The isolated follow-up replaces three further construction sites: the default
`Expr.Absent` in `signature_requires_of` and both miss returns in
`struct_field_annotation`. Both helpers return `Ast::Expr?`; no match returns
null, while a matching real `Expr.Absent` remains a present payload. Signature
lookup retains its last matching line/kind row; field lookup retains its first
matching struct and first matching field. The signature consumer still ignores a
present Absent predicate, and field consumers retain their prior success behavior.

Remote source admission passes with private core778 and the retained fresh76
Stage1 product. The direct `refinement_lookup_presence_probe.elisa` compiles and
runs at O0 and O2, checking empty/missing lookups, duplicate selection and genuine
Absent payloads. It was built by predecessor Stage1 SHA-256
`b667627e9ff78e1eb90d002db2e083361f9bd612a454d1bce71d0fda9a07da85`,
linked with matching runtime SHA-256
`f903d6f450d4f7a082400586c895002930b52690e50eef01ce6c32b711f9acdb`.
Logs and artifacts remain in `/root/work/codex-refinement-lookup-sentinels/build`.

Static reachability identifies the removed helpers as the only remaining Absent
construction barriers for multiparam precondition, fixed-index range and guest
overlay checking. Refinement return checking still reaches other allocations,
including `container_element_annotation` and `law_predicate_by_name`. Historical
multiparam timing (213.4 ms) motivates this batch; it is not a measured gain.
Fresh seed and product-level focused checks follow the qualified source checkpoint.

## Hot-pass receiver and assignment follow-up

The isolated `codex/hot-pass-sentinels` batch starts at d6593153 and removes exactly
two additional placeholders. `storage_view_call_origin_sources` carries an optional
receiver, retaining a present real Absent expression and the original receiver/static
arity choice and argument shift. `bam_bind` accepts the already-decided
`holds_reference` flag: declarations retain the original absent-or-reference annotation
predicate, while untyped assignments pass true without constructing an annotation node.

The direct `hot_pass_sentinel_behavior_probe.elisa` tests receiver and static forms,
shifted origin positions, thread origins, unknown-overload precedence and a real Absent
receiver. It also tests genuine Absent declaration annotations/values, explicit reference
and value-copy annotations, untyped borrow assignment, retargeting tombstones, unchanged
other borrows, and owner reinitialization.

With explicit Linux/x86_64 host flags, complete source admission passed under core778
and the retained predecessor Stage1 product. The new probe compiled, strictly linked
without ignored unresolved symbols, and ran with exit 0 at O0 and O2. Predecessor product
and matching runtime digests are the b667627e/f903d6f4 values above. Logs remain in
`/root/work/codex-hot-pass-sentinels/build` (`stage0-linux-semantic`,
`predecessor-linux-semantic`, `hot-probe-linux-O0`, `hot-probe-linux-O2` and their done,
link and run records). Initial probe objects without the host flags selected a macOS
helper; those builds are not qualification evidence.

This does not establish either pass's parallel eligibility or a measured gain.
Region-storage checking still synthesizes Field/Call/Ident nodes in derived-origin
helpers. Borrow checking still reaches annotation helpers that construct Absent nodes.
Historical pass profiles (1331 ms and 514 ms) motivate investigation only. A fresh
experimental compiler, broader output comparison and quiet timing remain pending;
no integration has occurred.
