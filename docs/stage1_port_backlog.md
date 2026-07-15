# Stage1 Port Backlog — the next 300 items (stage0 → stage1)

Generated 2026-07-15 from a five-way gap analysis of `Elisa-core/compiler/src` (stage0, Go)
vs `Elisa-compiler/src` (stage1, self-hosted). Ordered by phase: fix stage1's own debt
first, then structure the AST, then core types, then the analysis engines, then remaining
diagnostics, then backend/codegen, then pipeline extras. Stage0 file references are the
porting source of truth.

## Phase A — Stage1 hygiene, known bugs, and test debt (1–40)

**Status (2026-07-15):**
- DONE (committed): 1, 2, 5 (README/manifest freshness); 6, 7, 8 (match_pattern_smoke
  false-green SKIP paths → hard FAIL, strict build); 11, 12, 13 (primer de-staled to
  grep anchors; breadth `_unused` glob tightened); 18–32 (68 previously-uncovered
  check_* diagnostics now have verified pos/neg fixtures — diagnostics smoke 188/188,
  full gate 44/44). 33 is the same corpus-hygiene as covered here.
- SATISFIED (no change needed): 10 (breadth run.sh consumes only the P count, so the
  UndefinedName D-noise never reaches the gate; already documented); 15 (both named
  regressions are guarded — literal_comparison_impossible.neg fixture is the FP guard,
  machine_from_smoke case 3 exercises the arm/payload binding).
- BLOCKED on Phase C (real type + namespace/visibility resolution, items 107–110):
  16 (extending UnknownFieldType/UnknownTypeName past the lowercase-only heuristic would
  false-positive on every legitimate cross-module capitalized type until the resolver can
  see them — the uppercase-skip is a deliberate soundness guard, not laziness).
- DEFERRED (needs a decision / larger effort): 3, 4 (cross-repo lexer oracle infra);
  9 (runtime drift reconciliation — real bidirectional drift, tracked separately);
  14 (reproduce-or-retire the stage0 `*ast.TypeExprExpr` backend divergence — needs a
  stage0 backend build); 17 (multi-scrutinee tuple-match exhaustiveness — real feature).


