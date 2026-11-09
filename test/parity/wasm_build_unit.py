#!/usr/bin/env python3
"""Focused tests for the host-side WASM ABI and binding generator."""
import unittest

from wasm_build_cases_01 import WasmBindingsTests, WasmReferenceSourceBoundsTests
from wasm_build_cases_02 import WasmExportScanClientTests
from wasm_build_cases_03 import ExportScannerSelectionTests
from wasm_build_cases_04 import RuntimeObjectCacheTests
from wasm_build_cases_05 import BoundedStage1CommandTests


if __name__ == "__main__":
    unittest.main()
