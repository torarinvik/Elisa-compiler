#!/usr/bin/env python3
"""Focused tests for the host-side WASM ABI and binding generator."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.wasm_build import (
    WasmBuildError,
    build,
    js_bindings,
    load_export_scan,
    main,
    parse_exports,
    read_flat_source,
    runtime_cache_path,
    type_declaration,
    write_text_if_changed,
    _resolve_llc_executable,
    _resolve_native_object_merger,
    _runtime_cache_entry_valid,
    _runtime_cache_observer_requested,
    _runtime_cache_directory_ready,
    _runtime_object_from_cache,
    _publish_runtime_cache,
)
from scripts.wasm_export_scan_client import (
    MAX_PROCESS_SNAPSHOT_BYTES,
    MAX_PROCESS_SNAPSHOT_ROWS,
    PROCESS_RSS_LIMIT_BYTES,
    WasmExportScanClientError,
    _decode_build_payload,
    _decode_flatten_payload,
    _process_tree_rss_bytes,
    _read_process_snapshot,
    _validate_exports,
    run_export_scan,
    run_flatten_source,
)
from scripts.wasm_export_scan import MAX_FLATTENED_SOURCE_BYTES, MAX_SOURCE_LINES
from scripts.wasm_facade import js_input, js_output, ts_type


_BOUNDED_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "wasm_bounded_stage1_command",
    ROOT / "test/parity/run_bounded_stage1_command.py",
)
assert _BOUNDED_RUNNER_SPEC is not None
assert _BOUNDED_RUNNER_SPEC.loader is not None
bounded_runner = importlib.util.module_from_spec(_BOUNDED_RUNNER_SPEC)
sys.modules[_BOUNDED_RUNNER_SPEC.name] = bounded_runner
_BOUNDED_RUNNER_SPEC.loader.exec_module(bounded_runner)



__all__ = [name for name in globals() if not name.startswith("__")]
