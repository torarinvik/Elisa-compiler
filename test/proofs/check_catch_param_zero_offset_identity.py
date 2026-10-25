"""Bind Catch ErrorSet parameter lookup to exact declaration byte offsets."""
from __future__ import annotations

import argparse
from pathlib import Path
import re


parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
parser.parse_args()

ROOT = Path(__file__).resolve().parents[2]
CPB_SOURCE = (ROOT / "src/semantic/check_catch_param_binder.elisa").read_text()
INFERENCE_SOURCE = (ROOT / "src/semantic/check_errorset_param_inference.elisa").read_text()
PARSER_SOURCE = (ROOT / "src/parser/parser_types_function.elisa").read_text()
FIXTURE = (ROOT / "test/repro/catch_param_zero_offset_identity.elisa").read_text()
INFERENCE_FIXTURE = (ROOT / "test/repro/errorset_param_zero_offset_identity.elisa").read_text()
SMOKE = (ROOT / "test/parity/catch_param_zero_offset_identity_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


cpb_lookup = function_source(CPB_SOURCE, "cpb_errorset_param")
index_builder = function_source(CPB_SOURCE, "cpb_collect_errorset_params")
inference_lookup = function_source(INFERENCE_SOURCE, "errorset_param_at")
generic_capture = function_source(PARSER_SOURCE, "capture_function_generic_params")
if not all(fragment in cpb_lookup for fragment in (
        "offsets[index] == function_offset",
        "modules[index] != function_module",
        "return exact_name if exact_count == 1.usize()",
        "return \"\"")) or "offsets[index] == 0" in cpb_lookup or "legacy_count" in cpb_lookup:
    raise SystemExit("Catch must match the exact function byte offset; zero is not a missing-offset sentinel")
if "for annotation in annotations |lines, offsets, names, modules|" not in index_builder or "modules.push(annotation.module)" not in index_builder:
    raise SystemExit("Catch's ErrorSet parameter index must carry module identity in its parallel columns")
if not all(fragment in inference_lookup for fragment in (
        "annotation.offset == function_offset",
        "annotation.module != function_module",
        "return exact_name if exact_count == 1.usize()",
        "return \"\"")) or "annotation.offset == 0" in inference_lookup or "legacy_count" in inference_lookup:
    raise SystemExit("ErrorSet parameter inference must not reuse a byte-zero row for another #line declaration")
if "errorset_param_at(annotations, line.line, line.offset, current_module)" not in INFERENCE_SOURCE:
    raise SystemExit("ErrorSet parameter inference must query the generic row by the owning declaration's exact module and offset")
if 'offset: function_offset' not in generic_capture or 'parser.capture_function_generic_params(token.line, token.start, lexical_module_id)' not in PARSER_SOURCE:
    raise SystemExit("parser ErrorSet parameter rows must retain the owning function token's exact byte offset")
if not FIXTURE.startswith("def opaque[errorset R](callback: fn() -> i64 error[R])") or not all(fragment in FIXTURE for fragment in (
        "#line 1 catch-param-zero-offset.elisa",
        "def concrete(callback: fn() -> i64 error[Fault])",
        "opaque_error:",
        "plain:")):
    raise SystemExit("zero-offset fixture must pair a byte-zero generic function with a later same-logical-line concrete function")
if not INFERENCE_FIXTURE.startswith("def generic[errorset R]() -> i64 error[R]:") or not all(fragment in INFERENCE_FIXTURE for fragment in (
        "#line 1 errorset-param-zero-offset.elisa",
        "def concrete() -> i64:",
        "def call_concrete() -> i64:",
        "return concrete()")):
    raise SystemExit("ErrorSet inference fixture must exercise a zero-parameter call after a byte-zero generic declaration on the same logical line")
if not all(fragment in SMOKE for fragment in (
        "catch_param_zero_offset_identity.elisa",
        "errorset_param_zero_offset_identity.elisa",
        "opaque error-set parameter component",
        'diagnostic_count\" != 1',
        'cannot infer error-set parameter "R" for call to "concrete"')):
    raise SystemExit("zero-offset smoke must retain only the generic function's opaque-ErrorSet binder diagnostic")

print("Catch ErrorSet parameter exact-offset source binding passed")