1. Update README.md:39 "Semantic: not yet written" — stale; 93 checks + 142 DiagnosticKinds exist.
2. Rewrite README.md:68 TODO list to reflect real remaining work (backend, oracle, resolver depth).
3. Build the cross-repo parity oracle: `-emit tokens`/checksum subcommand on stage0 `elisacore` (README:63-65).
4. Wire lexer parity (`run_parity.sh`) into an always-on gate, not manual-only (README:49-50).
5. Fix stale `manifest.json`: declared entry `src/elisac.elisa` / `src/elisac.elisai` don't exist.
6. Remove the SKIP-on-build-break path in `test/parity/match_pattern_smoke.sh:25-34` (silently green when stage1 fails to build).
7. Remove the SKIP-on-clang-link-failure path in `match_pattern_smoke.sh:34`.
8. Port/write the missing docs/119 spec referenced by `match_pattern_smoke.sh:29`.
9. Wire `scripts/check_runtime_drift.sh` into `test/parity/run_all.sh` (runtime can drift while gate stays green).
10. Fix `test/breadth/run.sh` per-file-isolation UndefinedName noise: resolve cross-file names or suppress the kind in breadth mode so `D <n>` counts become trustworthy.
11. Document/enumerate the `_unused`-path exclusions in `test/breadth/run.sh:14`.
12. Re-audit primer doc `docs/notes/port_primer_template.md` wiring anchors (claims ordinal 122/old line numbers; enum is at 142).
13. Audit DiagnosticKind (142) vs check files (93): document which kinds share a check fn; regenerate the wiring-point list.
14. Reproduce-or-retire the open stage0 backend divergence: `x is Enum.PayloadlessVariant` in `if` crashing stage0 on `*ast.TypeExprExpr` (ast_shape_gotchas.md:351-377).
15. Verify regression fixtures for the two historically-fixed bugs named in `run_all.sh:9-11` still exist and fail-on-revert.
16. Extend `UnknownFieldType` beyond the lowercase-only heuristic (struct_layout_smoke.sh:18-19) with proper cross-module resolution.
17. Multi-scrutinee tuple-match exhaustiveness (`match a, b:`) in `resolve_types.elisa:287` (cartesian product).
18–40. Add pos/neg fixtures (and smoke where warranted) for the 70 uncovered check_* diagnostics — batched:
18. fixtures: affine_collection, assign_to_loop_var, call_non_function, call_named_non_function.
19. fixtures: array_literal_arity, array_literal_element, construct_field_type, firm_arg_type_mismatch, literal_arg_type_mismatch.
20. fixtures: compound_assign_nonnumeric, redundant_arithmetic, self_arithmetic, self_assignment, self_comparison.
21. fixtures: constant_comparison, constant_condition, logical_constant_operand, identical_branches, identical_logical_operands.
22. fixtures: division_by_zero, modulo_by_zero, shift_by_zero, negative_shift, oversized_shift, nonnumeric_shift, shift_non_integral.
23. fixtures: duplicate_condition, duplicate_decorator, duplicate_dict_key, duplicate_import, duplicate_set_element, duplicate_variant_field.
24. fixtures: duplicate_match_arm (non-enum), duplicate_pattern_binding, nonbool_match_guard, void_match_scrutinee.
25. fixtures: dict_key_mismatch, dict_value_mismatch, set_element_mismatch, darray_element_mismatch, ternary_branch_mismatch.
26. fixtures: empty_iterable, empty_range, infinite_loop, redundant_continue, immediate_overwrite, unused_expression, discarded_call_result.
27. fixtures: index_non_indexable, index_out_of_bounds, negative_index, string_index_nonintegral, range_bound_non_integral.
28. fixtures: field_access_on_primitive, unknown_field_access, unknown_type_name (general kind), literal_assign_out_of_range.
29. fixtures: float_equality, double_negation, negated_comparison, redundant_bool_compare.
30. fixtures: void_argument, void_collection_element, void_field_access, void_index, void_operand, void_unary_operand, void_value_use.
31. fixtures: if_value_missing_else, contract_position, contract_result_void (resolve name drift vs contract_ensure_result_void), const_enum_member_value.
32. Resolve string_index_nonintegral vs string_index_nonnumeric naming drift.
33. Retire the 5 in-tree Go consumers in Elisa-core that still use the pre-stage1 frontend (README:66-67).
34. Add smoke coverage for decorator checks in the parity gate (run_all.sh gap).
35. Add smoke coverage for import checks (duplicate_import/unused_import) in the parity gate.
36. Add smoke coverage for array/collection-literal checks in the parity gate.
37. Add a breadth-corpus diagnostic-count baseline file so regressions in `D <n>` are visible per-file.
38. Add a stage0↔stage1 diagnostics diff oracle over the fixtures corpus (same file → same kinds).
39. Add per-check unit-test convention doc so every new check lands with fixtures (stop the 70-file coverage hole growing).
40. CI target that builds stage1 with itself once semantic is complete (self-check gate placeholder).

## Phase B — Parser/AST structuring (41–90)

