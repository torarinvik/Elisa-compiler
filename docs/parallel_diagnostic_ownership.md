# Parallel diagnostic ownership qualification

The round-8 worker allocated diagnostics in its inferred frame region, despite an
`in scratch` block. Moving the scratch Arena into the job did not preserve those
allocations. The splice therefore read storage freed when the worker returned.

The worker now allocates the result record array explicitly with
`arena_alloc(&job.arena, ...)`, copies its records, and clones each of the 17 sview
payloads into the same arena before returning. Complete Diagnostic constructors
preserve all 10 other fields, including source positions, kind and numeric context.
The public darray fields provide the result descriptor; there is no guessed struct
layout or reinterpretation of an unrelated carrier type.

After joining, the runner validates **every** worker snapshot against the unchanged
parent table before copying any result. It then copies results in pass order. Each
text payload gets a separate caller-region byte buffer, held in the defaulted
SymbolTable.parallel_diagnostic_text field. An explicit region-polymorphic helper
allocates those buffers in the caller's region. Their descriptors may move when the
outer array grows, but their bytes never grow after insertion. The internal pointer
boundary in par_pass_parent_view relies on precisely that invariant. This avoids
the existing text_storage buffer's fixed 65536-byte capacity and relocation hazards.
Each job arena is explicitly freed after its last diagnostic is copied.
The parent copy receives a scalar address into the still-live job record, reads it
through an internal heap Diagnostic reference, and finishes cloning before freeing
the job. This avoids conservatively treating a temporary Diagnostic value as an
escaping local reference. SymbolTable retains its ordinary constructor: zeroed
initialization is invalid because some of its fields require live sview backing.

Zero-result jobs skip allocation and indexing. Zero-length text becomes an empty
view. Nonempty text is copied by its exact byte count, preserving embedded NULs.
The serial path remains the existing ordered pass runner.

`scripts/semantic_parallel_diagnostic_audit.py` checks all three constructors against the
actual Diagnostic declaration, checks every textual field's backing/copy mapping,
and verifies every other field is preserved. Adding a defaulted field without
updating every transfer fails the audit.

## Evidence and remaining qualification

Checkpoint 4212814 built but crashed at the diagnostic export boundary. Updated
checkpoint 360133ca passed a fresh seed and the complete 860-case serial/parallel
full-check comparison below. This verifies the diagnostic ownership lane; gen2,
fixpoint/determinism, broader semantic gates/corpus and quiet timing remain for
parent integration. No performance gain is claimed.

Private remote directory: `/root/work/codex-parallel-diagnostics`.
Stage0 used read-only: `/root/work/r8-core/compiler/bin/elisac` at d965439b.
The successful final probe is `probe-immutable.elisa`, object `probe-immutable.o`,
executable `probe-immutable`, and compiler log `probe-immutable.log`.

The probe uses nine jobs and four workers: eight jobs produce 100 diagnostics each
and the ninth is empty. All 17 text fields contain the four bytes `65, 0, 66, 67`.
It verifies all text after worker return and job-arena destruction, a unique scalar
sequence for pass/record order, the total of 800 records, and zero arena-used bytes
after every job arena is freed. The final probe matches immutable Diagnostic text
fields and passed at O2 (exit 0). Earlier mutable-field probes passed at O0 and O2;
they are preliminary evidence only.

Reproduce from that private directory:

```sh
export PATH=/usr/lib/llvm-21/bin:$PATH
ulimit -s unlimited
/root/work/r8-core/compiler/bin/elisac -emit obj -O2 \
    -o probe-immutable.o probe-immutable.elisa
clang -fno-builtin -c -o hooks.o hooks.c
clang -no-pie -o probe-immutable probe-immutable.o hooks.o -lm -lpthread -ldl
./probe-immutable
python3 scripts/semantic_parallel_diagnostic_audit.py
```

The probe includes the runtime directly. Its private hooks.c was copied from
`/root/work/r8-probe/rt/hooks.c`; the existing shared hooks.o lacked newer callback
stub symbols, so it was rebuilt privately. No shared runtime object is linked or
changed. No timed benchmark was run.


## Diagnostic-only export boundary

Production qualification of checkpoint 4212814 found a main-thread SIGSEGV in
`run_semantic_gate+5676`: `cmpl $0x6e657241,(%rax)` dereferenced an unmapped
`diagnostic.name` while testing the runtime-carrier name `Arena`. All worker
threads had exited. `check_full_diagnostics` shallow-copied table-owned text into
its caller's output, then released the local table region before reporting.
Private trace: `parallel-self-gdb-detail.log`.

