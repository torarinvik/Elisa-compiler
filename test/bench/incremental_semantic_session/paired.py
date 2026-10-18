#!/usr/bin/env python3
"""Paired retained-session benchmark for the experimental semantic query graph.

This measures an in-memory semantic-session body-edit path. It is distinct from
incremental_fact_lookup/paired.py, which launches fresh compiler processes and
measures the durable disk-sidecar path. The graph remains opt-in in production.
"""

from __future__ import annotations

import argparse
import atexit
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


ROOT = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(ROOT / "scripts"))
from bench_load_gate import (  # noqa: E402
    LoadGateError,
    check_load_gate,
    load_average,
    wait_for_sustained_load_gate,
)


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def fixture(functions: int, edit_version: int, payload_mode: str, add_surface_function: bool = False) -> str:
    pieces = [
        "# Many cacheable, independent bodies make the collector's reuse path visible.\n\n",
    ]
    if payload_mode == "call-facts":
        pieces.extend(
            (
                "def fact_leaf_a() -> i64:\n    return 1\n\n",
                "def fact_leaf_b() -> i64:\n    return 2\n\n",
            )
        )
    for index in range(functions):
        if payload_mode == "call-facts":
            target = "fact_leaf_b" if index == 0 and edit_version % 2 == 1 else "fact_leaf_a"
            body = f"    return {target}()\n"
        else:
            value = edit_version if index == 0 else index
            body = f"    return {value}\n"
        pieces.append(f"def bench_{index:04d}() -> i64:\n{body}\n")
    if add_surface_function:
        pieces.append("def declaration_surface_change() -> i64:\n    return 17\n\n")
    # Keep a stable diagnostic in the stream so the paired run compares more
    # than exit status. This body intentionally remains outside the narrow fact
    # scanner's cacheable grammar.
    pieces.append(
        "def lint() -> i64:\n"
        "    value: mutable i64 = 40\n"
        "    value <- value\n"
        "    return value\n\n"
    )
    pieces.append(
        "def main() -> i64:\n"
        "    return 0\n"
    )
    return "".join(pieces)


def normalized_transcript(lines: list[str]) -> list[str]:
    ignored_prefixes = (
        "incremental-ga-cache:",
        "stage1-timing:",
        "stage1-counter:",
    )
    return [line for line in lines if not line.startswith(ignored_prefixes)]


def report_fields(lines: list[str]) -> dict[str, str]:
    report = next((line for line in lines if line.startswith("incremental-ga-cache:")), None)
    if report is None:
        raise RuntimeError("semantic-session response omitted incremental cache report")
    return dict(re.findall(r"([a-z][a-z0-9_]*)=([^\s]+)", report))


def timing_rows(lines: list[str]) -> list[dict[str, Any]]:
    pattern = re.compile(r"^stage1-timing: (.+?) wall_ms=([0-9.]+) cpu_ms=([0-9.]+)$")
    rows: list[dict[str, Any]] = []
    for line in lines:
        match = pattern.match(line)
        if match:
            rows.append({"phase": match.group(1), "wall_ms": float(match.group(2)), "cpu_ms": float(match.group(3))})
    return rows


class PipeLineReader:
    """Read bytes directly so select() and Python's text buffer cannot diverge."""

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        self.fd = proc.stdout.fileno()
        self.buffer = bytearray()

    def readline(self, deadline: float) -> str:
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self.buffer[:newline]).rstrip(b"\r")
                del self.buffer[: newline + 1]
                return line.decode("utf-8", errors="replace")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for semantic-session response")
            ready, _, _ = select.select([self.fd], [], [], remaining)
            if not ready:
                raise TimeoutError("timed out waiting for semantic-session response")
            chunk = os.read(self.fd, 65536)
            if not chunk:
                raise RuntimeError("semantic-session closed its output before replying")
            self.buffer.extend(chunk)


def read_response(reader: PipeLineReader, deadline: float) -> tuple[str, list[str]]:
    lines: list[str] = []
    while True:
        value = reader.readline(deadline)
        if value in {"0", "1", "2"}:
            return value, lines
        lines.append(value)


