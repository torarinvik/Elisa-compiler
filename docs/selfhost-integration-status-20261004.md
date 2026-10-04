# Self-hosted compiler consolidation status — 2026-10-04

Integration was prepared on `codex/selfhost-main-integration` and qualified
for promotion to primary main after acceptance, native behavior and closure.

All local branch tips and unique detached tip `bb9f1b63` are incorporated into
the integration history. Uncommitted transpiler gains were preserved as
`8c5717ca`. Remaining origin build-speed/catch-enum-arm/studio-globals commits
are patch-equivalent (`git cherry HEAD origin/build-speed` reports only `-`).

Conflict resolution preserves current binder indexes, declared binding types,
alias identity metadata, append-only NameStore ownership, ordered lmut summary
indexes, and current storage checks over older superseded implementations.
The old parser experiments were moved out of production source into test/repro.

Fresh canonical Stage0 seed succeeds with Command Line Tools DEVELOPER_DIR and
-O0. Confirmed passing: typestate foundation O0/O2, derived loop O0/O2,
nullable extern callback ABI, refinement argument module collisions, and
adversarial escape (146 cases).

Integration repairs: immutable submit identity no longer appears in threaded
loop captures; type-position T&[N] is no longer parsed as bitwise ampersand;
zeroed-value container controls link the runtime object. The complete zeroed
safety gate now passes, including Stage0/Stage1 O0/O2 controls.

The complete repaired driver sweep passes bare at 2 disagreements (limit 6),
with no accept gaps, and with-std at zero disagreements (limit 0). Both results
were reproduced after the alias-owner repair. No ratchet has been loosened.
The native backend gate passes 563/563 before the subsequent packed-pattern
repairs; required Stage0 oracle compilation now fails the gate rather than
silently skipping cases.

Repairs and fixture diagnosis:

- Runtime inclusion no longer exempts nongeneric user code from reference
  forging or authority-upgrade checks. Audited runtime casts have local grants.
- Inline grants use exact expression spans; a granted argument cannot authorize
  its ungranted sibling. The authority gate passes both compilers in bare and
  runtime-inclusive modes, also testing function/global collisions in both orders.
- Classic named states do not require derived predicates; protocol graph checks
  remain enabled. The obsolete rejection and diagnostic expectation were removed.
- The global-storage control no longer accidentally collides with atomic `store`.
  The real function/global value-namespace collision is now rejected separately.
- Region-selector controls return scalars independently of local scratch values,
  separating legal owner resolution from return-provenance analysis.
- The local-view escape case is explicitly marked deliberate-decline: Stage1
  rejects a dangling view that Stage0's hidden arena happens to keep alive.
- Fresh array returns use a bounded overload fallback rather than trusting a
  spelling shared with atomic `load`. Unknown, nested, extern, arity-mismatched,
  shadowed and borrow-carrying candidates remain conservative. Builtin array
  symbol rows must not be mistaken for distinct nominal structs. The storage
  gate preserves rejection of global-buffer and view-payload dependencies.

Bootstrap exposed three additional lowering gaps: payloadless packed `or`
arms, nested value-match bindings, and nested string constraints. The recursive
matcher now compares string contents and falls through on mismatch instead of
silently treating the literal as a wildcard; unsupported field types decline.
Tag-only patterns remain legal, and payload offsets account for common fields.
The new native packed-pattern gate passes Stage0/Stage1 at O0/O2, including
matching and mismatching literals, wrong tags, and both empty alternatives.
The quantified-range contract gate passes. The final native suite passes
563/563 checks. Bootstrap passes stage A (5/5 blocker controls), stage B
(gen2 compiled the complete compiler), and stage C (gen3.o equals gen4.o
byte-for-byte). All local branch tips are ancestors of the integration tip.
Primary main was fast-forwarded to the qualified tree. All redundant local
worktrees and branches were removed; only the primary main checkout remains.
Detached tip 2dc1b770 was patch-equivalent (git cherry reported only minus),
and all other removed tips were incorporated by ancestry. Local non-source
files were archived before removal; generated worktree products are rebuildable.

Recovery: primary .git/selfhost-integration-recovery-20261004.bundle was
verified. Primary .git/cleanup-recovery-20261004.qwXoEe stores inventory and
tar backups of local Finder metadata, .zp probes, an old seed log, and a
broken temporary symlink. Refresh the bundle with final integration history
before deletion. A second verified bundle, selfhost-integration-final-20261004.bundle,
preserves the backend repairs. The verified qualified bundle
selfhost-integration-qualified-20261004.bundle includes the passing-gate
documentation and every pre-deletion ref. Remote branches remain untouched.
