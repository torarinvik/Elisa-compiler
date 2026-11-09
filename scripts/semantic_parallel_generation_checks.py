"""Generation checks for the semantic parallel-pass audit."""
import collections
from functools import lru_cache
import os
import re
import sys


def parallel_safety_gate_source(_services, safe_ids):
    """Emit a fail-closed whitelist for pass IDs proven safe by the source audit."""
    ids = sorted(set(safe_ids))
    lines = [_services['PARALLEL_GATE_BEGIN'],
             "        def par_pass_is_append_only(pass_id: u32) -> bool:"]
    ranges = []
    for pass_id in ids:
        if ranges and pass_id == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], pass_id)
        else:
            ranges.append((pass_id, pass_id))
    for first, last in ranges:
        if first == last:
            condition = "pass_id == %d" % first
        elif first == 0:
            condition = "pass_id <= %d" % last
        else:
            condition = "pass_id >= %d and pass_id <= %d" % (first, last)
        lines.append("            return true if " + condition)
    lines.append("            return false")
    lines.append(_services['PARALLEL_GATE_END'])
    return "\n".join(lines)

def refresh_parallel_safety_gate(_services, source, safe_ids):
    """Replace or append the audit-generated pass-ID whitelist in the dispatcher."""
    start = source.find(_services['PARALLEL_GATE_BEGIN'])
    end = source.find(_services['PARALLEL_GATE_END'])
    generated = _services['parallel_safety_gate_source'](safe_ids)
    if start < 0 and end < 0:
        return source.rstrip() + "\n\n" + generated + "\n"
    if start < 0 or end < start or source.find(_services['PARALLEL_GATE_BEGIN'], start + 1) >= 0:
        raise ValueError("malformed generated append-only gate markers")
    end += len(_services['PARALLEL_GATE_END'])
    return source[:start] + generated + source[end:]

def parallel_safety_gate_errors(_services, source, safe_ids):
    """Require the generated whitelist to exactly match the append-only audit."""
    start = source.find(_services['PARALLEL_GATE_BEGIN'])
    end = source.find(_services['PARALLEL_GATE_END'])
    if start < 0 or end < start or source.find(_services['PARALLEL_GATE_BEGIN'], start + 1) >= 0:
        return ["semantic_parallel_passes.elisa: missing or malformed generated append-only gate"]
    actual = source[start:end + len(_services['PARALLEL_GATE_END'])].strip()
    expected = _services['parallel_safety_gate_source'](safe_ids).strip()
    if actual != expected:
        return ["semantic_parallel_passes.elisa: append-only ID gate does not exactly match the audited dispatcher"]
    return []