41. Structure `Pattern.Other` raw-span fallback into real pattern AST (parser_tokens.elisa:263).
42. Decompose match-arm patterns from `capture_pattern_span` raw spans into a Pattern tree (parser_stmt_pattern.elisa:6-19).
43. Deep nested struct patterns (stage0 parseBraceMatchStructPatternArg).
44. Variant patterns with payload bindings as structured nodes.
45. Tuple patterns as structured nodes.
46. Or-pattern alternatives as structured nodes (needed for binding-consistency check).
47. Rest-bind / as-bind / range patterns structurally (docs/122 forms).
48. Structure contract clauses: `requires` as ast node (not generic contract_statement).
49. Structure `ensure` incl. EnsuresCondition (stage0 parseEnsuresClause/Condition).
50. Structure `EnsuresPath` dotted mutation paths for changes/preserves (stage0 parseEnsuresPath).
51. Structure `EnsuresStateCases` (typestate case lists in ensures).
52. `preserves` clause support (zero hits in stage1).
53. Structure `decreases` measures (expr list + `*` reason form).
54. Structure struct-body `invariant EXPR` predicates (parser_types.elisa:371-378).
55. Quantifier expressions `forall`/`exists` into AST (stage0 parseQuantifier; currently raw text).
56. Parse `law` predicates into AST instead of raw sview (parser_decl.elisa:335, parser_tokens.elisa:204).
57. General refinement type suffix `T where PRED` on any type expr (stage0 parseRefinementTypeSuffix).
58. `type X = T where PRED` alias refinement — model on Decl.Alias (parser_decl.elisa:261, currently consumed).
59. Structure `can EFFECT:` blocks as CanStmt with effect refs (not generic Block).
60. Structure `region NAME(args):` as RegionStmt with allocator/backing args (currently degrades to empty stmt, parser_stmt_control.elisa:186).
61. Structure `try:` blocks distinctly.
62. Structure `catch` arms with typed error-tag bindings (stage0 parseCatchArm/Arms).
63. RecoveryClause structural support (stage0 parseRecoveryClause).
64. Error declaration ASTs: ErrorDecl + payload variants (stage0 parseErrorDecl/parseErrorPayloadDecl).
65. Structured ErrorSetExpr/ErrorTagExpr type expressions `T ! {A, B(p)}` (stage1 keeps only a bool flag).
66. Model `error[...]` clause on signatures in the symbol table (parser_types.elisa:183; `-> void error[E]` vs `-> void` currently indistinguishable).
67. `using` declaration modeled in resolver (parser_decl.elisa:209, parsed-and-discarded).
68. `ghost` struct fields as distinct AST (parser_types.elisa:363).
69. `ghost def` function declarations as distinct decl kind.
70. `permission FAMILY:` declarations as structured Decl.Permission (stage0 parsePermissionDecl/Refs).
71. Grant/alias declarations structured (stage0 grant_alias_decl).
72. `bit_group` declarations structured (stage0 parseBitGroupDecl).
73. `layout Name size N:` guest-overlay layout decls with offsets/size constraints (stage0 parseGuestOverlayBody).
74. Static interface declarations (stage0 static_interfaces parser support).
75. Associated-type declarations in static interfaces (stage0 parseAssociatedTypeDecl).
76. `fulfills` clauses (stage0 parseFulfillsClausesAfterKeyword).
77. Typestate protocol declarations (stage0 parser_typestate_protocol.go).
78. `visit` construct: VisitArm + child bindings (stage0 parseVisitArm/Head).
79. `static assert` blocks (stage0 parseStaticAssertItemBlock).
80. `static generate` blocks/stmts (stage0 parseStaticGenerateBlock/Stmt).
81. Static-only `static if/elif/else` stmt forms (stage0 parseStaticOnlyIfStmt/Stmt).
82. Branch-hint annotations likely/unlikely on if (stage0 parseBranchHint).
83. `destroy` statement (stage0 ast.DestroyStmt).
84. `signal` / `notify` / `wait_all` concurrency statements (stage0 parseSignalStmt etc.).
85. Cascade statement full structuring (stage0 parseCascadeStmt; stage1 partial).
86. `with_arena` statement distinct semantics (stage0 parseWithArenaStmt).
87. `charset` declarations (stage0 parseCharsetDecl) — non-DSL lexer charset sugar.
88. Fix prefixed_block_statement lossy degradation generally: unknown prefix+no-block must diagnose, not silently vanish (parser_stmt_control.elisa:183-188).
89. Verify/skip deliberately-dead stage0 forms before porting: enum_map/keyword_map, checkpoint/restore, promote/adopt (removed by deprecation batches) — mark as WONTPORT in this file rather than porting.
90. Multi-scrutinee match parse support aligned with #17's exhaustiveness work.

