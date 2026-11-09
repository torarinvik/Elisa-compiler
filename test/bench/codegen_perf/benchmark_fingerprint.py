"""Record benchmark host, workload and toolchain fingerprints."""
import csv
import hashlib
import json
import math
import os
import platform
import resource
import shlex
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path


def host_platform_profile(_context):
    host = platform.uname()
    models = set()
    features = set()
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-a"], capture_output=True, text=True, check=False, timeout=5
            )
            for line in result.stdout.splitlines():
                key, separator, value = line.partition(":")
                if not separator:
                    continue
                key = key.strip()
                value = value.strip()
                if key in ("machdep.cpu.brand_string", "hw.model") and value:
                    models.add(value)
                elif key in (
                    "machdep.cpu.features",
                    "machdep.cpu.leaf7_features",
                    "machdep.cpu.extfeatures",
                ):
                    features.update(value.split())
                elif key.startswith("hw.optional.arm.") and value == "1":
                    features.add(key.removeprefix("hw.optional.arm."))
        except (OSError, subprocess.TimeoutExpired):
            pass
    elif sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines():
                key, separator, value = line.partition(":")
                if not separator:
                    continue
                key = key.strip().lower()
                value = value.strip()
                if key in (
                    "model name",
                    "hardware",
                    "cpu model",
                    "cpu implementer",
                    "cpu architecture",
                    "cpu part",
                    "cpu revision",
                ) and value:
                    models.add(value)
                elif key in ("flags", "features"):
                    features.update(value.split())
        except OSError:
            pass
    if not models and platform.processor():
        models.add(platform.processor())
    qualification = json.loads((_context['out'] / "host_qualification.json").read_text())
    try:
        allowed_cpu_ids = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        allowed_cpu_ids = None
    return {
        "system": host.system,
        "machine": host.machine,
        "os_release": host.release,
        "os_version": host.version,
        "cpu_models": sorted(models) or ["unknown"],
        "cpu_features": sorted(features),
        "benchmark_cpu_entitlement": {
            "logical_cpu_count": os.cpu_count(),
            "allowed_cpu_count": qualification.get("allowed_cpu_count"),
            "allowed_cpu_ids": allowed_cpu_ids,
            "effective_cgroup_cpu_quota": qualification.get("effective_cgroup_cpu_quota"),
        },
    }

def comparator_toolchain_identity(_context):
    """Hash comparator tools while excluding candidate-specific compiler/runtime products."""
    candidate_products = {
        str(Path(_context['elisa_bin']).resolve()),
        str(Path(f"{_context['elisa_bin']}.provenance.json").resolve()),
        str(Path(_context['runtime']).resolve()),
    }
    rows = []
    for line in (_context['out'] / "toolchain.before.sha256").read_text().splitlines():
        digest, separator, raw_path = line.partition("  ")
        if not separator or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
            raise RuntimeError("malformed toolchain.before.sha256 manifest")
        raw_path_obj = Path(raw_path)
        resolved_path = str(raw_path_obj.resolve())
        if resolved_path in candidate_products or raw_path_obj.name.endswith(".provenance.json"):
            continue
        rows.append({"path": resolved_path, "sha256": digest.lower()})
    if not rows:
        raise RuntimeError("toolchain manifest contains no pinned comparator tools")
    return sorted(rows, key=lambda row: (row["path"], row["sha256"]))

def benchmark_helper_hashes(_context):
    paths = (
        _context['root'] / "scripts" / "bench_load_gate.py",
        _context['root'] / "scripts" / "platform.sh",
        _context['root'] / "scripts" / "stage1_provenance.py",
        _context['root'] / "scripts" / "elisac_stage1.sh",
        _context['root'] / "scripts" / "build_runtime_object.sh",
        _context['root'] / "scripts" / "write_profiler_hook_fallbacks.sh",
    )
    return {
        path.relative_to(_context['root']).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }

def run_environment_input_hashes(_context, environment):
    names = set(_context['ENVIRONMENT_INPUT_NAMES'])
    names.update(name for name in environment if name.startswith(("ELISA_", "ELISACORE_")))
    return _context['environment_input_hashes'](environment, sorted(names))