def parallel_runtime_serial_guard_errors(_services, source):
    """Check unsafe pass IDs take the ordered dispatcher path before any worker submits."""
    lines = source.splitlines()
    start = next((index for index, line in enumerate(lines)
                  if re.match(r"^[ \t]*def par_pass_run\[", line)), None)
    if start is None:
        return ["semantic_parallel.elisa: missing par_pass_run"]
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= indent:
            break
        end += 1
    body_lines = lines[start:end]
    body = "\n".join(body_lines)
    errors = []
    def find_line(pattern, after=0):
        return next((index for index in range(after, len(body_lines))
                     if re.search(pattern, body_lines[index])), None)

    def line_indent(index):
        line = body_lines[index]
        return len(line) - len(line.lstrip())

    def next_code_line(index):
        return next((candidate for candidate in range(index + 1, len(body_lines))
                     if body_lines[candidate].strip()
                     and not body_lines[candidate].lstrip().startswith("#")), None)

    gate = find_line(r"if not par_pass_is_append_only\(first\s*\+\s*offset\):")
    gate_assignment = find_line(r"unsafe_pass\s*<-\s*true", gate + 1 if gate is not None else 0)
    gate_loop = next((index for index in range(gate - 1, -1, -1)
                      if re.search(r"for offset in 0\.\.<count:", body_lines[index])), None) if gate is not None else None
    serial = find_line(r"if count < 2 or shared_pool\.handle == null or unsafe_pass:")
    serial_loop = find_line(r"for offset in 0\.\.<count", serial + 1 if serial is not None else 0)
    call = find_line(
        r"table <- par_pass_call\[destination\]\(first\s*\+\s*offset, file, &loop_view, flags, table\)",
        serial_loop + 1 if serial_loop is not None else 0,
    )
    return_line = find_line(r"^\s*return\s*$", call + 1 if call is not None else 0)
    worker = find_line(r"nursery on\(shared_pool\):")
    region = find_line(r"region par_pass_jobs_region:")
    jobs = find_line(r"jobs: mutable darray\[ParPassJob\] @par_pass_jobs_region = \[\]")
    initialization = find_line(r"^\s*unsafe_pass: mutable\s+bool = false\s*$")
    if None in (
        gate, gate_assignment, gate_loop, serial, serial_loop, call, return_line,
        worker, region, jobs, initialization,
    ):
        errors.append("semantic_parallel.elisa: unsafe pass IDs or batch-local job storage are not guarded by the serial dispatcher path")
    else:
        base_indent = line_indent(initialization)
        ordered = initialization < gate_loop < gate < gate_assignment < serial < serial_loop < call < return_line < region < jobs < worker
        expected_indents = {
            initialization: base_indent,
            gate_loop: base_indent,
            gate: base_indent + 4,
            gate_assignment: base_indent + 8,
            serial: base_indent,
            serial_loop: base_indent + 4,
            call: base_indent + 8,
            return_line: base_indent + 4,
            region: base_indent,
            jobs: base_indent + 4,
            worker: base_indent + 4,
        }
        if not ordered:
            errors.append("semantic_parallel.elisa: serial dispatcher must return before worker submission")
        elif any(line_indent(index) != expected for index, expected in expected_indents.items()):
            errors.append("semantic_parallel.elisa: serial gate, loop, and return indentation bypasses the unsafe-pass branch")
        elif any(next_code_line(parent) != child for parent, child in (
            (initialization, gate_loop),
            (gate_loop, gate),
            (gate, gate_assignment),
            (gate_assignment, serial),
            (serial, serial_loop),
            (serial_loop, call),
            (call, return_line),
            (return_line, region),
            (region, jobs),
        )):
            errors.append("semantic_parallel.elisa: serial guard statements are not nested under their required parent branches")
    return errors

def parallel_runtime_lmut_errors(_services, source, passes):
    """Check parallel dispatch keeps the caller's explicit table region."""
    line = next((line for line in source.splitlines()
                 if re.match(r"^[ \t]*def par_pass_run\[", line)), None)
    if line is None:
        return ["semantic_parallel.elisa: missing par_pass_run"]
    errors = []
    if not re.search(r"\btable:[ \t]*mutable SymbolTable&[ \t]*@\w+,", line):
        errors.append("semantic_parallel.elisa: par_pass_run must borrow the caller's table descriptor in a named region")
    if not re.search(
        r"def par_pass_call\[@table_region\]\(pass_id: u32, file: Ast::File&, loop_view: Ast::File&, flags: ParPassFlags, table: mutable SymbolTable& @table_region\) -> void can\[Unsafe\{PointerArithmetic,PointerCast,RawExtern\}\]:",
        passes,
    ):
        errors.append("semantic_parallel_passes.elisa: dispatcher must tie its table borrow to an explicit named region and preserve its Unsafe effect requirement")
    if not re.search(r"\(&frozen_table\)\.cast\[mutable void&\], table\.cast\[void&\], size_of\(SymbolTable\)", source):
        errors.append("semantic_parallel.elisa: par_pass_run must copy bytes from the borrowed table descriptor")
    if not re.search(
        r"table <- par_pass_call\[destination\]\(first \+ offset, file, &loop_view, flags, table\) can Global\{Read,Write\}, Unsafe\{PointerArithmetic,PointerCast,RawExtern\}",
        source,
    ):
        errors.append("semantic_parallel.elisa: serial dispatcher must instantiate the caller's table region and grant its required effects")
    if not re.search(r"table <- par_pass_parent_diagnostic\[destination\]\(source_bits, table\)", source):
        errors.append("semantic_parallel.elisa: parent diagnostic splice must instantiate its explicit table region")
    if not re.search(
        r"table <- par_pass_call\(job\.pass_id, file, view, job\.flags, table\) can Global\{Read,Write\}, Unsafe\{PointerArithmetic,PointerCast,RawExtern\}",
        source,
    ):
        errors.append("semantic_parallel.elisa: worker dispatcher call must explicitly update its local table and grant its required effects")
    if not re.search(r"\) -> void:", line):
        errors.append("semantic_parallel.elisa: par_pass_run must mutate the borrowed table in place")
    return errors

