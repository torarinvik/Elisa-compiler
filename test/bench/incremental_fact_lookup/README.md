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

The paired runner is exploratory and macOS-only. Before starting the compiler-heavy
correctness preflight, it uses the shared benchmark load gate and requires
`load1 / logical_CPU <= 0.20`. Use `cross_language.sh` for qualified Linux timing. A closed
gate writes `ABORTED.txt` without launching the preflight builds. The runner also holds the
shared cross-language benchmark lock, so compiler timing suites cannot overlap on the host.
After correctness preflight, the load gate must remain under the same limit for 60 consecutive
seconds before the first timed pair. A high sample or a polling gap over 1.5 seconds resets the
window; if it does not pass within 15 minutes, the run aborts before timing. Passing admission
does not authorize timing. Before any timed pair, the runner still uses
isolated cache directories to verify exact parent/candidate
stdout and diagnostics for both the original-source priming compile and the body edit,
along with reuse reports and prior snapshot hashes for every workload. It then alternates arm
order, primes each product on the original source, and times the body edit at the same absolute
path. It measures the complete `-emit check` process, including index
construction, cache loading, current-source validation and publication. Separate cache
directories prevent cross-product writes.

Each pair must have identical prior snapshot bytes, diagnostics and reuse counts.
Product/provenance/LLVM/source/corpus and benchmark-harness hashes are checked before timing,
after correctness preflight, and after all pairs. The load gate runs before and after each
preflight compile, then before and after priming and timed samples; a failure writes
`ABORTED.txt`. Raw samples include CPU time and host load. Saved prior
snapshots allow admission inputs to be inspected afterward. `COMPLETE` marks a fully written
summary; unexpected exits write `ABORTED.txt` when possible. The runner uses the newest
installed Homebrew LLVM and does not invoke `brew update`.

The small and low-query cases expose index construction overhead. Dense cases use supported scalar-returning helpers; low-query cases keep only one supported helper among generic declarations. Results from a shared Mac are exploratory and do not qualify Linux performance or comparisons with other languages.
