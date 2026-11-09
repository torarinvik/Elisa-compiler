"""Runtime checks for the semantic parallel-pass audit."""
import collections
from functools import lru_cache
import os
import re
import sys


def generated_parallel_errors(_services, info):
    """Validate generated pipeline ranges against the dispatcher's ordered pass IDs."""
    api = _services['read_pipeline_source'](_services['API'])
    passes = open(_services['PASSES'], encoding="utf-8").read()
    parallel = open(os.path.join(_services['SRC'], "semantic", "semantic_parallel.elisa"), encoding="utf-8").read()
    errors = []
    api_lines = api.splitlines()
    all_calls, malformed_lines = _services['par_run_calls'](api_lines)
    for line_number in malformed_lines:
        errors.append("semantic_api.elisa:%d: par_pass_run call does not match the generated call shape" % line_number)
    lines, start, end, _params = _services['pipeline_statements']()
    _lines, _flags, _stmts, sequential_runs = _services['plan_runs'](info)
    pipeline_calls, _pipeline_malformed = _services['par_run_calls'](lines[start:end], start)
    errors.extend(_services['pipeline_scratch_errors'](lines, start, end, pipeline_calls))
    if _services['has_mixed_generated_and_sequential_runs'](lines, start, end, sequential_runs):
        errors.append("semantic_api.elisa: mixed generated batches and sequential eligible runs; regenerate from a fully sequential pipeline")
    pipeline_line_numbers = set(range(start, end))
    outside_calls = [call for call in all_calls if call["line"] not in pipeline_line_numbers]
    if outside_calls:
        errors.append("semantic_api.elisa: par_pass_run call found outside check_full_into_pipeline")
    if not pipeline_calls:
        errors.append("semantic_api.elisa: no generated par_pass_run calls found")
    if any(call["match"].group(3) is None for call in pipeline_calls):
        errors.append("semantic_api.elisa: generated par_pass_run call is missing its typed loop view")
    if any(call["match"].group(2) is None for call in pipeline_calls):
        errors.append("semantic_api.elisa: par_pass_run calls must explicitly update the lmut table")
    counts = [call["count"] for call in pipeline_calls]
    max_batch = max(counts, default=1)
    bound = re.search(r"^\s*const PAR_PASS_MAX_BATCH: usize = (\d+)\s*$", passes, re.M)
    if bound is None:
        errors.append("semantic_parallel_passes.elisa: missing PAR_PASS_MAX_BATCH")
    elif int(bound.group(1)) != max_batch:
        errors.append("semantic_parallel_passes.elisa: PAR_PASS_MAX_BATCH does not match the largest run")

    pipeline_ids = []
    for call in pipeline_calls:
        if call["count"] <= 0:
            errors.append("semantic_api.elisa:%d: generated par_pass_run count must be positive" % (call["line"] + 1))
            continue
        if call["start"] < 0:
            errors.append("semantic_api.elisa:%d: generated par_pass_run start must not be negative" % (call["line"] + 1))
        pipeline_ids.extend(range(call["start"], call["start"] + call["count"]))
    if pipeline_ids != list(range(len(pipeline_ids))):
        errors.append("semantic_api.elisa: generated pass ranges must cover IDs once, in pipeline order, starting at 0")

    dispatch, dispatch_errors = _services['parse_parallel_dispatch'](passes)
    errors.extend(dispatch_errors)
    dispatch_ids = [record["id"] for record in dispatch]
    errors.extend(_services['parallel_dispatch_chunk_errors'](passes, pipeline_ids))
    if dispatch_ids != pipeline_ids:
        errors.append("semantic_parallel_passes.elisa: dispatcher pass IDs/order do not match semantic_api.elisa ranges")
    if len({record["id"] for record in dispatch}) != len(dispatch):
        errors.append("semantic_parallel_passes.elisa: duplicate dispatcher pass ID")
    # Names, arguments, and conditions are parsed as one record per ID. The generated pipeline
    # retains only batch ranges, so only IDs and their order can be independently compared here.
    for record in dispatch:
        if not record["name"] or not record["args"].strip():
            errors.append("semantic_parallel_passes.elisa: incomplete dispatcher mapping for pass_id %d" % record["id"])
    safe_ids = {
        record["id"] for record in dispatch
        if _services['append_only'](info, record["name"])[0]
    }
    errors.extend(_services['parallel_safety_gate_errors'](passes, safe_ids))
    errors.extend(_services['parallel_runtime_serial_guard_errors'](parallel))
    errors.extend(_services['parallel_runtime_lmut_errors'](parallel, passes))
    errors.extend(_services['parallel_runtime_view_errors'](parallel))


    _lines, _start, _end, params = _services['pipeline_statements']()
    expected_flags = [p for p in params if p not in _services['PIPELINE_CONTEXT']]
    flag_struct = re.search(r"struct ParPassFlags:\n((?:\s{12}\w+: [^\n]+\n)+)", passes)
    actual_flags = re.findall(r"^\s{12}(\w+):", flag_struct.group(1), re.M) if flag_struct else []
    if actual_flags != expected_flags:
        errors.append("semantic_parallel_passes.elisa: ParPassFlags does not match pipeline scalar flags")
    flag_init = re.search(r"^\s*flags: ParPassFlags\s*=\s*ParPassFlags\{([^}]+)\}", api, re.M)
    initialized_flags = re.findall(r"\b(\w+):", flag_init.group(1)) if flag_init else []
    if initialized_flags != expected_flags:
        errors.append("semantic_api.elisa: ParPassFlags initializer does not match pipeline scalar flags")
    if not re.search(r"def par_pass_run\[[^\]]*@pool[^\]]*\]\([^\n]*shared_pool: mutable ThreadPool& @pool, loop_view: Ast::File", parallel):
        errors.append("semantic_parallel.elisa: par_pass_run must borrow the shared pool in the caller's region")
    return errors

