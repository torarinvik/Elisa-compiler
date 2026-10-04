# Self-hosted compiler consolidation status — 2026-10-04

Integration branch: `codex/selfhost-main-integration`. Primary main remains at
`dfaeb45c` until combined acceptance and bootstrap closure pass.

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
gate must finish after the last harness repair.

Driver acceptance: bare passes at 5 disagreements (limit 6); with-std fails at
8 (limit 0). Do not loosen this ratchet to conceal integration gaps.
Disagreements needing resolution:

- global_storage_return.neg: Stage0 rejects, Stage1 accepts.
- local_view_escape_view_call.pos: Stage0 accepts, Stage1 rejects.
- named_states_without_derive.pos: Stage0 accepts, Stage1 rejects.
- new_region_owner_resolved.neg: Stage0 rejects, Stage1 accepts.
- reference_authority_forge.pos: Stage0 rejects, Stage1 accepts.
- reference_authority_upgrade_reborrow.pos: Stage0 rejects, Stage1 accepts.
- reference_authority_upgrade_value.pos: Stage0 rejects, Stage1 accepts.
- storage_dependency_owned_return_global.neg: Stage0 accepts, Stage1 rejects.

The authority accept gaps come from the compilation-unit-wide runtime_std
exemption in check_pointer_erasure_cast; runtime inclusion must not exempt
user code. Fix without disabling safety or relying on spelling-only trust.
Other disagreements need individual diagnosis, not blanket exclusions.

Still required: driver parity repair, complete zeroed safety verification,
backend differential coverage, and self_host_gen3 byte-identical fixpoint.
Only then advance primary main and remove other local branches/worktrees.

Recovery: primary .git/selfhost-integration-recovery-20261004.bundle was
verified. Primary .git/cleanup-recovery-20261004.qwXoEe stores inventory and
tar backups of local Finder metadata, .zp probes, an old seed log, and a
broken temporary symlink. Refresh the bundle with final integration history
before deletion. No branches or worktrees have been deleted yet; remote
branches must remain untouched.