def parity_environment_input_hashes(_context, environment):
    """Fingerprint effective settings while normalizing candidate-specific artifact paths."""
    normalized_paths = {
        "ELISA_STAGE1_BIN": "<stage1-binary>",
        "ELISA_STAGE1_SELF": "<stage1-binary>",
        "ELISA_STAGE1_ROOT": "<stage1-source-root>",
        "ELISA_STAGE1_PROVENANCE_ROOT": "<stage1-provenance-source-root>",
        "ELISA_RUNTIME_OBJ": "<runtime-object>",
    }
    projected = _context['run_environment_input_hashes'](environment)
    for name, normalized_value in normalized_paths.items():
        raw = projected.get(name, {"present": False, "sha256": None})
        projected[name] = {
            "present": raw["present"],
            "normalized_value": normalized_value if raw["present"] else None,
        }
    return projected

def parse_toolchain_manifest(_context):
    rows = []
    for line in (_context['out'] / "toolchain.before.sha256").read_text().splitlines():
        digest, separator, raw_path = line.partition("  ")
        if not separator or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()) or not raw_path:
            raise RuntimeError("malformed toolchain.before.sha256 manifest")
        rows.append({"path": str(Path(raw_path).resolve()), "sha256": digest.lower()})
    return sorted(rows, key=lambda row: (row["path"], row["sha256"]))

