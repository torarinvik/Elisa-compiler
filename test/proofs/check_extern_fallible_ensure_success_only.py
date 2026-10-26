"""Guard success-only result reads for fallible extern boundary ensures."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
CALL = (ROOT / "src/backend/codegen_call_direct.elisa").read_text()
GOOD = (ROOT / "test/fixtures/backend/extern_fallible_ensure_good.elisa").read_text()
BAD = (ROOT / "test/fixtures/backend/extern_fallible_ensure_bad.elisa").read_text()
FAIL = (ROOT / "test/fixtures/backend/extern_fallible_ensure_unwritten_failure.elisa").read_text()
STUB = (ROOT / "test/fixtures/backend/extern_fallible_ensure.c").read_text()
SMOKE = (ROOT / "test/parity/extern_fallible_ensure_smoke.sh").read_text()


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def check_sources() -> None:
    call = compact(CALL)
    start = call.index("ifensure_applies:")
    end = call.index("returnsret_slot", start)
    block = call[start:end]
    status = block.index("error_status_code(call_result,ctx,builder)")
    branch = block.index("LLVMBuildCondBr(builder,ensure_success,ensure_check_block,ensure_merge_block)")
    check_block = block.index("LLVMPositionBuilderAtEnd(builder,ensure_check_block)")
    load = block.index('LLVMBuildLoad2(builder,llvm_type_of(call_return_type,structs,ctx),error_out_slot,"call.error.ensure")')
    checks = block.index("emit_extern_ensure_checks(fn_index,ensure_arguments,ensure_hidden,ensure_result")
    merge = block.index("LLVMPositionBuilderAtEnd(builder,ensure_merge_block)")
    if not status < branch < check_block < load < checks < merge:
        raise SystemExit("fallible ensure must branch on status before loading result, and merge after success-only checks")
    if "ensure_result<-LLVMBuildLoad2(builder,llvm_type_of(call_return_type,structs,ctx),error_out_slot" in block[:check_block]:
        raise SystemExit("failure path can still read the unspecified fallible result out-slot")

    for source in (GOOD, BAD, FAIL):
        if "ensure result == 42" not in source or "i64 error[ProbeError]" not in source:
            raise SystemExit("all controls must declare the same fallible extern result postcondition")
    if "ProbeError.Failed: 7" not in FAIL:
        raise SystemExit("unwritten failure control must consume the original error status")
    stub = compact(STUB)
    if "*out=bad?41:42;return0;" not in stub or "(void)out;" not in stub or "return1;" not in stub:
        raise SystemExit("C controls must write good/bad success outputs and leave failure output unwritten")
    smoke = compact(SMOKE)
    for required in (
        "forcase_nameingoodbadunwritten_failure",
        "expected=7",
        "externpostconditionfailed",
        "elisa_run_timeout29",
        "elisa_run_timeout10",
        "--ir",
    ):
        if required not in smoke:
            raise SystemExit(f"focused smoke does not cover bounded good/bad/unwritten-failure checks: {required!r}")


def function_blocks(text: str) -> dict[str, list[str]]:
    function = re.search(r"(?ms)^define\s+[^\n]*@main\([^\n]*\)[^\n]*\{(.*?)^\}", text)
    if not function:
        raise SystemExit("failure fixture LLVM is missing main")
    blocks: dict[str, list[str]] = {"<entry>": []}
    current = "<entry>"
    for line in function.group(1).splitlines():
        label = re.match(r"^([-A-Za-z$._0-9]+):(?:\s*;.*)?$", line.strip())
        if label:
            current = label.group(1)
            blocks[current] = []
        else:
            blocks[current].append(line)
    return blocks


def assert_failure_cfg(ir_path: Path) -> None:
    blocks = function_blocks(ir_path.read_text())
    call_result = None
    call_block = None
    for label, lines in blocks.items():
        for line in lines:
            match = re.search(r"(%[-A-Za-z$._0-9]+)\s*=\s*(?:tail\s+)?call\s+(?:(?:zeroext|signext)\s+)?i32\s+@ensure_failure\(", line)
            if match:
                call_result, call_block = match.group(1), label
                break
    if call_result is None or call_block is None:
        raise SystemExit("main has no result-bearing i32 call to ensure_failure")

    condition = None
    for label, lines in blocks.items():
        for line in lines:
            match = re.search(r"(%[-A-Za-z$._0-9]+)\s*=\s*icmp\s+eq\s+i32\s+" + re.escape(call_result) + r"\s*,\s*0\b", line)
            if match:
                condition = match.group(1)
                break
        if condition:
            break
    if condition is None:
        raise SystemExit("failure status is not tested against zero before ensure evaluation")

    status_success = status_failure = None
    for lines in blocks.values():
        for line in lines:
            match = re.search(r"br\s+i1\s+" + re.escape(condition) + r"\s*,\s*label\s+%([-A-Za-z$._0-9]+)\s*,\s*label\s+%([-A-Za-z$._0-9]+)", line)
            if match:
                status_success, status_failure = match.group(1), match.group(2)
                break
        if status_success:
            break
    if status_success is None or status_failure is None:
        raise SystemExit("failure status comparison does not control a conditional branch")

    edges: dict[str, list[str]] = {label: [] for label in blocks}
    for label, lines in blocks.items():
        for line in lines:
            edges[label].extend(re.findall(r"label\s+%([-A-Za-z$._0-9]+)", line))

    def reachable(start: str) -> set[str]:
        seen: set[str] = set()
        pending = [start]
        while pending:
            label = pending.pop()
            if label in seen or label not in blocks:
                continue
            seen.add(label)
            pending.extend(edges[label])
        return seen

    success_reachable = reachable(status_success)
    failure_reachable = reachable(status_failure)
    ensure_load_blocks = {
        label for label, lines in blocks.items()
        if any(re.search(r"%call\.error\.ensure\s*=\s*load\b", line) for line in lines)
    }
    guard_blocks = {label for label in blocks if "contract.fail" in label}
    if not ensure_load_blocks or not success_reachable.intersection(ensure_load_blocks):
        raise SystemExit("status-zero successor cannot reach the success-result ensure load")
    if not success_reachable.intersection(guard_blocks):
        raise SystemExit("status-zero successor cannot reach the extern postcondition guard")
    if not failure_reachable.isdisjoint(ensure_load_blocks | guard_blocks):
        raise SystemExit("failure-status successor can reach the result load or extern postcondition guard")


if len(sys.argv) == 3 and sys.argv[1] == "--ir":
    check_sources()
    assert_failure_cfg(Path(sys.argv[2]))
    print("extern fallible ensure source and failure-CFG proof OK")
elif len(sys.argv) != 1:
    raise SystemExit("usage: check_extern_fallible_ensure_success_only.py [--ir failure.ll]")
else:
    check_sources()
    print("extern fallible ensure source proof OK")
