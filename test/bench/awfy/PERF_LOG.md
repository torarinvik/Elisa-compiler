# AWFY codegen perf log

The AWFY sources live on the agent-a88735ec88f86f10a worktree (test/bench/awfy). Builds use
stage0 `-emit obj -O3` (`-fstrict-fp` for NBody/Mandelbrot), linked against the
profiler-hook fallbacks. The host load average was 30-60, so wall time is unreliable.
The numbers below are **instructions retired / cycles in millions** from `/usr/bin/time -l`,
best cycles of 3 runs, with 3 outer iterations at the run_compare.sh inner counts. Every
Elisa port verifies its own result, and all of them exited 0 before and after.

## 2026-10-13: stage0 dae70ca7 + 3014fc1d (branch claude/codegen-perf-20261013, Elisa-core)

### What changed
1. **scev-aa in the optimisation AA stack** (`optimizationAAPipeline` in
   backend/llvm_target.go plus parallel_emit.c). This is LLVM's default stack plus scev-aa. In
   NBody's `for j in i+1..<n` loop, BasicAA could not prove that `bodies[j]` stores leave
   `bodies[i]` alone. So `bodies[i].vx/vy/vz` were reloaded and re-stored on every j iteration,
   which put a store-forwarding chain on the critical path. Rust avoids this through
   `split_at_mut` noalias. scev-aa proves the two addresses disjoint once trip counts are
   known, and LICM then keeps the i fields in registers.
   Cost: the stage1 self-compile went from 136.6 s to 139.0 s user time (+1.8%).
   Limitation: for a non-inlined kernel with a runtime `n`, the element GEP has no
   `inbounds`, because only proven indices get it (`TestUnprovenIndexDoesNotEmitInboundsGEP`).
   The SCEV addrecs then have no no-wrap flags, and scev-aa cannot prove disjointness.
2. **hdr/elt alias scopes widened.**
   - The bounds-guard *count* load is now tagged `hdr`, like the data-pointer load. Before,
     the bound was reloaded after every element store.
   - Element types that get `elt` tags now include bool, const enums, plain structs, and
     non-packed enums built only from those. Before, only numeric types qualified.
   - Field addresses derived from an alias-safe element address inherit the tag.
   - Soundness argument: an element buffer of such a type never holds a darray or view
     header. A struct that contains a darray stays untagged, and a test checks this.

### Before -> after (Minstr / Mcycles)
| bench     | stage0 main   | this branch   | Rust       | Zig        |
|-----------|---------------|---------------|------------|------------|
| NBody     | 332 / 121     | 305 / 94-102  | 255 / 73   | 321 / 105  |
| Richards  | 2188 / 517    | 1878 / 456    | 1708 / 450 | 813 / 225  |
| Queens    | 625 / 122     | 557 / 119     | 396 / 75   | 321 / 76   |
| Towers    | 1150 / 159    | 975 / 155     | 626 / 130  | 451 / 108  |
| Permute   | 740 / 145     | 579 / 108     | 775 / 161  | 383 / 100  |
| List      | 1419 / 236    | 1419 / ~214   | 757 / 159  | 748 / 163  |
| Json      | 1672 / 268    | 1674 / ~270   | 973 / 155  | 2295 / 335 |
| others    | unchanged within noise (CD -2.5%, Havlak -0.7% instr) |

NBody wall time, best of 3x5 at load ~40: 17.7 ms -> 12.6-13.0 ms per iteration
(Rust 9.4 ms, Zig 14.3 ms).

### stage1 mirror
- The AA pipeline is mirrored in src/backend/codegen_target_machine.elisa `run_optimization`,
  with a new extern `LLVMPassBuilderOptionsSetAAPipeline` in llvm_c.elisa. This is
  **untested in stage1**: stage1 is currently unseedable.
- The hdr/elt widening is **not mirrored**. Stage1 has no darray hdr/elt alias-scope
  mechanism at all; it only has per-parameter disjoint scopes. Porting the base mechanism is
  a separate task.

### Open leads (not done)
- Queens and List: the remaining gap is header reloads after calls and bounds checks on the
  index-arena representation. Rust keeps the Vec headers in registers across the recursive
  call because `&mut self` is noalias. Elisa's opt-in `-fnoalias` (ELISACORE_NOALIAS_MUTABLE_REFS)
  is the related mechanism.
- Allowing `inbounds` on guarded (not only proven) element GEPs would let scev-aa work in
  non-inlined kernels. That conflicts with the current design rule in
  TestUnprovenIndexDoesNotEmitInboundsGEP, so it needs an owner decision.
