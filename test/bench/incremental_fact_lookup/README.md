# Warm incremental fact lookup benchmark

This measures opt-in semantic-cache reuse after one function-body edit. It does not measure cold compilation, object emission, linking, or generated-program runtime.

Generate the source-only corpus:

```sh
python3 test/bench/incremental_fact_lookup/generate.py /absolute/corpus --low-query
```

Run only after the candidate passes `test/parity/incremental_prior_key_index_gate.sh` and the compiler lane is available:

```sh
python3 test/bench/incremental_fact_lookup/paired.py PARENT_ROOT PARENT_BIN CANDIDATE_ROOT CANDIDATE_BIN /absolute/corpus /absolute/results --pairs 7
```

The Mac runner alternates arm order, primes each product on the original source, then times the body edit at the same absolute path. It measures the complete `-emit check` process, including index construction, cache loading, current-source validation and publication. Separate cache directories prevent cross-product writes.

Each pair must have identical prior snapshot bytes, diagnostics and reuse counts. Product/provenance/LLVM/source/corpus hashes must remain unchanged. Raw samples include CPU time and host load. Saved prior snapshots allow admission inputs to be inspected afterward.

The small and low-query cases expose index construction overhead. Dense cases use supported scalar-returning helpers; low-query cases keep only one supported helper among generic declarations. Results from a shared Mac are exploratory and do not qualify Linux performance or comparisons with other languages.