## Phase C — Type-system core (91–110)

**DESIGN CONSTRAINT (found 2026-07-15, the critical prerequisite for this whole phase):**
`InferType` (in semantic_types.elisa) is currently a POD `{kind, name: sview}` returned by
value from `infer_expression_type`. Structural element types (for tuples/generics/refs) must
NOT be added as an owned `darray[InferType]` field — doing so makes the returned value
region-bearing, which turns `infer_expression_type` region-polymorphic and forces **all ~20
of its call sites** into region-inferable contexts (verified empirically: a one-field add
produced "call to region-polymorphic … must occur where a region can be inferred" at every
caller). Use stage0's flat-interned model instead: keep `InferType` POD and carry a `u32`
index into a `SymbolTable`-held pool of element-type lists (mirrors stage0 `typeid.go` /
`types.go`). Every Phase C sub-item below assumes that interned-table representation. A
placeholder scalar `TypeKind.Tuple`/`Ref`/`Optional` with no structural payload is NOT worth
landing on its own — no consumer can use it, and it still risks the arithmetic-inference
interaction in `infer_expression_type`.


91. Replace coarse TypeKind (Unknown/Void/Int/Float/Bool/Char/String/Named) with a real type representation: tuples.
92. Type representation: references (`T&`, `mutable T&`).
93. Type representation: optionals.
94. Type representation: generic instances (darray[T], dict[K,V], user generics).
95. Type representation: function types (params/ret/effects) — stage0 analyzer_func_types.go.
96. Type interning/identity (stage0 typeid.go).
97. Type equality/compatibility lattice (stage0 types_compare.go).
98. Unification core for inference (stage0 analyzer.go/types.go).
99. Generic type-parameter substitution (stage0 analyzer_substitute_types.go).
100. Generic instantiation + cache (stage0 analyzer_generics.go).
101. Type traversal/visitor infrastructure (stage0 analyzer_type_traversal.go) incl. recursion-limit guard.
102. Bidirectional/contextual expected-type propagation (stage0 analyzer_expr_contextual_*.go).
103. Integer-literal type inference & defaulting rules.
104. Type-constructor call validation `T(x)` (stage0 analyzer_type_constructor_calls.go).
105. Type-diagnostic pretty formatting (stage0 diagnostic_type_format.go).
106. Symbol tables with scopes/shadowing beyond flat resolve.elisa; value-symbol flow state (stage0 analyzer_value_symbols.go).
107. Namespace resolution engine: modules, `::` access, visibility, public: re-export (stage0 namespaces.go).
108. Namespace-vs-value disambiguation diagnostics (`%q is a namespace; write %s::%s`).
109. Extension-method resolution + duplicate detection (stage0 extension_methods.go).
110. Cross-declaration analysis record building (stage0 analyzer_decl_analysis.go).

## Phase D — Semantic analysis engines (111–220)

Regions & lifetimes:
111. Region parameter inference for calls (analyzer_region_param_inference.go).
112. Region polymorphism resolution `__region_auto` (analyzer_region_polymorphism.go).
113. Per-region stack assignment (analyzer_region_stacks.go) incl. growable-container rules.
114. Region container modeling: push-legality, store-into-longer-lived (region_containers.go).
115. Auto-reserve/commit sizing inference (analyzer_auto_reserve.go).
116. Region death-time computation (analyzer_region_deathtime.go).
117. Region lifetime scope binding (analyzer_region_lifetime.go).
118. Region provenance through expressions (analyzer_expr_region_provenance.go).
119. Region state clone/merge/provenance at flow joins (analyzer_flow_region_state_*.go).
120. Region-backed struct locals: thread region into callee `@r` (region_struct_local.go).
121. Region backing kinds: reserve_commit/fixed validation (region_backing.go).
122. Nested-region escape detection (store-into-outer).
123. Ref storage-outlives checking (analyzer_ref_storage_outlives.go).
124. Region string-view builtins (`darray cstr requires active arena`) (region_string_views.go).
125. Packed/region interaction (analyzer_flow_packed_regions.go).

