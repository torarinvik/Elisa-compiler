#!/usr/bin/env python3
"""Paired retained-session benchmark for the experimental semantic query graph.

This measures an in-memory semantic-session body-edit path. It is distinct from
incremental_fact_lookup/paired.py, which launches fresh compiler processes and
measures the durable disk-sidecar path. The graph remains opt-in in production.
"""

from __future__ import annotations

import argparse
import atexit
import ctypes
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import select
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

from session_workload import (
    digest_bytes,
    digest_file,
    fixture,
    normalized_transcript,
    report_fields,
    timing_rows,
    timing_arm_kinds,
    mode_environment,
    three_mode_order,
)
from session_measurements import (
    paired_timing_summary,
    paired_counter_summary,
    DarwinRusageInfoV4,
    DarwinTimebaseInfo,
    mach_ticks_to_ns,
    DarwinProcessCounters,
    memory_observation,
    find_stage1_pid,
    counter_delta,
    paired_counter_measurements,
    paired_mode_measurements,
)
from session_runner import (
    PipeLineReader,
    read_response,
    stop_process_group,
    run_arm,
)
from session_validation import (
    validate_pair,
    validate_direct_surface_pair,
)


ROOT = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(ROOT / "scripts"))
from bench_load_gate import (  # noqa: E402
    LoadGateError,
    check_load_gate,
    load_average,
    wait_for_sustained_load_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1", type=Path, default=ROOT / "bin/elisac-stage1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--functions", type=int, default=128)
    parser.add_argument("--body-edits", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument(
        "--include-direct-surface",
        action="store_true",
        help="add an opt-in graph-on NameLookup arm that classifies from the finalized resolver surface",
    )
    parser.add_argument(
        "--concurrent-instruction-counts",
        action="store_true",
        help="skip the host lock/load gate; use process counters while treating wall time as unqualified",
    )
    args = parser.parse_args()
    if args.pairs < 1 or args.functions < 4 or args.body_edits < 1 or args.timeout_seconds <= 0:
        parser.error("pairs/body-edits/timeout must be positive and functions must be at least 4")
    root = ROOT.resolve()
    stage1 = args.stage1.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error(f"output directory is not empty: {output}")
    run_state = {"complete": False}

    def mark_incomplete_run() -> None:
        if run_state["complete"] or (output / "COMPLETE").exists() or (output / "ABORTED.txt").exists():
            return
        try:
            (output / "ABORTED.txt").write_text(
                "ABORTED — paired graph benchmark exited before completing.\n"
                "Partial timings and measurements are unusable.\n",
                encoding="utf-8",
            )
        except OSError as error:
            print(f"could not write ABORTED.txt: {error}", file=sys.stderr)

    atexit.register(mark_incomplete_run)
    if platform.system() != "Darwin":
        parser.error("this exploratory paired runner is macOS-only; use the qualified cross-language runner on Linux")

    host_lock_path = Path(os.environ.get("ELISA_BENCH_LOCK_PATH") or "/tmp/elisa-cross-language-benchmark.lock")
    host_lock_fd: int | None = None
    if not args.concurrent_instruction_counts:
        host_lock_fd = os.open(host_lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(host_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(host_lock_fd)
            parser.error(f"another compiler benchmark holds the host lock at {host_lock_path}")

    if not stage1.is_file():
        parser.error(f"Stage1 product does not exist: {stage1}")
    provenance_checker = root / "scripts/stage1_provenance.py"
    subprocess.run(["python3", str(provenance_checker), "check-exact", str(root), str(stage1)], cwd=root, check=True)
    if not Path(str(stage1) + ".provenance.json").is_file():
        parser.error(f"Stage1 provenance is missing: {stage1}.provenance.json")

    system = platform.system()
    host_qualification = output / "host_qualification.json"
    host_qualification.write_text(
        json.dumps(
            {
                "system": system,
                "machine": platform.machine(),
                "qualified": False,
                "reason": (
                    "concurrent instruction-count mode; wall-time comparisons are unqualified"
                    if args.concurrent_instruction_counts
                    else "retained semantic graph paired timings are exploratory"
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if args.concurrent_instruction_counts:
        print("Concurrent instruction-count mode: host load and wall time are unqualified.", flush=True)
    else:
        try:
            check_load_gate(load_average(), "before retained-session graph benchmark", output, system, host_qualification, preflight=True)
            print("Waiting for the load gate to hold for 60 seconds before paired samples.", flush=True)
            wait_for_sustained_load_gate(output, system, host_qualification, stage="before first retained-session pair")
        except LoadGateError as error:
            raise SystemExit(str(error)) from error

    pinned_paths = [
        stage1,
        Path(str(stage1) + ".provenance.json"),
        Path(__file__).resolve(),
        root / "scripts/elisac_stage1.sh",
        root / "scripts/assert_stage1_fresh.sh",
        provenance_checker,
        root / "scripts/platform.sh",
        root / "scripts/process_rss.sh",
        root / "scripts/bench_load_gate.py",
    ]
    pins = {str(path.resolve()): digest_file(path.resolve()) for path in pinned_paths}
    metadata: dict[str, Any] = {
        "status": (
            "exploratory retained semantic-session graph-on/off plus direct-surface NameLookup benchmark; not disk-sidecar timing"
            if args.include_direct_surface
            else "exploratory retained semantic-session graph-on/off benchmark; not disk-sidecar timing"
        ),
        "platform": platform.platform(),
        "python": sys.version,
        "stage1_path": str(stage1),
        "stage1_sha256": digest_file(stage1),
        "stage1_provenance_sha256": digest_file(Path(str(stage1) + ".provenance.json")),
        "runner_sha256": digest_file(Path(__file__).resolve()),
        "direct_surface_arm_enabled": args.include_direct_surface,
        "mode_environment": {
            mode: mode_environment(mode)
            for mode in (
                ("graph-off", "graph-on", "direct-surface")
                if args.include_direct_surface
                else ("graph-off", "graph-on")
            )
        },
        "process_counter_method": "macOS proc_pid_rusage(RUSAGE_INFO_V4) sampled on the exact Stage1 compiler child PID; process-level retired instructions, cycles, and CPU time (not LLVM instruction attribution)",
        "pairs": args.pairs,
        "functions": args.functions,
        "body_edits_per_arm": args.body_edits,
        "source_identity": "same absolute temporary source path within each workload across graph modes and pairs",
        "semantic_execution_mode": "default parallel mode; ELISA_SEMANTIC_SERIAL is cleared for each arm",
        "warm_measurement": "body edits are the primary paired summary; prime, exact-repeat, declaration-surface, and post-surface body-edit controls also receive paired summaries",
        "name_lookup_hit_semantics": "call-facts uses one unique callee per body; ordinary warm requests must exceed the prime same-request hit baseline and post-surface must exceed N-1. Every shared-calls warm request must exceed its fixture-specific same-request duplicate baseline: 2N-2 when an alternate callee is present, 2N-1 for one shared callee, and 2N-3 after the post-surface literal transition. These aggregate thresholds prove at least one prior-request NameLookup hit, not reuse of every unchanged spelling.",
        "name_lookup_chain_visit_semantics": "graph-off and graph-on count only symbol/member hash-chain rows visited by the fused NameLookup cold classifier; direct-surface counts finalized-surface classifications separately and bypasses per-name graph evaluate/commit; direct name_known callers (including RegionNew, value-block captures, and flow checks) and qualified Expr.Scope probes are excluded",
        "reverse_mark_counter_semantics": "routing-only request counters cover query-graph reverse invalidation during collection/publication and semantic resolution; exact-repeat expects zero closure work and declaration-surface-edit must exercise a nonempty full walk plus at least one repeated-mark shortcut",
        "reverse_mark_counter_overhead": "timing arms disable counter increments, but the current graph traversal still checks the runtime metrics flag per visited node and edge; measured graph-on/off ratios include this branch overhead",
        "direct_fact_payload_semantics": "call-facts expects one direct-call fact per bench body before the post-surface transition, then one fewer; zero-fact expects no direct facts",
        "primary_performance_metric": "Stage1 process retired instructions from macOS proc_pid_rusage; wall time and cycles are supporting measurements",
        "timing_instrumentation": "separate routing arms enable cache reports and assert reuse; timing arms disable cache reports and chain-visit counting, retain phase timing, collect exact Stage1 process counters, and must match routing-arm diagnostics; summaries contain timing arms only",
        "arm_kind_ordering": (
            "with direct-surface enabled, all routing arms run and pass diagnostics parity before timing arms; mode order rotates across pairs"
            if args.include_direct_surface
            else "routing-first on even pairs and timing-first on odd pairs to counterbalance run-order drift"
        ),
        "diagnostic_parity": (
            "all routing modes must match per-request compiler transcript lines after timing/cache instrumentation removal before timed arms run; each timed arm must also match its same-mode routing arm"
            if args.include_direct_surface
            else "all per-request compiler transcript lines after timing/cache instrumentation removal"
        ),
        "benchmark_host_lock": None if args.concurrent_instruction_counts else str(host_lock_path),
        "host_qualification": str(host_qualification),
        "host_qualification_sha256": digest_file(host_qualification),
        "load_gate": (
            "disabled by --concurrent-instruction-counts; wall-time comparisons are unqualified"
            if args.concurrent_instruction_counts
            else "load1 / logical_cpu <= 0.20; 60 second stable admission"
        ),
        "pinned_inputs": pins,
    }
    temp = tempfile.TemporaryDirectory(prefix="elisa-retained-graph-")
    workload_specs = (("zero-fact", "zero-fact"), ("call-facts", "call-facts"))
    if args.include_direct_surface:
        workload_specs += (("shared-calls", "shared-calls"),)
    workloads: dict[str, tuple[Path, list[str]]] = {}
    source_hashes: dict[str, list[str]] = {}
    source_sequence_dir = output / "source-sequence"
    source_sequence_dir.mkdir()
    for workload, payload_mode in workload_specs:
        workload_dir = Path(temp.name) / workload
        workload_dir.mkdir()
        source = workload_dir / "session.elisa"
        source_versions = [fixture(args.functions, 0, payload_mode)]
        source_versions.extend(
            fixture(args.functions, 100_000 + index + 1, payload_mode)
            for index in range(args.body_edits)
        )
        source_versions.append(
            fixture(
                args.functions,
                100_000 + args.body_edits,
                payload_mode,
                add_surface_function=True,
            )
        )
        source_versions.append(
            fixture(
                args.functions,
                100_001 + args.body_edits,
                payload_mode,
                add_surface_function=True,
                post_surface_fact_transition=True,
            )
        )
        if workload == "shared-calls":
            if source_versions[0].count("return shared_fact_leaf()") != args.functions:
                raise RuntimeError("shared-calls prime fixture does not route every caller to one global callee")
            if "return shared_fact_leaf_alt()" not in source_versions[1]:
                raise RuntimeError("shared-calls first body edit does not change a caller's target")
        if workload in {"call-facts", "shared-calls"}:
            transitioned_body = "def bench_0000() -> i64:\n    return 42\n\n"
            if transitioned_body not in source_versions[-1]:
                raise RuntimeError(f"{workload} post-surface edit does not transition bench_0000 to a literal")
            previous = source_versions[-2]
            function_header = "def bench_0000() -> i64:\n"
            if previous.count(function_header) != 1:
                raise RuntimeError(f"{workload} declaration-surface fixture has no unique bench_0000 body")
            previous_return = previous.split(function_header, 1)[1].splitlines()[0]
            if not previous_return.startswith("    return ") or not previous_return.endswith("()"):
                raise RuntimeError(f"{workload} declaration-surface bench_0000 body is not a direct call")
            previous_body = f"{function_header}{previous_return}\n\n"
            if previous.count(previous_body) != 1 or previous.replace(previous_body, transitioned_body, 1) != source_versions[-1]:
                raise RuntimeError(f"{workload} post-surface edit changed source outside bench_0000's body")
        workloads[workload] = (source, source_versions)
        workload_sequence_dir = source_sequence_dir / workload
        workload_sequence_dir.mkdir()
        hashes: list[str] = []
        for index, version in enumerate(source_versions):
            if index == 0:
                name = "prime.elisa"
            elif index == len(source_versions) - 2:
                name = "declaration-surface-edit.elisa"
            elif index == len(source_versions) - 1:
                name = "post-surface-body-edit.elisa"
            else:
                name = f"body-edit-{index}.elisa"
            (workload_sequence_dir / name).write_text(version, encoding="utf-8")
            hashes.append(digest_bytes(version.encode()))
        source_hashes[workload] = hashes
    metadata["workloads"] = {
        "zero-fact": "cacheable literal-return bodies with zero direct-call facts",
        "call-facts": "unique-callee workload: cacheable direct-call bodies isolate reuse across distinct global name keys",
    }
    if args.include_direct_surface:
        metadata["workloads"]["shared-calls"] = (
            "shared-callee workload: cacheable callers repeat one global name to expose same-request duplicate lookup plus cross-request reuse; the first caller alternates to a distinct target on edits"
        )
    metadata["fixture_scope"] = (
        "synthetic fixtures contain no imports or import annotations; direct-surface versus graph comparisons do not measure import-heavy resolver-surface setup"
    )
    metadata["source_sequence_sha256"] = source_hashes
    arms: list[dict[str, Any]] = []
    routing_arms: list[dict[str, Any]] = []
    try:
        for pair_index in range(args.pairs):
            ordered_workloads = workload_specs if pair_index % 2 == 0 else tuple(reversed(workload_specs))
            for workload, _payload_mode in ordered_workloads:
                source, source_versions = workloads[workload]
                workload_index = 0 if workload == "zero-fact" else 1
                order = (
                    ("graph-off", "graph-on")
                    if (pair_index + workload_index) % 2 == 0
                    else ("graph-on", "graph-off")
                )
                routing_pair: dict[str, dict[str, Any]] = {}
                timing_pair: dict[str, dict[str, Any]] = {}
                collect_sequence = (True, False) if args.include_direct_surface else timing_arm_kinds(pair_index)
                route_order = three_mode_order(pair_index, workload_index) if args.include_direct_surface else order
                for collect_cache_report in collect_sequence:
                    pair_arms: dict[str, dict[str, Any]] = {}
                    arm_order = (
                        three_mode_order(pair_index, workload_index, timing=not collect_cache_report)
                        if args.include_direct_surface
                        else order
                    )
                    for order_index, mode in enumerate(arm_order):
                        if not args.concurrent_instruction_counts:
                            try:
                                check_load_gate(
                                    load_average(),
                                    f"before pair {pair_index} {workload} {mode}",
                                    output,
                                    system,
                                    host_qualification,
                                )
                            except LoadGateError as error:
                                raise SystemExit(str(error)) from error
                        arm = run_arm(
                            root=root,
                            stage1=stage1,
                            source=source,
                            source_versions=source_versions,
                            workload=workload,
                            output=output,
                            pair_index=pair_index,
                            mode=mode,
                            order=order_index,
                            functions=args.functions,
                            edits=args.body_edits,
                            timeout_seconds=args.timeout_seconds,
                            collect_cache_report=collect_cache_report,
                        )
                        pair_arms[mode] = arm
                        (routing_arms if collect_cache_report else arms).append(arm)
                        if not args.concurrent_instruction_counts:
                            try:
                                check_load_gate(
                                    load_average(),
                                    f"after pair {pair_index} {workload} {mode}",
                                    output,
                                    system,
                                    host_qualification,
                                )
                            except LoadGateError as error:
                                raise SystemExit(str(error)) from error
                        for pinned_path, expected_hash in pins.items():
                            if digest_file(Path(pinned_path)) != expected_hash:
                                raise SystemExit(f"pinned benchmark input changed during run: {pinned_path}")
                    if collect_cache_report:
                        validate_pair(
                            pair_arms["graph-off"],
                            pair_arms["graph-on"],
                            args.functions,
                            workload,
                            require_reports=True,
                        )
                        if args.include_direct_surface:
                            validate_direct_surface_pair(
                                pair_arms["graph-on"], pair_arms["direct-surface"], workload
                            )
                        routing_pair = pair_arms
                    else:
                        timing_pair = pair_arms
                for mode in route_order:
                    if routing_pair[mode]["mode_environment"] != timing_pair[mode]["mode_environment"]:
                        raise RuntimeError(f"{workload}: {mode} routing/timing environment differs")
                    validate_pair(
                        routing_pair[mode], timing_pair[mode], args.functions, workload, require_reports=False
                    )
    finally:
        temp.cleanup()

    subprocess.run(["python3", str(provenance_checker), "check-exact", str(root), str(stage1)], cwd=root, check=True)
    for pinned_path, expected_hash in pins.items():
        if digest_file(Path(pinned_path)) != expected_hash:
            raise SystemExit(f"pinned benchmark input changed during run: {pinned_path}")

    edit_labels = [f"body-edit-{index + 1}" for index in range(args.body_edits)]
    summaries: dict[str, Any] = {}
    summary_modes = (
        ("graph-off", "graph-on", "direct-surface")
        if args.include_direct_surface
        else ("graph-off", "graph-on")
    )
    for workload, _payload_mode in workload_specs:
        workload_arms = [arm for arm in arms if arm["workload"] == workload]
        per_edit: dict[str, Any] = {}
        paired_ratios: list[float] = []
        for label in edit_labels:
            off_samples = [
                request["request_wall_ms"]
                for arm in workload_arms
                if arm["mode"] == "graph-off"
                for request in arm["requests"]
                if request["label"] == label
            ]
            on_samples = [
                request["request_wall_ms"]
                for arm in workload_arms
                if arm["mode"] == "graph-on"
                for request in arm["requests"]
                if request["label"] == label
            ]
            off_median = statistics.median(off_samples)
            on_median = statistics.median(on_samples)
            per_edit[label] = {
                "graph_off_median_ms": off_median,
                "graph_on_median_ms": on_median,
                "graph_on_over_off_median_ratio": on_median / off_median,
                "samples_per_mode": args.pairs,
            }
        for pair_index in range(args.pairs):
            off_arm = next(
                arm for arm in workload_arms if arm["pair"] == pair_index and arm["mode"] == "graph-off"
            )
            on_arm = next(
                arm for arm in workload_arms if arm["pair"] == pair_index and arm["mode"] == "graph-on"
            )
            for label in edit_labels:
                off_value = next(
                    request["request_wall_ms"] for request in off_arm["requests"] if request["label"] == label
                )
                on_value = next(
                    request["request_wall_ms"] for request in on_arm["requests"] if request["label"] == label
                )
                paired_ratios.append(on_value / off_value)
        body_edit_summary = paired_timing_summary(paired_ratios, f"{workload} body edits")
        control_labels = ("prime", "exact-repeat", "declaration-surface-edit", "post-surface-body-edit")
        process_counter_summary = {
            "primary_metric": "instructions_retired",
            "instructions_retired": {
                "body_edits": paired_counter_measurements(
                    workload_arms,
                    args.pairs,
                    edit_labels,
                    "instructions_retired",
                    f"{workload} body edit instructions",
                ),
                "controls": paired_counter_measurements(
                    workload_arms,
                    args.pairs,
                    control_labels,
                    "instructions_retired",
                    f"{workload} control instructions",
                ),
            },
            "cycles_elapsed": {
                "body_edits": paired_counter_measurements(
                    workload_arms, args.pairs, edit_labels, "cycles_elapsed", f"{workload} body edit cycles"
                ),
                "controls": paired_counter_measurements(
                    workload_arms, args.pairs, control_labels, "cycles_elapsed", f"{workload} control cycles"
                ),
            },
        }
        paired_controls: dict[str, Any] = {}
        for label in control_labels:
            control_ratios: list[float] = []
            for pair_index in range(args.pairs):
                off_arm = next(
                    arm for arm in workload_arms if arm["pair"] == pair_index and arm["mode"] == "graph-off"
                )
                on_arm = next(
                    arm for arm in workload_arms if arm["pair"] == pair_index and arm["mode"] == "graph-on"
                )
                off_value = next(
                    request["request_wall_ms"] for request in off_arm["requests"] if request["label"] == label
                )
                on_value = next(
                    request["request_wall_ms"] for request in on_arm["requests"] if request["label"] == label
                )
                control_ratios.append(on_value / off_value)
            control_summary = paired_timing_summary(control_ratios, f"{workload} {label}")
            control_summary["paired_control_samples"] = len(control_ratios)
            paired_controls[label] = control_summary
        workload_summary = {
            "per_edit": per_edit,
            **body_edit_summary,
            "primary_metric": "instructions_retired",
            "primary_instruction_summary": process_counter_summary["instructions_retired"]["body_edits"][
                "paired_aggregate"
            ],
            "process_counters": process_counter_summary,
            "paired_edit_samples": len(paired_ratios),
            "paired_controls": paired_controls,
            "control_medians_ms": {
                label: {
                    mode: statistics.median(
                        request["request_wall_ms"]
                        for arm in workload_arms
                        if arm["mode"] == mode
                        for request in arm["requests"]
                        if request["label"] == label
                    )
                    for mode in summary_modes
                }
                for label in ("prime", "exact-repeat", "declaration-surface-edit", "post-surface-body-edit")
            },
            "process_wall_medians_ms": {
                mode: statistics.median(arm["process_wall_ms"] for arm in workload_arms if arm["mode"] == mode)
                for mode in summary_modes
            },
        }
        if args.include_direct_surface:
            comparison_labels = (
                "prime",
                "exact-repeat",
                *edit_labels,
                "declaration-surface-edit",
                "post-surface-body-edit",
            )
            workload_summary["direct_surface_vs_graph_on"] = {
                "request_wall_ms": paired_mode_measurements(
                    workload_arms,
                    args.pairs,
                    comparison_labels,
                    "request_wall_ms",
                    "graph-on",
                    "direct-surface",
                    f"{workload} direct-surface wall time",
                ),
                "instructions_retired": paired_mode_measurements(
                    workload_arms,
                    args.pairs,
                    comparison_labels,
                    "instructions_retired",
                    "graph-on",
                    "direct-surface",
                    f"{workload} direct-surface instructions",
                ),
                "cycles_elapsed": paired_mode_measurements(
                    workload_arms,
                    args.pairs,
                    comparison_labels,
                    "cycles_elapsed",
                    "graph-on",
                    "direct-surface",
                    f"{workload} direct-surface cycles",
                ),
            }
        summaries[workload] = workload_summary
    summary = {"workloads": summaries}
    result = {"metadata": metadata, "summary": summary, "arms": arms, "routing_arms": routing_arms}
    (output / "paired.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "COMPLETE").write_text("Paired retained-session graph measurement finished.\n", encoding="utf-8")
    run_state["complete"] = True
    if host_lock_fd is not None:
        os.close(host_lock_fd)
    print(json.dumps({"output": str(output), "summary": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