The export now clones all 17 text payloads into independent byte arrays explicitly
allocated in the caller output region `@r`. These allocations are reclaimed with
that region; their temporary array headers do not own a separate allocation
lifetime. Only scalar addresses cross the conservative frontend view-dependency
boundary, and each reconstructed view uses the exact validated source byte count.
All scalar fields are preserved. Filtering and diagnostic order are unchanged.
Both serial and parallel output use this boundary.

`probe-export.elisa` reproduces the worker, local table, and caller output ownership
layers. Its producing function returns after freeing every job arena and its local
table region; only then does main inspect every field in the 800 returned records.
The O2 build and run passed (exit 0), including embedded NUL bytes and an
additional record with all 17 text fields empty. Reproduce with
the commands above, substituting `probe-export` for `probe-immutable`.
Final complete-source stage0 semantic check passed (`export-sourcecheck-final.done`,
exit 0). Updated production qualification passed as recorded below.


## Production qualification of 360133ca

Exact source: `360133cad0ad943731ef3f55d854af9400651626`. Read-only stage0
binary SHA256: `d5db7f8450c14859c308c4d32a40eb064d58d25ed89347b202806f7164b20cc3`.
All 1448 tracked compiler/runtime source inputs matched the local d965439b
stage0 checkout (`core-source.sha256`, `core-source-check.log`, exit 0).
The remote stage0 snapshot has no Git metadata or embedded binary VCS revision;
source matching and this exact binary digest record that provenance limitation.

`seed-export.sh` called the standard seed wrapper directly with
`ELISA_STAGE1_JOBS=1`, `ELISA_STAGE1_SEED_OPT_LEVEL=-O2`,
`ELISA_S0_CACHE=0`, `ELISA_NO_LINUX_SHIM=1`, and the private source/core paths.
The wrapper owned `/tmp/elisac-stage1-global-seed.lock/pid` as PID 2259862;
its stage0 child was PID 2259900. Both completed and released the host lock.
`seed-export.done` is 0; the coherent runtime was freshly generated by this product.
Provenance passed before and after the comparison.

| Artifact | SHA256 |
|---|---|
| `bin/elisac-stage1` | `4584ed08b74d41a4bf8c6c0b93b3d1f150df9c6666d4a410ba255508a0bf01ca` |
| `build/runtime/elisacore_runtime.o` | `5ee85c03294bb6c2f2e2588aa805185ceabfcad5b30e8c0c69a52d0d54b22d9d` |
| `bin/elisac-stage1.strict` | `92d3fd9b763d1873fb10de67c3fb7bfa2cd3131931591cb29c38b43a907f5270` |

A strict relink of the fresh object with its generated canonical host hooks
succeeded without `--unresolved-symbols=ignore-all` (`strict-export-link.done`, 0):

```sh
/usr/lib/llvm-21/bin/clang -fno-builtin -no-pie -Wl,--gc-sections \
    -o bin/elisac-stage1.strict build/elisac_stage1.o \
    build/elisac_stage1_profile_hooks.tmp.2259862.c \
    -L/usr/lib/llvm-21/lib -lLLVM -Wl,-rpath,/usr/lib/llvm-21/lib
```

`qualify.py` (PID 2262048) ran the unchanged product twice per case with
`ELISA_SEMANTIC_SERIAL=1` and `=0`, host Linux/x86_64, one backend worker, and a
120-second timeout. It compared exit status and every stdout/stderr byte:

- Full compiler source selfcheck: both exit 0, empty stdout/stderr.
- Generated 256-overflow-diagnostic unit: both exit 1, exactly 256 located findings,
  byte-identical diagnostic output.
- All 858 diagnostic fixtures: byte-identical outcomes.

`qualify-export.done` is 0; `qualification-results/summary.json` records 860
comparisons with no mismatches or signal exits. Output from the earlier crashing
checkpoint is preserved in `qualification-crash-4212814`.

Integration requires the round-8 compiler foundations bb7c557f/0d4caf45 and stage0
store-capturing submit support d965439b, including coherent concurrency runtime and
canonical native hook generation. The three ownership commits are bd942d1e,
42128146 and 360133ca. Land stage0 support before stage1; this branch remains isolated.
The historical stricter eligibility audit attributed about 1.2 s of roughly 11.5 s
of checking to safe parallel passes. Even eliminating that entire slice would cap
check-only speedup near 1.12x before scheduling/copy overhead. The 62 passes blocked
by 167 placeholder AST allocations require separate sentinel work and a fresh
combined-source audit. No quiet timing was run for this branch.