Borrow/alias/permissions:
126. Alias-access classification read/write/exclusive + root tracking (analyzer_alias_access.go).
127. Call-site disjointness (analyzer_call_disjoint.go).
128. Function param disjointness contracts (analyzer_func_disjoint_params.go).
129. ReturnIsolation enforcement (laundered-borrow hole class).
130. Borrow annotation validation on externs (analyzer_borrow_annotations.go).
131. Borrowed-owner expr/summary/tracking flow analyses (analyzer_flow_borrowed_owner_*.go).
132. Return-param aliasing rules (analyzer_return_param_alias.go).
133. Parameter retention analysis (analyzer_param_retention.go).
134. Param store-target validation (analyzer_param_store_targets.go).
135. Permission-based reference validation (permissions_refs.go, permissions_validation.go).
136. Permission inference across control flow (permissions_inference.go).
137. Permission decl validation: reserved-top, duplicates (analyzer_permissions.go).
138. Permission alias/family conflict checks (analyzer_effects.go).
139. Redundant-grant detection (surrounding can-block already grants).
140. Global permission scope checking (global_permissions.go).
141. Storage-view interior-borrow tracking / Pooled[T] safety (analyzer_storage_views.go).
142. Storage-view mutation legality checks.

Effects:
143. Effect-row representation and merging.
144. Grant propagation with row algebra (beyond check_ungranted_panic surface lint).
145. Effect subsumption / row polymorphism (analyzer_impl_effect_variance.go).
146. Impl effect-variance vs interface declarations.
147. Protocol/contract variance under effects (analyzer_protocol_contract_variance.go).
148. Reentrant-safety segments (@reentrant_safe cannot call X) (segment_safety.go).
149. Segment.Host/Guest/Unsafe grant restrictions (segment_safety.go).
150. Hot-loop contract / effect-cost checking (analyzer_hot_contract.go, analyzer_perf_contract.go).

Contracts & proofs:
151. Named contracts engine (analyzer_named_contracts.go) incl. includes-clause rules.
152. Requires-clause discharge / proof obligations (analyzer_requires_discharge.go).
153. Frame conditions: changes/preserves enforcement (analyzer_frame_changes.go).
154. Frame fact survival across calls (analyzer_frame_fact_survival.go).
155. Higher-order function contracts (analyzer_higher_order_contracts.go).
156. Law/contract axioms (analyzer_law_contract.go) incl. composite laws.
157. Law `is`-relation checking (analyzer_law_is.go).
158. Modular laws (analyzer_modular_laws.go).
159. assert-by proof tactics + citation checking (analyzer_assert_by.go).
160. Lemma declaration/application (analyzer_lemma.go).
161. Loop invariants (analyzer_loop_invariants.go).
162. Structural induction (analyzer_structural_induction.go).
163. Proof-hole tracking (analyzer_proof_holes.go).
164. Proof diagnostics reporting (analyzer_proof_diagnostics.go).
165. Recursive proof certificates (analyzer_recursive_proof_certs.go).
166. Recursive pure-function returns (analyzer_recursive_pure_returns.go).
167. Ghost-function restrictions (no frame/runtime effects) (analyzer_ghost_funcs.go).
168. Invariant checking on struct/enum construction+mutation sites.
169. Contract spec-purity enforcement (requires may not read mutable global).