def passes_source(_services, flags, calls, max_batch):
    head = """# Stage1 semantic layer — the passes semantic_parallel.elisa may run concurrently, by id.
# GENERATED by scripts/semantic_parallel_gen.py --write from the sequential pipeline in
# semantic_api.elisa (check_full_into_pipeline); `--check` audits every pass below for append-only behavior.
# Ids follow pipeline order, which is the order par_pass_run splices diagnostics in.
#
# Continues semantic_api.elisa.

extend Semantic:
    private:
"""
    _lines, start, _end, _params = _services['pipeline_statements']()
    types = dict((p.split(":", 1)[0].strip(), p.split(":", 1)[1].strip()) for p in _services['DEF_RE'].match(_lines[start]).group(3).split(","))
    body = ["        # Largest generated batch; the shared semantic pool is capped to this size.",
            "        const PAR_PASS_MAX_BATCH: usize = %d" % max_batch,
            "",
            "        # check_full_into_pipeline's flags, for the passes' arguments and conditions.",
            "        struct ParPassFlags:"]
    body += ["            %s: %s" % (f, types[f]) for f in flags]
    signature = "(pass_id: u32, file: Ast::File&, loop_view: Ast::File&, flags: ParPassFlags, table: mutable SymbolTable& @table_region) -> void:"
    body += ["",
             "        def par_pass_call[@table_region]" + signature[:-1] + " can[Unsafe{PointerArithmetic,PointerCast,RawExtern}]:",
             "            can Memory.Allocate, Abort.Panic, Global{Read,Write}, Unsafe{PointerArithmetic,PointerCast,RawExtern}:"]
    chunks = [
        calls[start:start + _services['PAR_PASS_DISPATCH_CHUNK_SIZE']]
        for start in range(0, len(calls), _services['PAR_PASS_DISPATCH_CHUNK_SIZE'])
    ]
    for chunk_index, chunk in enumerate(chunks):
        first, last = chunk[0][0], chunk[-1][0]
        condition = "pass_id <= %d" % last if first == 0 else "pass_id >= %d and pass_id <= %d" % (first, last)
        body.append("                if %s:" % condition)
        body.append(
            "                    table <- par_pass_call_chunk_%d(pass_id, file, loop_view, flags, table)"
            % chunk_index
        )
    for chunk_index, chunk in enumerate(chunks):
        body += ["",
                 "        def par_pass_call_chunk_%d[@table_region]%s" % (chunk_index, signature),
                 "            can Memory.Allocate, Abort.Panic:"]
        for pid, s in chunk:
            flag_names = r"(?<!\.)\b(" + "|".join(flags) + r")\b" if flags else ""
            args = re.sub(flag_names, r"flags.\1", s["args"]) if flags else s["args"]
            suffix = s.get("suffix", "")
            if suffix and flags:
                suffix = re.sub(flag_names, r"flags.\1", suffix)
            # pass_id is immutable and IDs are unique. Each helper owns a bounded range.
            body.append("                if pass_id == %d:" % pid)
            call = "table <- %s(%s)%s" % (s["name"], args, (" " + suffix) if suffix else "")
            scope = s.get("scope", "")
            if scope:
                body.append("                    %s:" % scope)
                body.append("                        " + call)
            else:
                body.append("                    " + call)
    body.extend(["", _services['parallel_safety_gate_source'](pid for pid, _statement in calls)])
    return head + "\n".join(body) + "\n"

