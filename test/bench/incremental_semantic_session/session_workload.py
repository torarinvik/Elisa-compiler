"""Build and decode incremental semantic benchmark workloads."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Any


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())

def fixture(
    functions: int,
    edit_version: int,
    payload_mode: str,
    add_surface_function: bool = False,
    post_surface_fact_transition: bool = False,
) -> str:
    pieces = [
        "# Many cacheable, independent bodies make the collector's reuse path visible.\n\n",
    ]
    if payload_mode == "call-facts":
        for index in range(functions):
            pieces.append(f"def fact_leaf_{index:04d}() -> i64:\n    return {index}\n\n")
        pieces.append("def fact_leaf_alt() -> i64:\n    return 999\n\n")
    elif payload_mode == "shared-calls":
        pieces.append("def shared_fact_leaf() -> i64:\n    return 700\n\n")
        pieces.append("def shared_fact_leaf_alt() -> i64:\n    return 701\n\n")
    for index in range(functions):
        if post_surface_fact_transition and index == 0 and payload_mode in {"call-facts", "shared-calls"}:
            body = "    return 42\n"
        elif payload_mode == "call-facts":
            target = "fact_leaf_alt" if index == 0 and edit_version % 2 == 1 else f"fact_leaf_{index:04d}"
            body = f"    return {target}()\n"
        elif payload_mode == "shared-calls":
            target = "shared_fact_leaf_alt" if index == 0 and edit_version % 2 == 1 else "shared_fact_leaf"
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

def timing_arm_kinds(pair_index: int) -> tuple[bool, bool]:
    """Return routing/timing order, counterbalanced across adjacent pairs."""
    return (True, False) if pair_index % 2 == 0 else (False, True)

def mode_environment(mode: str) -> dict[str, str]:
    """Return the explicit resolver/query-graph switches for one benchmark arm."""
    if mode == "graph-off":
        return {
            "ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH": "0",
            "ELISA_STAGE1_INCREMENTAL_NAME_LOOKUP_DIRECT": "0",
        }
    if mode == "graph-on":
        return {
            "ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH": "1",
            "ELISA_STAGE1_INCREMENTAL_NAME_LOOKUP_DIRECT": "0",
        }
    if mode == "direct-surface":
        return {
            "ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH": "1",
            "ELISA_STAGE1_INCREMENTAL_NAME_LOOKUP_DIRECT": "1",
        }
    raise ValueError(f"unknown semantic-session benchmark mode: {mode}")

def three_mode_order(pair_index: int, workload_index: int, *, timing: bool = False) -> tuple[str, ...]:
    """Rotate the opt-in three-arm order so no resolver mode is always first."""
    modes = ("graph-off", "graph-on", "direct-surface")
    offset = (pair_index + workload_index + (1 if timing else 0)) % len(modes)
    return modes[offset:] + modes[:offset]