Refinements & bounds:
170. Refinement scheme representation (refinement_scheme.go, analyzer_refinement_scheme.go).
171. Path-sensitive refinement flow (analyzer_refinement_flow.go — largest engine, 3011 lines; split into sub-ports).
172. Refinement predicate-fact extraction (analyzer_refinement_predfacts.go).
173. Where-clause refinement checking (analyzer_where_refinements.go).
174. Where-call precondition discharge (analyzer_where_call_discharge.go).
175. Where-field-store violation detection (analyzer_where_field_store.go).
176. Named-refinement alias resolution + cycle detection (analyzer_named_refinement_alias.go).
177. Bounds indexing refinement — index-in-range proofs (analyzer_bounds_indexing.go).
178. General arithmetic bound propagation (analyzer_bounds_refinement.go).
179. Reserve-bounds/capacity proofs (analyzer_reserve_bounds.go).
180. Sentinel-index semantics (analyzer_sentinel_index.go).
181. Mut-ref out-param range re-seeding after calls.
182. Guard facts from postfix guards / conditions (guard_facts.go).

Termination & progress:
183. Core decreases verification incl. measure typing (analyzer_termination.go).
184. Structural termination (analyzer_termination_structural.go).
185. Mutual-recursion termination (analyzer_termination_mutual.go).
186. Interprocedural callee-summary termination — docs/118 (analyzer_termination_callee_summary.go).
187. Guard-if loop-termination pattern (analyzer_loop_termination_guardif.go).
188. Progress-safety engine (progress_safety.go).

Flow analyses:
189. Definite-assignment analysis (analyzer_flow_definite_assign.go).
190. Affine/must-consume linear state machine (analyzer_flow_affine_consumption.go) incl. drain-via-move rules.
191. lmut linear-mutable tracking (analyzer_flow_linear_mutable.go).
192. Match exhaustiveness engine — real coverage computation (analyzer_flow_match_coverage.go).
193. Match core dispatch/arm binding types (analyzer_flow_match_core.go).
194. String/struct/tuple match semantics + in-store clauses (analyzer_flow_string_struct_tuple_match.go).
195. Variant move-as pattern checks (analyzer_flow_variant_patterns.go).
196. Optional-match in-store validation (analyzer_flow_optional_match.go).
197. Or-pattern binding-consistency check (analyzer_flow_blocks.go).
198. Flow-strict §6b block-if detector port (analyzer_flow_blocks.go, 1284 lines).
199. Flow complexity scoring r1–r6 (analyzer_flow_complexity*.go).
200. Flow IR construction (flow_ir.go, flow_instrs.go).
201. Value-merge / join-rule engine (analyzer_flow_value_merges.go, analyzer_flow_join_rule.go).
202. Tracked-clone / tracked-type-merge / specialized merges (analyzer_flow_tracked_*.go).
203. Defer restrictions (no raise/return; capture rules) (analyzer_flow_defer_*.go).
204. Lambda capture/type inference + capture-legality (analyzer_lambda.go).
205. Parallel-capture concurrency safety (analyzer_flow_parallel_captures.go).
206. Call post-state tracking (analyzer_flow_call_poststates.go).
207. Named-state poststates + paths / typestate engine (analyzer_flow_named_state_*.go).
208. Protocol/typestate must-consume-before-scope-exit (analyzer_flow_protocols.go).
209. Machine-from start-state + qualified-state validation (analyzer_machine_from.go).
210. Machine state-path completeness beyond tag coverage (analyzer_machine_coverage.go).
211. Error-set match/join computation + polymorphism (errorset match engine).
212. Store-inference for packed-enum move-as (analyzer_flow_store_inference.go).
213. Sequence-rewrite arm checking (analyzer_flow_sequence_rewrite.go).
214. Fold/visit tree-construct enforcement (analyzer_flow_fold_match_exprs.go).
215. Consteval engine — compile-time evaluator (analyzer_consteval.go, 2736 lines; split into literal/arith/const-fn sub-ports).
216. Classifier constant folding (analyzer_classifier_fold.go).
217. Enum sealed-refinement totality + layout/tag encoding (analyzer_decl_enums.go, enum_layout.go) incl. sparse-requires-soa.
218. Struct decl analysis: derive, layout, bitfield storage typing (analyzer_decl_structs.go).
219. Static if/elif compile-time bool + duplicate error-tag decl checks (analyzer_decl_types.go).
220. Value-block (E4) capture-scope checking (analyzer_value_block_e4.go).

