"""Bind the trusted pool_await runtime marker to its exact declaration position."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text()


def function_text(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        text,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


annotations = source("src/backend/codegen_struct_table.elisa")
producer = source("src/backend/codegen_module.elisa")
consumer = source("src/backend/codegen_generic_inference/trusted_runtime_calls.elisa")
smoke = source("test/parity/submit_store_capture_smoke.sh")
control = source("test/parity/submit_store_capture_control.elisa")

annotation_start = annotations.find("pool_await_runtime_lines: mutable darray[u32] = []")
annotation_end = annotations.find("pool_await_runtime_offsets: mutable darray[u32] = []")
if annotation_start < 0 or annotation_end <= annotation_start:
    raise SystemExit("pool_await runtime marker must store line and offset side by side")

producer_start = producer.find("structs.annotations.pool_await_runtime_lines.push(await_pos.line)")
producer_end = producer.find("structs.annotations.pool_await_runtime_offsets.push(await_pos.offset)")
if producer_start < 0 or producer_end <= producer_start:
    raise SystemExit("runtime marker producer must store both fields from await_pos")

consumer_body = function_text(consumer, "backend_is_trusted_pool_await_call")
line_count_guard = consumer_body.find(
    "pool_await_runtime_lines.count != structs.annotations.pool_await_runtime_offsets.count"
)
position_join = consumer_body.find(
    "pool_await_runtime_lines[runtime_row] == function_pos.line and structs.annotations.pool_await_runtime_offsets[runtime_row] == function_pos.offset"
)
if line_count_guard < 0 or position_join < 0 or line_count_guard >= position_join:
    raise SystemExit("pool_await runtime trust must fail closed and match the exact declaration position")

if 'python3 "$ROOT/test/proofs/check_pool_await_runtime_identity.py"' not in smoke:
    raise SystemExit("submit store smoke must run the pool_await runtime identity proof")
if "pool_await(move first_task)" not in control:
    raise SystemExit("positive submit control must continue exercising the bundled pool_await consumer")
