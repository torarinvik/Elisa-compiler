# Build-speed notes (branch build-speed, base 2678ff10)

## Profile: stage1 compiling src/driver/elisac.elisa
elisa-profiler `--mode sample` (2 ms period, 61,885 samples) on the Mac. Shares are of all samples.

| Phase | Share |
|---|---|
| Semantic gate (`check_full_into`) | 46% |
| ...check_region_storage_stability | 17.6% (param_growth_rows 9.6%, of which pgs_callee_fields 7.6%) |
| ...resolve_declarations | 4.7% |
| IR generation (`emit_module_core`) | 39% (bodies 24%, declare_module_functions 6%, register_region_abi_facts 5.7%) |
| ...annotation_value_type / enum_scope_path_rank | 9.7% / 5.4% |
| Parse | 7.2% (record_generic_func_metadata 2.2%) |
| Lex | 2% |
| LLVM object emission (O0) | 4% |

Notes:
- `-emit ast` and `-emit progress` are themselves pathologically slow (300-600 s), much slower than a full obj build. Don't use them as phase probes. They're also a separate bug worth fixing.
- vast/Linux timings were dominated by box contention. Measure retired instructions instead (`/usr/bin/time -l` on macOS).
- On vast, gdb/ptrace is blocked. The O3 seed has only private symbols, so PC sampling can't be symbolized there.

## Results (gen2 = O0 product built by the studio-globals stage1, compiling elisac.elisa)
| Build | Retired instructions | Object sha |
|---|---|---|
| base + parallel emission (serial run) | 1539.3 G | a143b99d277f |
| + pgs index | 1370.2 G (-11.0%) | same |
| + owner dedup | 1297.9 G (-5.3%) | same |
| + generic-metadata scan fix | 1222.0 G (-5.8%) | same |

Cumulative: -20.6% instructions, with byte-identical output.
- Parallel emission, `ELISA_STAGE1_JOBS=6`: 109 s -> 84 s wall (noisy Mac). Codegen is only ~4% of the profile, so the gain is bounded.
- gen2->gen3 fixpoint holds for both serial and 6-job objects (cmp identical).
- The object cache's hit cost is about 0.1 s.

## Next steps
- Re-profile: the flat tail includes check_region_storage_stability_declarations (7%), region_apply_forwarding_declarations, declare_function and arena_realloc.
- Fix the slow `-emit ast` / `-emit progress` reports.
- Run the parity smokes and a full gen3 fixpoint on the final tip. They were not run in this session.
- Measure mocap-cleaner studio.
- Consider making parallel emission the default in self_host_gen2.sh (with `ld -r`).