## Phase E — Remaining diagnostics & lint suite (221–250)

221. Implicit param/argument resolution diagnostics (analyzer_implicit.go).
222. Extern decl/impl signature matching + intrinsic restrictions (analyzer_value_symbols.go).
223. Export C-ABI compatibility checks (exports.go).
224. Hook validation (__cast__ etc.) (analyzer_hooks.go).
225. Default-argument type/syntax validation (default_args.go, explicit_args.go).
226. Param-pack duplicate checking (param_packs.go) — keep only ImplicitParamNames-relevant parts.
227. Generic argument validation (states/regions/values) (analyzer_generics.go diagnostics).
228. Runtime carrier type restrictions (runtime_carrier_warnings.go).
229. Copy-builtin validation (analyzer_copy_builtin.go).
230. Freeze/clone packed-store helper validation (analyzer_expr_packed_helpers).
231. Threading/atomic specialization checks (shareability, memory-order consts).
232. zip_map / view-helper callback-type checks.
233. Projected-borrow field-path resolution diagnostics.
234. dstr string-literal checks (analyzer_dstr_string_literal.go).
235. Unbounded string-cast checking (analyzer_unbounded_string_cast.go).
236. Guest-overlay host/guest boundary diagnostics (analyzer_guest_overlay.go).
237. Charset decl validation: cycles, non-ASCII reservation (analyzer_decl_charset.go).
238. Layout decl duplicate-field checks (analyzer_decl_layout.go).
239. Shape-parameter validation + shapes inference notes (analyzer_shape_params.go, analyzer_shapes.go).
240. -Wperf: optimization fact inference (optimization_fact_inference.go).
241. -Wperf: call-facts propagation (optimization_call_facts.go).
242. -Wperf: scaled extent tracking (optimization_extents).
243. Scalar-permission loop lint (stays-scalar warns unless can Scalar).
244. Churn lints: allocation churn, lock churn, pool churn, task-group churn (4 analyzers).
245. Hot-loop lints: atomic CAS-in-loop, await-in-loop (2 analyzers).
246. Push-loop-extend + unreserved-fill lints.
247. By-value grown-container lint + loop member-access perf lint.
248. Pointer-graph (intrusive) lint + handle-width lint.
249. Disjoint-param perf lint.
250. Function-graph partitions / sink analysis / fact snapshots (interprocedural fact caching trio).

## Phase F — Backend / codegen (251–285)

