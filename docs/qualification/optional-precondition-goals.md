# Optional parameter precondition goals

Production candidate: `af345ae4d12f689ac7a543a05031f8bdb03c010c`.
The native probe retains the predecessor tuple helper and collector only in test
code. Production continues to use the optional helper and scoped first-law lookup.

The probe covers plain annotations, non-`is` binary annotations, unnamed law
applications, missing laws, empty law tables, non-binary predicates, non-self
left operands, non-comparison operators, non-literal right operands, positive
and negative signed literals, and duplicate names selecting the first law.
Accepted predicates must retain their exact AST handle. The old and new
collectors must agree on all nine output arrays, including owner, parameter,
goal and self-index ordering. A real call-checker comparison requires a nonempty
diagnostic result and compares every Diagnostic field, including all six source
position fields.

Allocation observation reads the live packed store's node count synchronously
through a test-only C helper. It neither allocates nor changes the runtime, and
retains no pointers. C ABI assertions and runtime checks require a 96-byte
PackedAoSStore, 24-byte store carrier, matching record size and 256-record chunks.
Each candidate helper case must allocate zero AST nodes. Predecessor misses
allocate one or two; the mixed five-parameter collector allocates four in the
predecessor and zero in the candidate.

Run `test/parity/cpu_optional_goal_native.sh` on Linux with explicit
`ELISA_CPU_PROBE_PRODUCER`, `ELISA_CPU_PROBE_HOOKS`, `ELISA_CORE`, and an isolated
`ELISA_CPU_PROBE_OUTPUT`. It uses the canonical host flock, a 12 GiB RSS guard,
one backend worker, O0/O2, source-provided runtime and strict hooks-only native
linking. Complete external runtime objects and unresolved/duplicate symbol
suppression are not used. This is a correctness/allocation oracle, not a timing
or parallel eligibility claim.

## Qualified native result

Both O0 and O2 compiled, linked with `--no-undefined`, and returned zero on Vast.
Durable evidence: `/root/work/codex-optional-precondition-goals/qualification/native3`.
The source was the isolated `9c7ae0a4` checkout with the exact `af345ae4`
production-file overlay (SHA256
`ae34485d57241a5314348dd58a5fc096c9e15e2a67c5d2be5dd6e103dc967da5`).
Content manifests record the overlay independently of the base Git reference.

Producer: clean Core0088, SHA256
`03c38620346f328be448fc55defd825f49723bb58af47e5b516414e1d5b40995`.
Fallback hooks: SHA256
`40a603708173ce2c8565a90ead32d76041e46504e243105844b2c6e7e1c1746b`.
Executable SHA256s:

- O0: `2b317f70fbfd29e9e14e4082a9546935b513c2ca7b7f907fe45d63abf56d938e`
- O2: `3d311e4c024a99d278905bd634ed46637f9572996fa0e8d04cf0bad46627bafe`

Observed compiler peak RSS was 5,463,084 KiB at O0 and 5,718,472 KiB at O2.
Two earlier test-harness builds were retained: a constructor outside an active
store scope, then an Expr-store versus unified Node-store carrier mismatch.
The passing harness creates the canonical Node store in the constructing
function and leaves production store/helper code unchanged.
