# Warm incremental fact lookup benchmark

This measures opt-in semantic-cache reuse after one function-body edit. It does not measure cold compilation, object emission, linking, or generated-program runtime.

Generate the source-only corpus:

```sh
python3 test/bench/incremental_fact_lookup/generate.py /absolute/corpus --low-query
```

Add `--dense-calls` to include chains with one direct call per helper after the
leaf, plus a call from `main` to the last helper. These cases expose call-target
lookup costs that the ordinary corpus, with only one direct call, cannot show.
The edit changes only the leaf's returned literal. Unchanged callers contain
direct facts and therefore remain on the cold Global-authority body-walk path;
do not report their matched records as skipped checker work.

Run only after the candidate passes `test/parity/incremental_prior_key_index_gate.sh` and the compiler lane is available:

```sh
python3 test/bench/incremental_fact_lookup/paired.py PARENT_ROOT PARENT_BIN CANDIDATE_ROOT CANDIDATE_BIN /absolute/corpus /absolute/results --pairs 7
```

Before starting the compiler-heavy correctness preflight, the Mac runner checks
`load1 / logical_CPU <= 0.20`; a closed gate writes `ABORTED.txt` without launching the
preflight builds. Passing this admission check does not authorize timing. Before any timed
pair, the runner still uses isolated cache directories to verify exact parent/candidate
stdout and diagnostics for both the original-source priming compile and the body edit,
along with reuse reports and prior snapshot hashes for every workload. It then alternates arm
order, primes each product on the original source, and times the body edit at the same absolute
path. It measures the complete `-emit check` process, including index
construction, cache loading, current-source validation and publication. Separate cache
directories prevent cross-product writes.

Each pair must have identical prior snapshot bytes, diagnostics and reuse counts.
Product/provenance/LLVM/source/corpus hashes are checked before timing, after correctness
preflight, and after all pairs. On macOS, timing proceeds only when `load1 / logical_CPU <=
0.20`; the runner checks after preflight and before and after priming and timed samples, and
marks failed runs `ABORTED.txt`. Raw samples include CPU time and host load. Saved prior
snapshots allow admission inputs to be inspected afterward. `COMPLETE` marks a fully written
summary; unexpected exits write `ABORTED.txt` when possible. The runner uses the newest
installed Homebrew LLVM and does not invoke `brew update`.

The small and low-query cases expose index construction overhead. Dense cases use supported scalar-returning helpers; low-query cases keep only one supported helper among generic declarations. Results from a shared Mac are exploratory and do not qualify Linux performance or comparisons with other languages.