251. LLVM module/context/target setup + data layout (llvm_target.go).
252. Backend options/flags parsing (options.go, llvm_flags.go).
253. ABI aggregate layout + calling conventions (llvm_abi_layout.go, llvm_aggregate_abi.go).
254. Type lowering: struct/enum bodies, alignment, generic instance structs (llvm_types_*).
255. Constant lowering + const dict literals + consteval consts.
256. Global variable emission (llvm_globals.go).
257. Function body emission: statements dispatch, entry allocas, scope checkpoints (defer/drop).
258. Expression emission core: calls, fields, indexes, unary/binary, ternary.
259. Struct-literal construction lowering (llvm_struct_literals.go).
260. Lambda/closure capture lowering (llvm_lambda.go).
261. Enum match lowering: tag switch + arm trees + payload pattern test/read.
262. Packed-enum ABI: mode selection, store-ops (load/store side words, tags), constructor alloc, field offsets.
263. Optional/null match + niche-value optimization.
264. String match + membership (`in`) lowering.
265. Iterator loops: chunked/exact-item, pattern bindings, pattern filters.
266. Comprehension/fold lowering: tree-fold helpers, reduce-sum, zip_map, sequence rewrite.
267. F-string interpolation lowering (llvm_exprs_fstring.go).
268. String/view specializations: arena-view eq, slice eq, view copy, darray string views.
269. Dict/darray builtins: push, entry get-or-insert/insert, resize zero-init, hash functions.
270. Region/perm allocator runtime-call emission (llvm_perm_region.go) + checked alloc/reserve sizes.
271. Bounds-check instrumentation (-fbounds-check index watchdog) + deref guards.
272. Refinement-check + invariant-recheck instrumentation (debug-gated contracts).
273. Segment-safety codegen checks (llvm_segment_safety.go).
274. Atomics lowering (load/store/rmw/cas) (llvm_atomics.go).
275. Parallel-for/concurrency statement lowering.
276. Bitgroup packing lowering (llvm_bitgroups.go).
277. Monomorphization/specialization (llvm_specialize.go) + static-interface dispatch.
278. noalias/nounwind/inline attributes + branch weights (llvm.expect).
279. Autovectorization verify pass + diagnostics (llvm_autovec_verify.go).
280. Exports: export func ABI wrappers + C header generation (llvm_exports.go, c_header.go).
281. Guest-overlay + guest-table lowering (FFI overlay types).
282. DWARF debug info: compile unit, basic/struct/darray/array DITypes, DISubprogram, locals, line locs, finalize.
283. Enum column-scan (SoA) lowering + tree-variant structural access.
284. Promotion rules, casts (bitcast/value split), float↔ptr edge cases.
285. Module verify + IR printing + `-emit` modes (obj/test/ir).

## Phase G — Pipeline extras (286–300)

286. Frontend IR bundle: encode/decode + type registration (frontendir/bundle.go).
287. SMT-LIB2 solver bridge: process lifecycle, check-sat, get-value, S-expr reader (src/smt/smt.go).
288. SMT discharge tier hookup (-smt): VC IR + weakest preconditions (analyzer_smt_discharge.go, analyzer_vc_*.go — split port).
289. Entailment matrix / cross-module where matrix.
290. Unparser: decl/stmt/expr writers with precedence-aware printing (src/unparse — needed for tooling/format).
291. Unparser: contract/annotation/lambda/match/pattern formatting.
292. Unparser: where-view sugar reconstruction + recovery-clause formatting.
293. CLI driver: project.json handling, target selection, flag surface parity with stage0 elisac.
294. Interpreter/REPL core: stmt exec + expr eval (src/interpreter) — decide port vs WONTPORT for stage1.
295. REPL affordances: history, completion, meta-commands (`:load`, `:reload`) — contingent on 294.
296. Interactive debugger hooks (interpreter/debugger.go) — contingent on 294.
297. EASM inline-assembly: parse, op-rules, verification, assemble/instantiate (src/easm — decide scope; large).
298. EASM symbolic/lockstep oracle + preservation analysis — contingent on 297.
299. Static reflection/static generate execution (static_generate.go, static_reflection.go) — generated-decl lex/parse error propagation.
300. Runtime vendoring completeness: keep elisacore_std in lockstep (stores_*, concurrency, parallel, debug_referee, lldb pretty-printers) with the drift guard from #9 enforcing it.

## Explicit WONTPORT (deprecated in stage0 — do not port)
- Grammar DSL parsing (grammar_dsl_consolidation decision).
- enum map / keyword_map, checkpoint / restore checkpoint, region mark/restore/promote/adopt statements (construct-deprecation batch).
- `.specialize[T]()` (replaced by fn[T] value form), `?` recovery forms, `.ref` shorthand.
- Raw concurrency primitives (spawn1/pool_submit1/cond_wait/raw atomics) — hard errors in stage0.
