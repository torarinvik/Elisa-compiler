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

Zero-result jobs skip allocation and indexing. Zero-length text becomes an empty
view. Nonempty text is copied by its exact byte count, preserving embedded NULs.
The serial path remains the existing ordered pass runner.

`scripts/semantic_parallel_diagnostic_audit.py` checks both constructors against the
actual Diagnostic declaration, checks every textual field's backing/copy mapping,
and verifies every other field is preserved. Adding a defaulted field without
updating either transfer fails the audit.

## Evidence and remaining qualification

Only small probes have been built so far. **This is not yet evidence that the full
parallel compiler works or is faster.** Full seed/gen2, determinism, semantic gates,
corpus differential checks and quiet timing remain for parent coordination.

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
changed, no full compiler seed was started, and no timed benchmark was run.
