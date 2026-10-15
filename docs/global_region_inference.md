# Global region inference — design and measurement plan

Status: DESIGN, owner-agreed direction (2026-10-14). Nothing implemented.
Rule: **every piece must be justified by a measured cost before it is built.**

## Goal

1. Objects that die together share one arena, regardless of which function creates them.
2. Programmers rarely write lifetimes or copy values just to satisfy the checker
   (the Rust `'a` / `.clone()` friction), without weakening memory safety.

## What exists today (runtime, `elisacore_std/arena.elisa`)

Much of the "retain and reuse" half is already built:

| Mechanism | Today |
|---|---|
| Arena reuse | Region cache: up to 128 parked regions (`REGION_CACHE_MAX_ENTRIES`), probed on `new_region`. Added because 15.5% of -O2 compile CPU was mmap/munmap. |
| Large-object release | Regions above 1 MiB (`REGION_CACHE_MAX_SLOTS`) are not parked in the small cache; a separate reserve cache takes them only when barely used. Otherwise unmapped immediately. |
| Fresh-memory zeroing | Parking `memset`s the used bytes so reuse matches kernel-zeroed mmap. **This is a real cost on every park** — measure it. |
| Locking | One global cache lock (no-op on single-threaded targets). Not per-thread. |

So the immediate-free escape for very large objects already exists by size threshold.

## Proposed compiler side

- **Inference.** One region variable per allocation site. A store of X into Y, or a
  return of X to a caller that keeps it, adds "region(X) outlives region(Y)". Solve per
  strongly connected group of functions (recursion = region-polymorphic fixpoint, same
  machinery as today's store-mode summaries). Arenas are passed as hidden arguments, as
  region-polymorphic calls already do.
- **Module boundaries.** Infer freely inside a module; record inferred region signatures for
  public functions in `.elisair`, so a body change cannot silently break other modules.
- **Diagnostics.** Every rejection must print the chain ("stored here → forces it to outlive
  that"). Non-local errors without the chain are worse than Rust's.
- **Subsumes:** ambient adoption, destination-driven allocation, most store-escape false
  positives (e.g. snapshot copies in `bam_replay_flow_*`), and reduces the need for the
  scoped mark/restore rule.
- **Does not subsume:** aliasing/exclusivity (affine moves, call-argument exclusivity still
  force some copies), and views with unknown provenance (the AST sview question).

## Escape hatch: `eager` (name not final)

On a binding or allocation site, not primarily on the type. Meaning: put this value in the
shortest provable region and never widen it; if a store forces a longer lifetime, that is a
compile error naming the store. It is a placement constraint only — it cannot create a
use-after-free. Runtime: own region / own mapping, released (or `MADV_FREE`d) at end of life.
Only for cases the size threshold and automatic splits don't cover.

## Candidate runtime additions — build ONLY if measured

| Piece | Build only if… |
|---|---|
| Cap + decay on retained memory | long-running processes (LSP) hold peak memory measurably |
| `MADV_FREE` / `MADV_DONTNEED` instead of munmap | large-region churn shows up in profiles |
| Per-thread caches | lock contention appears in a parallel profile |
| Skip the park-time `memset` | zeroing cost is significant AND no code path relies on zeroed fresh memory |
| Automatic region splits at loop boundaries | merged regions grow unboundedly in the analysis report |
| `eager` keyword | a real program keeps a high peak that the above don't fix |

## Plan

1. **Analysis only.** Compute inferred regions per SCC; emit a report: which allocation
   sites merge, merged-region sizes, and how many current store-escape errors would vanish.
   No allocation change.
2. **Profile** the self-host compile, benchmarks and LSP: time in mmap/munmap, park `memset`,
   cache lock, and peak RSS.
3. **Decide** from 1 and 2 which pieces pay; build those only.
4. **Switch allocation** to inferred regions behind a flag; differential + gates; then default.
