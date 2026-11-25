# LLVM passes written in Elisa

Stage1 runs its own LLVM IR passes after LLVM's pipeline, on the target-machine output path.
They are being moved from C++ into Elisa. A pass written in Elisa calls the LLVM C API
directly. Where LLVM has no C entry point for something a pass needs, a small C shim provides
one.

## Layout

| Directory | What it holds |
|---|---|
| `src/backend/llvm_c_api/` | The C shims. Each area has a header (`.h`), a C++ file (`.cpp`) that wraps the LLVM C++ API in `extern "C"` functions, and the Elisa `extern` declarations (`.elisa`). `elisa_llvm_analysis` covers dominator trees and edge dominance, loops, scalar evolution (constant maximum backedge-taken counts, small constant trip counts, unsigned range maxima, signed ranges), value-tracking facts (including implied conditions and context-sensitive poison checks, with or without the assumption cache), lazy value ranges (at an instruction, on an edge and at a use), dropping the value analyses so the next query rebuilds them, PatternMatch constant tests (`m_One`, `m_Zero`, `m_SpecificInt`, which also accept splat vectors), irreducible control flow (`containsIrreducibleCFG`), constant-integer bit queries and arithmetic (wrapping multiplication, signed less-than, `isMask` width, agreement in the low bits, trailing zeros, the odd part, `getLowBitsSet` constants, unsigned comparison), instruction memory queries (`mayHaveSideEffects`, `mayReadOrWriteMemory`), memset tests, metadata uses (`isUsedByMetadata`), the data layout's index width, `stripPointerCasts`, `getUnderlyingObject`, `GetPointerBaseWithConstantOffset`, alloca queries (`isStaticAlloca`, `isUsedWithInAlloca`, `isSwiftError`, `getAllocationSize` when fixed), the bytes of a wide integer constant, the bits and floating-point class of a constant (`APFloat::classify`), known floating-point class facts (`computeKnownFPClass`: never NaN, never infinite, never negative), whether a function's control flow has a cycle (`scc_iterator`), reachability from the entry, definitive global initializers (`hasDefinitiveInitializer`), the value inserted at an aggregate index (`FindInsertedValue`), library-function recognition (`TargetLibraryInfo::getLibFunc` and `has`), `CallBase::isNoBuiltin`, target-triple queries (`isAArch64`, `isOSDarwin`, `isOSLinux`, `isMacOSX`) on a module or a target machine, and subtarget feature checks (`checkFeatures`). `elisa_llvm_constant_range` exposes `llvm::ConstantRange` as an opaque handle: the range a compare allows or exactly satisfies, the full, single-value and two-bound ranges, copies, intersection, subtraction, integer binary operations (`binaryOp`), the fast signed product (`smul_fast`), membership, full, wrapped, single-element and nonnegative tests, signed-minimum comparisons, and signed and unsigned minimum and maximum queries as 64-bit values. `elisa_llvm_pass_pipelines` runs `buildPerModuleDefaultPipeline(O3)` as `PassBuilder` builds it, which `LLVMRunPasses` cannot (see the traps below). `elisa_llvm_ir_edits` covers IR edits the C API lacks, such as phi incoming blocks and entries, dead-block deletion, unreachable-block removal, block and edge splitting (`SplitBlock`, `SplitEdge`), function and block cloning through an opaque value map (`ValueToValueMapTy`, which can also drop a mapped argument from a cloned function) with `RemapInstruction` (optionally leaving module-level values alone), moving an instruction to a block's end or before another instruction, moving a cloned function's body back into the original, copying a function's attribute list to a call, `emitGEPOffset`, call inlining, compare predicates, distinct-node tests and named-metadata erasure. `elisa_llvm_loop_transforms` exposes LLVM's loop utilities over the same analyses handle: top-level and sub-loop iteration, loop-simplify form, `simplifyLoop`, `formLCSSA`, peeling, `UnrollLoop`, block splitting that keeps the dominator tree and loop info current, and `cloneLoopWithPreheader` with its remapping. `elisa_llvm_weak_values` holds lists of `WeakTrackingVH`, so a pass can collect instructions before rewrites that may erase some of them. `elisa_llvm_function_analyses.h` is the C++ object behind that handle, shared by both shim files. |
| `src/backend/llvm_passes/` | The standalone passes. `llvm_passes.elisa` includes every pass. `llvm_pass_registry.elisa` maps a pass name to its entry point. `float_constant_pool.elisa` loads the expensive double constants of small, acyclic AArch64 functions from a private table on cores that fuse literal loads. |
| `src/backend/llvm_passes/ir/` | The shared IR helpers. `trap_blocks.elisa` recognizes blocks that only trap; `scalar_loop_patterns.elisa` holds the operand and continue-test patterns of single-block loop folds. `ir_editing.elisa`, `llvm_ir_queries.elisa` and `llvm_ir_constants.elisa` hold the editing helpers, IR queries and the LLVM 23 enum values (for example, `br` is now opcode 70 unconditional and 71 conditional). `loop_pass_policy.elisa` decides which functions a pass skips. `pass_pipelines.elisa` runs a textual pass pipeline over a module or one function, with or without a target machine. |
| `src/backend/llvm_passes/covered_array_revisit/` | The covered-array revisit (a second O3 run over small modules) and the loop-divisor versioning it runs: `divisor_screening.elisa` decides which function and frozen divisor qualify, and `divisor_versioning.elisa` clones the suffix after it. |
| `src/backend/llvm_passes/checked_multiplies/` | The checked i64 multiply folds of the late cleanup: `checked_multiplies.elisa` versions unproven multiplies onto a slow path and drives the rest; `cursor_products.elisa`, `checked_squares.elisa` and `checked_powers.elisa` prove multiplies safe from cursor bounds, square limits and power trip counts; `checked_initializers.elisa` tries constant-trip initializers unrolled; `checked_results.elisa` holds what they share. |
| `src/backend/llvm_passes/small_fills/` | The small-fill expansion and the byte- and word-store merges it runs first. `linked_helpers.elisa` links a helper written in textual IR into the module and inlines it at each expanded site. |
| `src/backend/llvm_passes/late_cleanup/` | The late scalar cleanup (`late_scalar_cleanup.elisa`), the C++ entries it still calls (`late_cleanup_externs.elisa`), and the folds it runs, one file each, grouped by subject: `array_copies/` (copies between private arrays and `malloc` blocks elided when one block can stand for both, and zero fills a descending loop rewrites before an ascending loop reads), `bit_loops/` (loops computing a bit function: parity, bit reverse, common prefix, xor, powers and digit counts), `divisions/` (quotients, remainders and divisibility tests, remainders of bounded dividends reduced to one conditional subtraction, and divisions a predecessor or an enclosing loop already computed), `range_checks/` (checks proven by guards and recurrences, even-integer range tests, sign normalizations a range check makes masks, and paired signed-index validations folded into one unsigned check per index), `scalar_idioms/` (scalar loops and bit tricks with a closed form: carry additions, trailing-zero shift loops, unsigned threshold searches, bit spreads rounded to a power of two, nibble population sums, and the select guarding the trailing zeros of an odd value); `sqrt_domain_proofs.elisa` proves `sqrt` arguments never NaN or negative, `bounded_unswitch.elisa` versions small innermost loops on an invariant branch condition, `reverse_byte_folds.elisa` turns reverse polynomial reductions over stored byte prefixes into sums, `stack_view_helpers.elisa` inlines small helpers that take views over two stack arrays (or assumes the arrays' storage separate) so SROA can see the arrays, and `vector_loops/` (vectorized loops and their stores, and the ordered conversions of a small AArch64 module: eight i64 loads converted to double and summed in order become pair loads, one vector conversion and an ordered `llvm.vector.reduce.fadd`, and two loop counters step as one `<2 x i64>`). |
| `src/backend/llvm_*.cpp` | The C++ passes not yet ported. `scripts/build_stage1_llvm_bridge.sh` lists the sources it compiles. |

A shim exists only for something the C API cannot do. Before adding one, check
`src/backend/llvm_c.elisa` and the LLVM-C headers. For example, reading textual IR uses
`LLVMCreateMemoryBufferWithContentsOfFile` and `LLVMParseIRInContext`, not a shim. A C API that
returns a handle through a `void **` out-cell gives Elisa a raw `void&`. Under
`can Unsafe.PointerCast`, cast it to the handle type with `raw.cast[LLVMModuleRef]`.

## Running one pass

`elisac llvm-pass PASS INPUT.ll [CPU [FEATURES]]` parses a textual module, runs one
registered pass, and verifies the result. It prints the pass's change count on the first line
and the module after it. With CPU, a pass that takes a target machine gets one for the
module's triple with that CPU and FEATURES (for example `generic +cssc`); without it, such a
pass runs as it would with no target machine. Exit codes: 1 for a usage error or an unknown
pass, 2 for unreadable IR, 3 for invalid IR after the pass.

Registered names: `bit-tests`, `remainder-tests`, `remainder-tails`, `compact-shift-loops`,
`conditional-doubling`, `decimal-digit-counts`, `power-positions`, `validation-returns`,
`shared-reciprocals`, `guarded-increments`, `nonnegative-remainders`,
`masked-single-bits`, `interleaved-byte-stores`, `bounded-carries`, `implied-loop-exits`,
`ring-index-bounds`, `halving-runs`, `factored-divisions`, `remainder-recurrences`,
`shift-parity-loops`,
`masked-split-multiplies`, `trap-exit-edges`, `shared-divisibility`,
`guarded-counter-bounds`, `bounded-quotient-sums`, `literal-divisors` (uses the target
machine when given a CPU), `guarded-unsigned-compares`, `vector-or-accumulators`,
`exit-dead-stores` (on any target; the pipeline runs it on AArch64),
`nested-vector-loops` (prints 1 when the late cleanup would rerun O3 for the module),
`cssc-range-checks` (needs a CPU; without one it changes nothing), `small-fills`,
`guarded-reductions`, `divisor-versioning` (versions the first qualifying function),
`covered-array-revisit` (runs as if the reductions had been unrolled),
`early-division-pairs` (uses the target machine when given a CPU; prints 0 off AArch64),
`shift-bit-reverse-loops`, `range-and-loops`, `shift-xor-loops`, `short-trips` (uses the target
machine when given a CPU), `guarded-counters`, `validation-epilogues`,
`private-bool-arrays` (uses the target machine when given a CPU), `checked-multiplies` (uses
the target machine when given a CPU; prints 0 off AArch64), `float-constant-pool` (needs a CPU
that fuses literal loads, such as `apple-m1`, or the `+fuse-literals` feature; prints 0
without one), `sqrt-domain-proofs` (adds `nnan` to proven `sqrt` calls), `sqrt-domains`
(the proofs, then the cleanup that turns those calls into the intrinsic; uses the target
machine when given a CPU), `even-ranges` (prints 0 off AArch64 Linux and Darwin; rewrites
signed 16-bit scans only when the compiler itself runs on AArch64), `bounded-unswitch` (prints 0
off little-endian 64-bit AArch64), `signed-range-masks` (prints 0 off AArch64), `reverse-byte-reductions` (prints 0 off AArch64), `index-bounds` (the late cleanup runs it
only on Darwin AArch64, where it also aligns the function's small leaf loops), `edge-division-reuse` (prints 0 off AArch64), `scalar-loop-idioms` (prints 0 off AArch64), `odd-trailing-zero-selects` (prints 0 off AArch64), `stack-view-helpers` (prints 0 off AArch64 and for modules of more than 512 functions; 2 when a cleanup pipeline fails), `bounded-remainders` (prints 0 off AArch64), `array-round-trips` (promotes `memcpy` calls and alloca `memmove`s to `llvm.memcpy` without counting them; the target-machine path also runs it before O3), `ordered-casts` and `paired-counters` (count the functions they change), `ordered-conversions` (needs a CPU; prints 0 without one, for modules of more than one defined function or 2000 instructions, and off AArch64; 2 when the `instcombine` cleanup fails).

The pass tests in `test/llvm/` and `test/parity/validation_layout_smoke.py` drive the passes
through this command, using `test/llvm/elisa_llvm_pass.py`
(`run_pass(name, ir) -> (count, module)`, or `run_pass_with_target(name, ir, cpu, features)`).
They run `$ELISAC`, or `bin/elisac-stage1` when it is unset.

## Porting a pass

1. Port the C++ pass to a file in `src/backend/llvm_passes/` (or the matching `late_cleanup/`
   subfolder for a late cleanup fold) and call it where the C++ entry point was called. Delete the C++ file and its includes, macro entries and externs.
2. Register it in `llvm_pass_registry.elisa`.
3. Compare the C++ and Elisa outputs on the same inputs: the change count and the printed
   module must match exactly. Then check that the benchmark corpus objects are unchanged.

Porting traps seen so far:

- An array of optional extern handles (`darray[LLVMValueRef?]`) uses 16-byte tagged slots.
  Pass only non-optional pointer arrays to C.
- `LLVMPositionBuilderBefore` does not set the debug location that the C++ `IRBuilder` sets.
  Use `position_builder_before` in `ir/ir_editing.elisa`.
- An instruction the C++ creates directly (`UncondBrInst::Create(Target, Block)`) has no debug
  location, but a builder keeps the last one it was given. Clear it with
  `LLVMSetCurrentDebugLocation2(builder, null)` before building such an instruction.
- Not every `LLVMIsA*` class test is exported: libLLVM has no `LLVMIsACallBase`. Use
  `is_call_base` in `ir/ir_editing.elisa`, which tests the call, invoke and callbr opcodes.
- Match the C++ predicate exactly. For example, `Triple::isAArch64()` is not a prefix test on
  the triple string, so it is a shim.
- `LLVMGetMDNodeOperands` writes null for a null operand. Read operands into pointer-sized
  words, as `metadata_operand_words` in `covered_array_revisit/divisor_screening.elisa` does,
  so a null stays distinguishable.
- `LLVMRunPasses` with the text `default<O3>` does not run the pipeline that
  `PassBuilder::buildPerModuleDefaultPipeline(O3)` returns: on LLVM 23 the text form
  vectorized doitgen differently. A pass whose C++ built the pipeline calls
  `ElisaLLVMRunDefaultO3Pipeline` instead.
- `sview_to_cstr(text, storage)` appends to `storage` and returns its start. A second
  call on the same buffer returns the first string again, so give each name its own buffer
  (or `truncate(0)` it first).
- An `else` right after an index (`a[i] else …`) is the removed implicit index fallback, even
  inside a conditional expression such as `x if n == a[1] else y`. Bind the element first with
  `get a[1] else …`.
- Reserved keywords such as `packed`, `error`, `to`, `tail`, `stack`, `heap` and `match` cannot name a
  local or a parameter (the lexer's keyword table in `src/lexer/lexer_identifiers.elisa`).
- A string literal cannot span lines. Write a textual-IR helper as an array of lines, as
  `small_fills/stack_word_pattern_fills.elisa` does; `link_internal_helper` joins them.