def parallel_dispatch_chunk_errors(_services, source, expected_ids):
    """Verify chunk helpers and their range checks form an exact dispatch cover."""
    lines = source.splitlines()
    chunk_defs = set()
    base = None
    for index, line in enumerate(lines):
        match = re.match(r"^[ \t]*def (par_pass_call(?:_chunk_(\d+))?)(?:\[[^\]\n]+\])?\(", line)
        if match is None:
            continue
        if match.group(2) is None:
            base = index
        else:
            chunk_defs.add(int(match.group(2)))
    if not chunk_defs:
        return []
    if not expected_ids:
        return ["semantic_parallel_passes.elisa: chunk helpers exist for an empty dispatcher"]

    errors = []
    expected_chunks = [
        (index, expected_ids[start], expected_ids[min(start + _services['PAR_PASS_DISPATCH_CHUNK_SIZE'], len(expected_ids)) - 1])
        for index, start in enumerate(range(0, len(expected_ids), _services['PAR_PASS_DISPATCH_CHUNK_SIZE']))
    ]
    expected_defs = {index for index, _first, _last in expected_chunks}
    if chunk_defs != expected_defs:
        errors.append("semantic_parallel_passes.elisa: dispatcher chunk helper set does not match the pass count")
    if base is None:
        return errors + ["semantic_parallel_passes.elisa: missing top-level chunk dispatcher"]

    base_indent = len(lines[base]) - len(lines[base].lstrip())
    end = base + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= base_indent:
            break
        end += 1

    if not any(
        re.fullmatch(
            r"[ \t]*can Memory\.Allocate, Abort\.Panic, Global\{Read,Write\}, Unsafe\{PointerArithmetic,PointerCast,RawExtern\}:[ \t]*",
            _services['strip_comments'](lines[index]),
        )
        for index in range(base + 1, end)
    ):
        errors.append("semantic_parallel_passes.elisa: chunk dispatcher must locally grant helper Global and Unsafe effects")
    if not re.search(
        r"def par_pass_call\[@table_region\]\(pass_id: u32, file: Ast::File&, loop_view: Ast::File&, flags: ParPassFlags, table: mutable SymbolTable& @table_region\) -> void can\[Unsafe\{PointerArithmetic,PointerCast,RawExtern\}\]:",
        lines[base],
    ):
        errors.append("semantic_parallel_passes.elisa: chunk dispatcher must preserve its inferred Unsafe effect requirement")

    actual_chunks = []
    for index in range(base + 1, end):
        code = _services['strip_comments'](lines[index])
        condition = re.fullmatch(r"[ \t]*if pass_id <= (\d+):[ \t]*", code)
        if condition is not None:
            first, last = 0, int(condition.group(1))
        else:
            condition = re.fullmatch(
                r"[ \t]*if pass_id >= (\d+) and pass_id <= (\d+):[ \t]*",
                code,
            )
            if condition is None:
                continue
            first, last = int(condition.group(1)), int(condition.group(2))
        indent = len(lines[index]) - len(lines[index].lstrip())
        body = []
        for body_index in range(index + 1, end):
            line = lines[body_index]
            code = _services['strip_comments'](line).strip()
            if not code:
                continue
            if len(line) - len(line.lstrip()) <= indent:
                break
            body.append(code)
        if len(body) != 1:
            errors.append("semantic_parallel_passes.elisa:%d: chunk range must have exactly one dispatch call" % (index + 1))
            continue
        call = re.fullmatch(
            r"table <- par_pass_call_chunk_(\d+)\(pass_id, file, loop_view, flags, table\)",
            body[0],
        )
        if call is None:
            errors.append("semantic_parallel_passes.elisa:%d: chunk range has an unrecognized dispatch call" % (index + 1))
            continue
        actual_chunks.append((int(call.group(1)), first, last))

    expected_set = set(expected_chunks)
    if len(actual_chunks) != len(expected_chunks) or set(actual_chunks) != expected_set:
        errors.append("semantic_parallel_passes.elisa: chunk range checks do not dispatch every pass exactly once")
    chunk_calls = [
        line for line in lines[base:end]
        if re.search(r"\bpar_pass_call_chunk_\d+\(", _services['strip_comments'](line))
    ]
    if len(chunk_calls) != len(expected_chunks):
        errors.append("semantic_parallel_passes.elisa: chunk helper calls do not match the checked ranges")
    return errors

