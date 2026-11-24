# LLVM passes written in Elisa

Stage1 runs its own LLVM IR passes after LLVM's pipeline, on the target-machine output path.
They are being moved from C++ into Elisa. A pass written in Elisa calls the LLVM C API
directly. Where LLVM has no C entry point for something a pass needs, a small C shim provides
one.

## Layout

| Directory | What it holds |
|---|---|
| `src/backend/llvm_c_api/` | The C shims. Each area has a header (`.h`), a C++ file (`.cpp`) that wraps the LLVM C++ API in `extern "C"` functions, and the Elisa `extern` declarations (`.elisa`). `elisa_llvm_analysis` covers dominator trees and edge dominance, loops, scalar evolution (constant maximum backedge-taken counts, unsigned range maxima), value-tracking facts (including implied conditions and context-sensitive poison checks), lazy value ranges, PatternMatch constant tests (`m_One`, `m_Zero`, `m_SpecificInt`, which also accept splat vectors), constant-integer bit queries (`isMask` width, agreement in the low bits, trailing zeros, the odd part, `getLowBitsSet` constants, unsigned comparison), instruction memory queries (`mayHaveSideEffects`, `mayReadOrWriteMemory`), `stripPointerCasts`, target-triple queries (`isAArch64`, `isMacOSX`) on a module or a target machine, and subtarget feature checks (`checkFeatures`). `elisa_llvm_constant_range` exposes `llvm::ConstantRange` as an opaque handle: the range a compare allows, subtraction, membership, and signed- and unsigned-maximum queries. `elisa_llvm_ir_edits` covers IR edits the C API lacks, such as phi incoming blocks, dead-block deletion, unreachable-block removal, function cloning, call inlining and compare predicates. |
| `src/backend/llvm_passes/` | The standalone passes. `llvm_passes.elisa` includes every pass. `llvm_pass_registry.elisa` maps a pass name to its entry point. |
| `src/backend/llvm_passes/ir/` | The shared IR helpers. `ir_editing.elisa`, `llvm_ir_queries.elisa` and `llvm_ir_constants.elisa` hold the editing helpers, IR queries and the LLVM 23 enum values (for example, `br` is now opcode 70 unconditional and 71 conditional). `loop_pass_policy.elisa` decides which functions a pass skips. |
| `src/backend/llvm_passes/late_cleanup/` | The late scalar cleanup (`late_scalar_cleanup.elisa`) and the folds it runs, one file each. |
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
`ring-index-bounds`, `halving-runs`, `factored-divisions`, `shift-parity-loops`,
`masked-split-multiplies`, `trap-exit-edges`, `shared-divisibility`,
`guarded-counter-bounds`, `bounded-quotient-sums`, `literal-divisors` (uses the target
machine when given a CPU), `guarded-unsigned-compares`, `vector-or-accumulators`,
`exit-dead-stores` (on any target; the pipeline runs it on AArch64),
`nested-vector-loops` (prints 1 when the late cleanup would rerun O3 for the module),
`cssc-range-checks` (needs a CPU; without one it changes nothing).

The pass tests in `test/llvm/` and `test/parity/validation_layout_smoke.py` drive the passes
through this command, using `test/llvm/elisa_llvm_pass.py`
(`run_pass(name, ir) -> (count, module)`, or `run_pass_with_target(name, ir, cpu, features)`).
They run `$ELISAC`, or `bin/elisac-stage1` when it is unset.

## Porting a pass

1. Port the C++ pass to a file in `src/backend/llvm_passes/` (or `late_cleanup/` for a late
   cleanup fold) and call it where the C++ entry
   point was called. Delete the C++ file and its includes, macro entries and externs.
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