def stop_process_group(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def run_arm(
    *,
    root: Path,
    stage1: Path,
    source: Path,
    source_versions: list[str],
    workload: str,
    output: Path,
    pair_index: int,
    mode: str,
    order: int,
    functions: int,
    edits: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    source.write_text(source_versions[0], encoding="utf-8")
    mode_dir = output / f"pair-{pair_index:02d}-{workload}-{mode}"
    mode_dir.mkdir()
    command = ["bash", str(root / "scripts/elisac_stage1.sh"), "semantic-session", str(source)]
    env = os.environ.copy()
    for key in (
        "ELISA_STAGE1_INCREMENTAL_CACHE_DIR",
        "ELISA_STAGE1_INCREMENTAL_SHADOW",
        "ELISA_STAGE1_INCREMENTAL_SHADOW_REPORT",
        "ELISA_STAGE1_PERMISSIVE",
    ):
        env.pop(key, None)
    env.update(
        {
            "ELISA_STAGE1_BIN": str(stage1),
            "ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH": "1" if mode == "graph-on" else "0",
            "ELISA_STAGE1_INCREMENTAL_CACHE_REPORT": "1",
            "ELISA_STAGE1_TIMINGS": "1",
            "ELISA_ALLOW_STALE_STAGE1": "0",
        }
    )
    started = time.perf_counter_ns()
    proc = subprocess.Popen(
        command,
        cwd=root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        start_new_session=True,
    )
    reader = PipeLineReader(proc)
    results: list[dict[str, Any]] = []
    request_specs: list[tuple[str, str | None]] = [("prime", None), ("exact-repeat", None)]
    request_specs.extend((f"body-edit-{index + 1}", source_versions[index + 1]) for index in range(edits))
    request_specs.append(("declaration-surface-edit", source_versions[-1]))
    transcript_log = mode_dir / "requests.log"
    try:
        assert proc.stdin is not None
        with transcript_log.open("w", encoding="utf-8") as raw_log:
            for request_index, (label, next_source) in enumerate(request_specs):
                if next_source is not None:
                    source.write_text(next_source, encoding="utf-8")
                before = time.perf_counter_ns()
                proc.stdin.write(b"check\n")
                proc.stdin.flush()
                status, lines = read_response(reader, time.monotonic() + timeout_seconds)
                request_wall_ms = (time.perf_counter_ns() - before) / 1_000_000
                raw_log.write(f"=== request={request_index} label={label} status={status} ===\n")
                raw_log.writelines(line + "\n" for line in lines)
                if status != "0":
                    raise RuntimeError(f"benchmark fixture check {label} was rejected with status {status}")
                fields = report_fields(lines)
                result = {
                    "request_index": request_index,
                    "label": label,
                    "status": int(status),
                    "request_wall_ms": request_wall_ms,
                    "timings": timing_rows(lines),
                    "cache": fields,
                    "diagnostic_sha256": digest_bytes("\n".join(normalized_transcript(lines)).encode()),
                    "diagnostics": normalized_transcript(lines),
                }
                results.append(result)
            proc.stdin.write(b"quit\n")
            proc.stdin.flush()
            proc.stdin.close()
        remaining = max(0.1, timeout_seconds)
        status = proc.wait(timeout=remaining)
        if status != 0:
            raise RuntimeError(f"semantic-session process exited with status {status}")
    except BaseException:
        stop_process_group(proc)
        raise
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return {
        "pair": pair_index,
        "workload": workload,
        "mode": mode,
        "order": order,
        "process_wall_ms": elapsed_ms,
        "process_counters": {
            "status": "unavailable",
            "method": "not collected",
            "instructions_retired": None,
            "cycles_elapsed": None,
            "process_tree_cpu_seconds": None,
            "command_real_seconds": None,
            "scope": "Stage1 runs as a child of the guarded shell launcher; launcher PID counters are not compiler counters",
        },
        "source_path": str(source),
        "initial_source_sha256": digest_bytes(source_versions[0].encode()),
        "request_count": len(results),
        "requests": results,
    }


def validate_pair(off: dict[str, Any], on: dict[str, Any], functions: int, workload: str) -> None:
    off_requests = off["requests"]
    on_requests = on["requests"]
    if len(off_requests) != len(on_requests):
        raise RuntimeError(f"{workload}: graph-on/off request counts differ")
    for index, (left, right) in enumerate(zip(off_requests, on_requests)):
        if left["status"] != right["status"]:
            raise RuntimeError(f"{workload}: graph-on/off request {index} status differs")
        if left["diagnostics"] != right["diagnostics"]:
            raise RuntimeError(f"{workload}: graph-on/off request {index} diagnostics/transcript differ")
        metric_fields = ("name_lookup_hits", "name_lookup_classification_chain_visits")
        if any(field not in left["cache"] or field not in right["cache"] for field in metric_fields):
            raise RuntimeError(f"{workload}: request {index} omitted NameLookup measurement counters")
        if int(left["cache"]["name_lookup_hits"]) != 0:
            raise RuntimeError(f"{workload}: graph-off request {index} unexpectedly hit NameLookup")
        if workload == "call-facts" and (
            right["label"] == "exact-repeat" or right["label"].startswith("body-edit-")
        ):
            lookup_hits = int(right["cache"]["name_lookup_hits"])
            off_visits = int(left["cache"]["name_lookup_classification_chain_visits"])
            on_visits = int(right["cache"]["name_lookup_classification_chain_visits"])
            if lookup_hits <= 0:
                raise RuntimeError(f"call-facts graph-on request {index} recorded no NameLookup hits")
            if on_visits >= off_visits:
                raise RuntimeError(
                    f"call-facts graph-on request {index} did not reduce name-classification chain visits: "
                    f"graph-on={on_visits} graph-off={off_visits} hits={lookup_hits}"
                )
        for field in ("eligible_bodies", "matched_eligible_bodies"):
            if left["cache"].get(field) != right["cache"].get(field):
                raise RuntimeError(f"{workload}: graph-on/off request {index} has different {field} counts")
        expected_eligible = functions + (3 if workload == "call-facts" else 1)
        if left["label"] == "declaration-surface-edit":
            expected_eligible += 1
        eligible = int(left["cache"].get("eligible_bodies", "-1"))
        if eligible != expected_eligible:
            raise RuntimeError(
                f"{workload}: request {left['label']} admitted {eligible} cacheable bodies; "
                f"fixture expects {expected_eligible}"
            )
    if len(off_requests) < 3:
        raise RuntimeError(f"{workload}: benchmark needs at least one body edit")
    for index, (left, right) in enumerate(zip(off_requests, on_requests)):
        if not left["label"].startswith("body-edit-"):
            continue
        off_cache = left["cache"]
        on_cache = right["cache"]
        if off_cache.get("source_input_admitted") != "no":
            raise RuntimeError(f"graph-off edit {index} unexpectedly admitted SourceInput")
        if int(off_cache.get("prior_snapshot_fact_fallbacks", "0")) <= 0:
            raise RuntimeError(f"graph-off edit {index} skipped typed-snapshot fact fallback")
        if on_cache.get("source_input_admitted") != "yes":
            raise RuntimeError(f"graph-on edit {index} did not admit unchanged SourceInput")
        expected_restored = int(off_cache.get("eligible_bodies", "0")) - 1
        restored = int(on_cache.get("function_body_facts_restored", "0"))
        if expected_restored <= 0 or restored != expected_restored:
            raise RuntimeError(
                f"graph-on edit {index} did not restore every unchanged cacheable body: "
                f"restored={restored} expected={expected_restored} functions={functions}"
            )
    surface_index = next(index for index, request in enumerate(off_requests) if request["label"] == "declaration-surface-edit")
    for mode, request in (("graph-off", off_requests[surface_index]), ("graph-on", on_requests[surface_index])):
        cache = request["cache"]
        if cache.get("source_input_admitted") != "no":
            raise RuntimeError(f"{mode} declaration-surface edit admitted stale SourceInput")
        if cache.get("function_body_facts_restored") != "0" or cache.get("prior_snapshot_fact_fallbacks") != "0":
            raise RuntimeError(f"{mode} declaration-surface edit reused body facts across changed declarations")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1", type=Path, default=ROOT / "bin/elisac-stage1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--functions", type=int, default=128)
    parser.add_argument("--body-edits", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=120)
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
                "reason": "retained semantic graph paired timings are exploratory",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
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
        "status": "exploratory retained semantic-session graph-on/off benchmark; not disk-sidecar timing",
        "platform": platform.platform(),
        "python": sys.version,
        "stage1_path": str(stage1),
        "stage1_sha256": digest_file(stage1),
        "stage1_provenance_sha256": digest_file(Path(str(stage1) + ".provenance.json")),
        "runner_sha256": digest_file(Path(__file__).resolve()),
        "process_counter_method": "unavailable: guarded Stage1 shell launcher owns the measured PID; no compiler instruction attribution",
        "pairs": args.pairs,
        "functions": args.functions,
        "body_edits_per_arm": args.body_edits,
        "source_identity": "same absolute temporary source path within each workload across graph modes and pairs",
        "warm_measurement": "body-edit requests only; prime and exact-repeat are reported separately per workload",
        "diagnostic_parity": "all per-request compiler transcript lines after timing/cache instrumentation removal",
        "benchmark_host_lock": str(host_lock_path),
        "host_qualification": str(host_qualification),
        "host_qualification_sha256": digest_file(host_qualification),
        "load_gate": "load1 / logical_cpu <= 0.20; 60 second stable admission",
        "pinned_inputs": pins,
    }
    temp = tempfile.TemporaryDirectory(prefix="elisa-retained-graph-")
    workload_specs = (("zero-fact", "zero-fact"), ("call-facts", "call-facts"))
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
        workloads[workload] = (source, source_versions)
        workload_sequence_dir = source_sequence_dir / workload
        workload_sequence_dir.mkdir()
        hashes: list[str] = []
        for index, version in enumerate(source_versions):
            if index == 0:
                name = "prime.elisa"
            elif index == len(source_versions) - 1:
                name = "declaration-surface-edit.elisa"
            else:
                name = f"body-edit-{index}.elisa"
            (workload_sequence_dir / name).write_text(version, encoding="utf-8")
            hashes.append(digest_bytes(version.encode()))
        source_hashes[workload] = hashes
    metadata["workloads"] = {
        "zero-fact": "cacheable literal-return bodies with zero direct-call facts",
        "call-facts": "cacheable direct-call bodies with nonempty direct-call facts",
    }
    metadata["source_sequence_sha256"] = source_hashes
    arms: list[dict[str, Any]] = []
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
                pair_arms: dict[str, dict[str, Any]] = {}
                for order_index, mode in enumerate(order):
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
                    )
                    pair_arms[mode] = arm
                    arms.append(arm)
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
                validate_pair(
                    pair_arms["graph-off"],
                    pair_arms["graph-on"],
                    args.functions,
                    workload,
                )
    finally:
        temp.cleanup()

    subprocess.run(["python3", str(provenance_checker), "check-exact", str(root), str(stage1)], cwd=root, check=True)
    for pinned_path, expected_hash in pins.items():
        if digest_file(Path(pinned_path)) != expected_hash:
            raise SystemExit(f"pinned benchmark input changed during run: {pinned_path}")

    edit_labels = [f"body-edit-{index + 1}" for index in range(args.body_edits)]
    summaries: dict[str, Any] = {}
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
        if any(not math.isfinite(ratio) or ratio <= 0 for ratio in paired_ratios):
            raise RuntimeError(f"{workload}: paired request timing produced an invalid graph-on/off ratio")
        summaries[workload] = {
            "per_edit": per_edit,
            "median_paired_graph_on_over_off_ratio": statistics.median(paired_ratios),
            "geometric_mean_paired_graph_on_over_off_ratio": math.exp(
                sum(math.log(ratio) for ratio in paired_ratios) / len(paired_ratios)
            ),
            "paired_graph_on_wins": sum(ratio < 1.0 for ratio in paired_ratios),
            "paired_graph_off_wins": sum(ratio > 1.0 for ratio in paired_ratios),
            "paired_ties": sum(ratio == 1.0 for ratio in paired_ratios),
            "paired_edit_samples": len(paired_ratios),
            "paired_request_ratios": paired_ratios,
            "control_medians_ms": {
                label: {
                    mode: statistics.median(
                        request["request_wall_ms"]
                        for arm in workload_arms
                        if arm["mode"] == mode
                        for request in arm["requests"]
                        if request["label"] == label
                    )
                    for mode in ("graph-off", "graph-on")
                }
                for label in ("prime", "exact-repeat", "declaration-surface-edit")
            },
            "process_wall_medians_ms": {
                mode: statistics.median(arm["process_wall_ms"] for arm in workload_arms if arm["mode"] == mode)
                for mode in ("graph-off", "graph-on")
            },
        }
    summary = {"workloads": summaries}
    result = {"metadata": metadata, "summary": summary, "arms": arms}
    (output / "paired.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "COMPLETE").write_text("Paired retained-session graph measurement finished.\n", encoding="utf-8")
    run_state["complete"] = True
    os.close(host_lock_fd)
    print(json.dumps({"output": str(output), "summary": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