def refresh_max_batch(_services, source, max_batch):
    """Update only the generated pool bound while preserving an existing pass dispatcher."""
    line = "        const PAR_PASS_MAX_BATCH: usize = %d" % max_batch
    pattern = re.compile(r"^[ \t]*const PAR_PASS_MAX_BATCH: usize = \d+[ \t]*$")
    lines = source.splitlines()
    for index, existing in enumerate(lines):
        if pattern.fullmatch(existing):
            lines[index] = line
            next_line = index + 1
            while next_line < len(lines) and not lines[next_line].strip():
                next_line += 1
            lines[index + 1:next_line] = [""]
            return "\n".join(lines) + ("\n" if source.endswith("\n") else "")
    private = next((i for i, existing in enumerate(lines) if re.fullmatch(r"[ \t]*private:[ \t]*", existing)), None)
    if private is None:
        raise ValueError("cannot find private section in generated semantic pass file")
    lines[private + 1:private + 1] = [line, ""]
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")

def refresh_pass_flags(_services, source, flags):
    """Refresh the flag record shape without regenerating its audited dispatch body."""
    _lines, start, _end, _params = _services['pipeline_statements']()
    types = dict((p.split(":", 1)[0].strip(), p.split(":", 1)[1].strip())
                 for p in _services['DEF_RE'].match(_lines[start]).group(3).split(","))
    fields = "\n".join("            %s: %s" % (flag, types[flag]) for flag in flags)
    pattern = re.compile(r"(^        struct ParPassFlags:\n)(?:^[ \t]+\w+: [^\n]*\n)*", re.M)
    updated, count = pattern.subn(lambda m: m.group(1) + fields + "\n", source, count=1)
    if count != 1:
        raise ValueError("cannot find ParPassFlags in generated semantic pass file")
    return updated

def refresh_dispatch_table_region(_services, source):
    """Tie the generated dispatcher borrow to an explicit region parameter."""
    lines = source.splitlines()
    matches = [index for index, line in enumerate(lines)
               if re.match(r"^[ \t]*def par_pass_call(?:\[[^\]\n]+\])?\(", line)]
    if len(matches) != 1:
        raise ValueError("expected exactly one par_pass_call dispatcher signature")
    index = matches[0]
    indent = lines[index][:len(lines[index]) - len(lines[index].lstrip())]
    expected = (
        indent + "def par_pass_call[@table_region](pass_id: u32, file: Ast::File&, loop_view: Ast::File&, "
        "flags: ParPassFlags, table: mutable SymbolTable& @table_region) -> void can[Unsafe{PointerArithmetic,PointerCast,RawExtern}]:"
    )
    accepted = {
        indent + "def par_pass_call(pass_id: u32, file: Ast::File&, loop_view: Ast::File&, "
        "flags: ParPassFlags, table: lmut SymbolTable) -> void:",
        indent + "def par_pass_call[@table_region](pass_id: u32, file: Ast::File&, loop_view: Ast::File&, "
        "flags: ParPassFlags, table: lmut SymbolTable& @table_region) -> void:",
        indent + "def par_pass_call[@table_region](pass_id: u32, file: Ast::File&, loop_view: Ast::File&, "
        "flags: ParPassFlags, table: mutable SymbolTable& @table_region) -> void:",
        expected,
    }
    if lines[index] not in accepted:
        raise ValueError("unrecognized par_pass_call dispatcher signature")
    lines[index] = expected
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")
