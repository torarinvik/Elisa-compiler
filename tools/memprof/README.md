# memprof: allocation evidence from an optimized build

The arena runtime calls `elisa_profile_allocation_event_v1` on every allocation, region
create/reset/free and arena adopt (`elisacore_std/profiler_hooks.elisa`). Ordinary links
resolve those to weak no-ops. `elisa_memprof.c` provides strong definitions, so linking it
into an existing object profiles **that exact build**, `-O3` seed included, with no
re-instrumentation. That matters for RSS and syscall work, where an `-O0 -ftrace` build
distorts the very thing being measured.

```sh
source your toolchain env   # Linux: PATH=$PWD/tools/linux_shim:$PATH LLVM_CONFIG=...
tools/memprof/link.sh                      # build/elisac_stage1.o -> build/memprof/elisac-stage1-memprof
ELISA_MEMPROF_OUT=/tmp/p.txt ELISA_MEMPROF_RATE=1048576 \
  ELISA_STAGE1_RUNTIME_STD=1 build/memprof/elisac-stage1-memprof -emit obj -o /tmp/x.o some.elisa
grep -E '^(SUMMARY|H |R )' /tmp/p.txt     # totals, region-size histogram, RSS checkpoints
python3 tools/memprof/analyze.py build/memprof/elisac-stage1-memprof /tmp/p.txt [--live]
```

What you get without any stacks:

* `SUMMARY`: bytes allocated / moved by darray growth / grown in place, region creates and
  frees, resets.
* `H 2^k N regions M MB`: regions handed to arenas, by size class. This counts region-cache hits too; use strace to count real mmaps. This is how the 256 MiB
  reserve_commit churn was found: 23.7k reservations to compile just the runtime.
* `R t=… rss_mb=…`: an RSS checkpoint every +64 MiB, which gives the growth timeline.
* `ADOPT …`: arena adopts and the parent chain lengths they walk.

Stacks (`analyze.py`, symbolized with `llvm-symbolizer`) need a target that can be unwound.
The stage0-built seed has no unwind tables, so `backtrace(3)` stops in the hook. Build the
target with frame pointers (stage1: `ELISA_STAGE1_KEEP_FRAME_POINTER=1`) and set
`ELISA_MEMPROF_FP=1`. `--live` keeps only the samples whose arena was still alive at the RSS
peak, which attributes the peak rather than total traffic.

Count syscalls with `strace -f -c -e trace=mmap,munmap`. Run the compiler directly rather
than through `scripts/elisac_stage1.sh` when measuring, so the wrapper's processes are not
counted.