def parallel_runtime_view_errors(_services, source):
    """Require a typed job copy and a worker borrow, rather than a parameter address."""
    errors = []
    lines = source.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^[ \t]*struct ParPassJob:", line)), None)
    block = []
    if start is not None:
        indent = len(lines[start]) - len(lines[start].lstrip())
        for line in lines[start + 1:]:
            if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= indent:
                break
            block.append(line)
    if not any(re.fullmatch(r"[ \t]+loop_view: Ast::File[ \t]*", line) for line in block):
        errors.append("semantic_parallel.elisa: ParPassJob must hold a typed loop view")
    if not re.search(r"jobs\.push\(ParPassJob\{[^\n}]*loop_view:[ \t]*loop_view(?:,|\})", source):
        errors.append("semantic_parallel.elisa: each job must initialize its typed loop view from the pipeline view")
    if not re.search(r"view: Ast::File& = &job\.loop_view", source):
        errors.append("semantic_parallel.elisa: workers must borrow the loop view in their joined job record")
    if re.search(r"\bview_bits[ \t]*:|\bjob\.view_bits\b", source):
        errors.append("semantic_parallel.elisa: raw loop-view descriptor addresses must not be retained")
    return errors

def pipeline_scratch_errors(_services, lines, start, end, calls):
    """Check typed-view initialization; retain legacy slot checks for migration."""
    # Historical slot-shaped calls remain parseable for migration and old fixtures.
    # New calls must use the single typed view initialized before any dispatch.
    view_calls = [call for call in calls if call["match"].group(3) == "loop_view"]
    if view_calls:
        errors = []
        if len(view_calls) != len(calls):
            errors.append("semantic_api.elisa: mixed typed-view and scratch-slot calls")
        declarations = [i for i in range(start, end)
                        if re.match(r"^[ \t]*loop_view: Ast::File = semantic_loop_view\(file\)[ \t]*$", lines[i])]
        if len(declarations) != 1:
            errors.append("semantic_api.elisa: initialize exactly one typed loop_view")
        elif any(call["line"] <= declarations[0] for call in calls):
            errors.append("semantic_api.elisa: loop_view must be initialized before par_pass_run")
        if any(re.match(r"\s*\w+:\s*mutable darray\[ParPassScratch\[", lines[i]) for i in range(start, end)):
            errors.append("semantic_api.elisa: typed-view calls must not allocate obsolete scratch slots")
        return errors
    scratch_decl_re = re.compile(
        r"^[ \t]*(\w+):[ \t]*mutable darray\[ParPassScratch\[pool\]\][ \t]*@pool[ \t]*=[ \t]*"
        r"\[[ \t]*ParPassScratch\[pool\]\{[ \t]*loop_view:[ \t]*loop_view[ \t]*\}[ \t]*\][ \t]*$"
    )
    declarations = []
    for line_number in range(start, end):
        match = scratch_decl_re.fullmatch(lines[line_number])
        if match:
            declarations.append((line_number, match.group(1)))
    if len(declarations) != 1:
        return ["semantic_api.elisa: check_full_into_pipeline must initialize exactly one pool-owned ParPassScratch slot"]

    declaration_line, slot_name = declarations[0]
    errors = []
    for call in calls:
        expression = call["match"].group(3) or ""
        slot = re.fullmatch(r"&([A-Za-z_]\w*)\[0\]", expression)
        if slot is None:
            errors.append("semantic_api.elisa:%d: par_pass_run must borrow the initialized scratch slot at index 0" % (call["line"] + 1))
        elif slot.group(1) != slot_name:
            errors.append("semantic_api.elisa:%d: par_pass_run references a different scratch slot than the initialized one" % (call["line"] + 1))
        elif call["line"] <= declaration_line:
            errors.append("semantic_api.elisa:%d: scratch slot must be initialized before par_pass_run" % (call["line"] + 1))
    return errors

def listed_passes(_services):
    if not os.path.exists(_services['PASSES']):
        return []
    return re.findall(r"table <- (\w+)\(", open(_services['PASSES'], encoding="utf-8").read())
