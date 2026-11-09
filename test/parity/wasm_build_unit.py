#!/usr/bin/env python3
"""Focused tests for the host-side WASM ABI and binding generator."""
import unittest

from wasm_bindings_reference_tests import WasmBindingsTests, WasmReferenceSourceBoundsTests
from wasm_export_payload_tests import WasmExportScanClientTests
from wasm_scanner_selection_tests import ExportScannerSelectionTests
from wasm_runtime_cache_tests import RuntimeObjectCacheTests
from wasm_bounded_command_tests import BoundedStage1CommandTests


if __name__ == "__main__":
    unittest.main()
