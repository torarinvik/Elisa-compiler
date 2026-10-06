# Remote gate hosts

Run stage1 gates on rented Linux boxes from the Mac. Everything a box needs is in this
directory, so a lost scratchpad or a dead box costs one command to rebuild.

    cp tools/remote/hosts.local.sample tools/remote/hosts.local   # then edit: alias port user@host
    tools/remote/setup_host.sh vast4                              # toolchain, idempotent (~1 min)
    tools/remote/remote_gate.sh --host vast4 <rev> gen3 diag internal escape backend
    tools/remote/hosts_status.sh                                  # load / disk / runs per host

| file | role |
|---|---|
| `setup_host.sh` | LLVM 21 (apt.llvm.org), z3 5.1.0 release binary, Go 1.27.1, the clang shim |
| `remote_gate.sh` | ships committed trees (`git archive`), builds stage0 per rev, seeds per (s1, s0, opt), runs gates in parallel, prints a summary |
| `gate_body.sh` | the host half of `remote_gate.sh` (shipped on every run) |
| `host_invalid.txt` | `<gate> <row>` rows the host cannot honour: reported SKIP-HOST, not FAIL |
| `hosts.sh`, `hosts.local(.sample)` | host registry; `hosts.local` is gitignored because addresses are ephemeral |
| `hosts_status.sh` | quick health of every host |

The differential fuzzers that use the same host layout are in `tools/fuzz/`: `fuzz.py`
mutates fixtures (verdict oracle); `gen_progs.py` + `difffuzz.py` generate VALID programs and
compare the RUNTIME output of both compilers' products (`diffmin.py` minimizes a finding,
`cmp.sh` probes one file by hand).

## Rules the scripts encode

- **Shared boxes.** Everything lives in `/root/elisa` (`bin/` with the shim, z3 and
  llvm-config; `go/`; `src/s0-<rev>`, `src/s1-<rev>`; `seed/<s1>-<s0><opt>`; `runs/<id>`;
  `cache/`). Nothing touches `/usr/local/bin`, the default `clang`, update-alternatives or a
  global PATH; our toolchain is on PATH only inside our scripts.
- **z3 >= 5.** apt's 4.8.12 makes contract-bearing compiles ~25x slower; the gate refuses it.
- **Linux host flags.** `ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1`, `ulimit -s unlimited`.
- **Committed trees only.** `--s1-repo` may be any worktree (they share the object db);
  uncommitted edits are never shipped, so a verdict always names a hash.
- **Parallel gates.** Each gate runs in its own copy of the seeded tree; the core budget
  is the host's free cores at dispatch (`nproc - loadavg`), split across gates and passed as
  `ELISA_JOBS`, `ELISA_INTERNAL_JOBS`, ... A run is detached on the host; if the ssh session
  drops, `remote_gate.sh --host H --attach <run-id>` re-attaches.
- **Gate aliases.** gen3, diag, internal (baseline from `test/fixtures/semantic_internal.baseline`),
  escape, backend. Any other name runs `test/parity/<name>.sh`.
- **Host-invalid rows.** `backend_native_smoke s1ir_module_triple` expects arm64.
  stage0's own native products segfault on Linux (exit 139): rows saying `stage0 exit=139`
  are the oracle's problem, not stage1's.