def shared_runtime_source_manifest(_context):
    """Fingerprint runtime source inputs independently of changing compiler sources."""
    runtime_root = _context['root'] / "elisacore_std"
    if not runtime_root.is_dir():
        raise RuntimeError(f"missing runtime source directory: {runtime_root}")
    paths = [
        path for path in runtime_root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.suffix in (".elisa", ".elisai")
    ]
    paths.extend((
        _context['root'] / "scripts" / "build_runtime_object.sh",
        _context['root'] / "scripts" / "write_profiler_hook_fallbacks.sh",
    ))
    rows = []
    for path in sorted(set(paths)):
        if not path.is_file():
            raise RuntimeError(f"missing shared runtime source input: {path}")
        rows.append({
            "path": path.relative_to(_context['root']).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    if not any(row["path"].startswith("elisacore_std/") for row in rows):
        raise RuntimeError("shared runtime source manifest contains no runtime sources")
    manifest_bytes = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"sha256": hashlib.sha256(manifest_bytes).hexdigest(), "files": rows}

def write_canonical_workload_fingerprint(_context, observed_results):
    """Record source/checksum/status parity independently of candidate compiler sources."""
    workloads = []
    for bench in _context['benches']:
        source_hashes = {
            suffix: hashlib.sha256((_context['source_dir'] / f"{bench}.{suffix}").read_bytes()).hexdigest()
            for suffix in ("elisa", "c", "rs", "zig")
        }
        observed = observed_results[bench]
        workloads.append({
            "name": bench,
            "source_sha256": source_hashes,
            "expected": {
                "checksum": _context['expected_checksums'][bench],
                "exit_status": _context['expected_exit_statuses'][bench],
            },
            "observed": {
                "checksum": observed["checksum"].strip(),
                "exit_status": observed["exit_status"],
            },
        })
    payload = {
        "schema": "canonical-codegen-workloads-v5",
        "scope": "compile_only" if _context['compile_only'] else "full_runtime",
        "runner_sha256": hashlib.sha256((_context['source_dir'] / "cross_language.sh").read_bytes()).hexdigest(),
        "benchmark_helper_sha256": _context['benchmark_helper_hashes'](),
        "comparator_toolchain": _context['comparator_toolchain_identity'](),
        "platform": _context['host_platform_profile'](),
        "measurement_protocol": {
            "build_repeats": _context['repeat'],
            "runtime_repeats": _context['runtime_repeat'],
            "timeout_seconds": _context['timeout_seconds'],
            "load_gate_fraction": _context['LOAD_FRACTION'],
        },
        "environment": {
            "cleared_loader_allocator_names": _context['cleared_loader_allocator_names'],
            "cleared_elisacore_names": _context['cleared_elisacore_names'],
            "ambient_inputs": _context['environment_input_hashes'](os.environ),
            "effective_build_inputs": _context['parity_environment_input_hashes'](_context['child_env']),
            "effective_runtime_inputs": _context['parity_environment_input_hashes'](os.environ),
        },
        "compile_profile": {
            "elisa": {"opt": "-O3", "overflow": _context['elisa_overflow_flag']},
            "elisa_runtime": {
                "mode": _context['runtime_profile_mode'],
                "opt_level": _context['runtime_profile_opt_level'],
                "overflow": _context['runtime_profile_overflow'],
            },
            "c": {"opt": "-O3", "cpu_flags": _context['cpu_flags'], "linker_flags": _context['clang_linker_flags'], "dead_strip_flags": _context['dead_strip'], "link_flags": _context['link_flags']},
            "rust": {"opt_level": 3, "codegen_units": "default", "overflow_checks": _context['rust_overflow_checks'], "target_cpu": "native"},
            "zig": {"optimize": _context['zig_optimize'], "target_cpu": "native"},
        },
        "workloads": workloads,
    }
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    source_manifest_bytes = (_context['out'] / "sources.sha256").read_bytes()
    toolchain_manifest_bytes = (_context['out'] / "toolchain.before.sha256").read_bytes()
    metadata_bytes = (_context['out'] / "metadata.txt").read_bytes()
    metadata_values = dict(
        line.partition("=")[::2]
        for line in metadata_bytes.decode("utf-8").splitlines()
        if "=" in line
    )
    if metadata_values.get("retired_instruction_counter") != _context['counter_method_description']():
        raise RuntimeError("counter method differs between shell metadata and Python sampler")
    qualification_bytes = (_context['out'] / "host_qualification.json").read_bytes()
    runtime_artifact_sha256 = hashlib.sha256(Path(_context['runtime']).read_bytes()).hexdigest()
    run_provenance = {
        "scope": payload["scope"],
        "retired_instruction_counter": _context['counter_method_description'](),
        "source_manifest_sha256": hashlib.sha256(source_manifest_bytes).hexdigest(),
        "toolchain_manifest_sha256": hashlib.sha256(toolchain_manifest_bytes).hexdigest(),
        "toolchain_manifest": _context['parse_toolchain_manifest'](),
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "host_qualification_sha256": hashlib.sha256(qualification_bytes).hexdigest(),
        "runtime_artifact_sha256": runtime_artifact_sha256,
        "shared_runtime_source_manifest": _context['shared_runtime_source_manifest'](),
        "build_environment_inputs": _context['run_environment_input_hashes'](_context['child_env']),
        "runtime_environment_inputs": _context['run_environment_input_hashes'](os.environ),
    }
    run_binding_bytes = json.dumps(
        {"payload": payload, "run_provenance": run_provenance},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    record = {
        "schema": payload["schema"],
        "fingerprint_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "run_fingerprint_sha256": hashlib.sha256(run_binding_bytes).hexdigest(),
        # Runtime bytes can legitimately change when this candidate compiler builds them.
        # Keep their identity per run without making workload/profile parity revision-sensitive.
        "runtime_artifact_sha256": runtime_artifact_sha256,
        "payload": payload,
        "run_provenance": run_provenance,
    }
    fingerprint_file = _context['out'] / "canonical_workload_fingerprint.json"
    fingerprint_file.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    if _context['expected_fingerprint_path']:
        reference_path = Path(_context['expected_fingerprint_path'])
        if reference_path.resolve() == fingerprint_file.resolve():
            _context['mark_aborted']("canonical workload fingerprint check failed", "reference cannot be the candidate output fingerprint file")
        try:
            reference = json.loads(reference_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            _context['mark_aborted']("canonical workload fingerprint check failed", f"cannot read {reference_path}: {error}")
        if not isinstance(reference, dict):
            _context['mark_aborted']("canonical workload fingerprint check failed", f"reference {reference_path} is not a JSON object")
        reference_payload = reference.get("payload")
        reference_scope = reference_payload.get("scope") if isinstance(reference_payload, dict) else None
        if reference_scope not in ("compile_only", "full_runtime"):
            _context['mark_aborted']("canonical workload fingerprint check failed", f"reference {reference_path} has an invalid run scope")
        completion_marker = "COMPILE_COMPLETE" if reference_scope == "compile_only" else "COMPLETE"
        reference_directory = reference_path.resolve().parent
        marker_path = reference_directory / completion_marker
        other_marker = reference_directory / ("COMPLETE" if completion_marker == "COMPILE_COMPLETE" else "COMPILE_COMPLETE")
        preflight_marker = reference_directory / "PREFLIGHT_COMPLETE"
        successful_timing_marker = (
            marker_path.is_file() and marker_path.stat().st_size > 0 and not other_marker.exists()
        )
        successful_preflight_marker = preflight_marker.is_file() and preflight_marker.stat().st_size > 0
        if (
            (reference_directory / "ABORTED.txt").exists()
            or not (successful_timing_marker or successful_preflight_marker)
        ):
            _context['mark_aborted'](
                "canonical workload fingerprint check failed",
                f"reference {reference_path} has no successful {completion_marker} or PREFLIGHT_COMPLETE marker",
            )
        if reference_scope != payload["scope"]:
            _context['mark_aborted'](
                "canonical workload fingerprint scope mismatch",
                f"candidate scope {payload['scope']} does not match reference scope {reference_scope!r}",
            )
        reference_provenance = reference.get("run_provenance")
        if not isinstance(reference_provenance, dict):
            _context['mark_aborted']("canonical workload fingerprint check failed", f"reference {reference_path} has no run provenance")
        reference_run_binding = json.dumps(
            {"payload": reference_payload, "run_provenance": reference_provenance},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if reference.get("run_fingerprint_sha256") != hashlib.sha256(reference_run_binding).hexdigest():
            _context['mark_aborted']("canonical workload fingerprint check failed", f"reference {reference_path} has invalid run provenance integrity")
        if reference.get("runtime_artifact_sha256") != reference_provenance.get("runtime_artifact_sha256"):
            _context['mark_aborted']("canonical workload fingerprint check failed", f"reference {reference_path} has inconsistent runtime artifact provenance")
        if (
            reference.get("schema") != record["schema"]
            or reference.get("fingerprint_sha256") != record["fingerprint_sha256"]
            or reference.get("payload") != payload
        ):
            _context['mark_aborted'](
                "canonical workload fingerprint mismatch",
                f"candidate fingerprint {record['fingerprint_sha256']} does not match reference {reference_path}",
            )
        if _context['runtime_profile_mode'] == "rebuilt-from-source":
            reference_runtime_sources = reference_provenance.get("shared_runtime_source_manifest")
            candidate_runtime_sources = run_provenance["shared_runtime_source_manifest"]
            if reference_runtime_sources != candidate_runtime_sources:
                _context['mark_aborted'](
                    "shared runtime source mismatch",
                    "rebuilt-runtime comparison requires identical runtime source and build-helper inputs",
                )
        reference_runtime_sha256 = reference_provenance.get("runtime_artifact_sha256")
        if (
            not isinstance(reference_runtime_sha256, str)
            or len(reference_runtime_sha256) != 64
            or any(char not in "0123456789abcdef" for char in reference_runtime_sha256.lower())
        ):
            _context['mark_aborted']("canonical workload fingerprint check failed", f"reference {reference_path} has an invalid runtime artifact hash")
        runtime_comparison = {
            "policy": (
                "must_match_shared_selected_runtime"
                if _context['runtime_profile_mode'] == "selected-runtime-object"
                else "report_both_rebuilt_runtime_hashes_allow_difference"
            ),
            "reference_sha256": reference_runtime_sha256.lower(),
            "candidate_sha256": runtime_artifact_sha256,
            "equal": reference_runtime_sha256.lower() == runtime_artifact_sha256,
        }
        run_provenance["runtime_artifact_comparison"] = runtime_comparison
        run_binding_bytes = json.dumps(
            {"payload": payload, "run_provenance": run_provenance},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        record["run_fingerprint_sha256"] = hashlib.sha256(run_binding_bytes).hexdigest()
        record["run_provenance"] = run_provenance
        record["runtime_artifact_comparison"] = runtime_comparison
        fingerprint_file.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(f"runtime_artifact_policy={runtime_comparison['policy']}")
        print(f"runtime_artifact_reference_sha256={runtime_comparison['reference_sha256']}")
        print(f"runtime_artifact_candidate_sha256={runtime_comparison['candidate_sha256']}")
        print(f"runtime_artifact_hashes_equal={runtime_comparison['equal']}")
        if _context['runtime_profile_mode'] == "selected-runtime-object" and not runtime_comparison["equal"]:
            _context['mark_aborted'](
                "runtime artifact parity mismatch",
                "selected runtime objects differ: "
                f"reference SHA-256 {runtime_comparison['reference_sha256']}, "
                f"candidate SHA-256 {runtime_comparison['candidate_sha256']}",
            )
    return record["fingerprint_sha256"]
