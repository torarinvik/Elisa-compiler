"""Source inspection and expected branch anchors for ownership proofs."""
import re


def compact_source(text):
    # Keep spaces inside strings, but remove comments and layout for stable source anchors.
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|#[^\r\n]*|\S', text)
    return "".join(token for token in tokens if not token.startswith("#"))

def source_function_raw(source, name):
    definition = re.search(rf"(?m)^\s*def\s+{re.escape(name)}(?=\[|\()", source)
    if not definition:
        raise SystemExit(f"production consumer function is missing: {name}")
    tail = source[definition.end():]
    following = re.search(r"(?m)^\s*def\s+", tail)
    end = definition.end() + following.start() if following else len(source)
    return source[definition.start():end]

def source_function(source, name):
    return compact_source(source_function_raw(source, name))

def source_field_lines(source, name, field):
    body = source_function_raw(source, name)
    return [compact_source(line) for line in body.splitlines() if re.search(rf"\b(?:literal|literal_guard)\.{field}\b", line)]

def source_reachability_writes(source, name):
    body = source_function_raw(source, name)
    return [compact_source(line) for line in body.splitlines() if ".reachable<-" in compact_source(line)]

def source_control_transfer_lines(source, name):
    body = source_function_raw(source, name)
    lines = []
    for line in body.splitlines():
        without_strings = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
        code = without_strings.split("#", 1)[0]
        if re.search(r"\b(return|break|continue)\b", code):
            lines.append(compact_source(line))
    return lines

def require_ordered(body, anchors, label):
    positions = [body.find(anchor) for anchor in anchors]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} changed or reordered a source-bound proof anchor")

def require_contiguous(body, fragments, label):
    expected = compact_source("\n".join(fragments))
    if expected not in body:
        raise SystemExit(f"{label} no longer preserves its exact branch transfer sequence")

def match_arm_signature(source, function_name, arm_header):
    """Return exact token lines with relative indentation for one match arm."""
    lines = source_function_raw(source, function_name).splitlines()
    for index, line in enumerate(lines):
        code = line.split("#", 1)[0].rstrip()
        if code.strip() != arm_header:
            continue
        base_indent = len(code) - len(code.lstrip(" "))
        signature = []
        for candidate in lines[index:]:
            code = candidate.split("#", 1)[0].rstrip()
            if not code.strip():
                continue
            indent = len(code) - len(code.lstrip(" "))
            if signature and indent <= base_indent:
                break
            signature.append((indent - base_indent, compact_source(code)))
        return tuple(signature)
    raise SystemExit(f"match arm is missing from {function_name}: {arm_header}")

def require_match_arm_structure(source, function_name, arm_header, expected, label):
    actual_signature = match_arm_signature(source, function_name, arm_header)
    expected_signature = match_arm_signature(
        "def fixture():\n" + "\n".join("    " + line for line in expected.splitlines()),
        "fixture",
        arm_header,
    )
    if actual_signature != expected_signature:
        raise SystemExit(f"{label} changed its branch body or nesting")

def direct_function_children(source, function_name):
    """Return normalized statements at the function body's direct indentation."""
    lines = source_function_raw(source, function_name).splitlines()
    definition = next((line for line in lines if line.lstrip().startswith("def ")), None)
    if definition is None:
        raise SystemExit(f"function definition is missing: {function_name}")
    function_indent = len(definition) - len(definition.lstrip(" "))
    child_indent = function_indent + 4
    children = []
    for line in lines:
        code = line.split("#", 1)[0].rstrip()
        if not code.strip() or len(code) - len(code.lstrip(" ")) != child_indent:
            continue
        children.append(compact_source(code))
    return children

def require_direct_function_children(source, function_name, expected, label):
    actual = direct_function_children(source, function_name)
    positions = [actual.index(compact_source(anchor)) if compact_source(anchor) in actual else -1
                 for anchor in expected]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} changed direct function-body nesting or order")

def nest_match_arm_under_guard(source, function_name, arm_header, guard):
    """Mutation fixture: wrap the complete arm body without changing its tokens."""
    function = source_function_raw(source, function_name)
    lines = function.splitlines()
    for index, line in enumerate(lines):
        code = line.split("#", 1)[0].rstrip()
        if code.strip() != arm_header:
            continue
        base_indent = len(code) - len(code.lstrip(" "))
        end = index + 1
        while end < len(lines):
            candidate = lines[end].split("#", 1)[0].rstrip()
            if candidate.strip() and len(candidate) - len(candidate.lstrip(" ")) <= base_indent:
                break
            end += 1
        rewritten = [lines[index], " " * (base_indent + 4) + guard]
        rewritten.extend("    " + row if row.strip() else row for row in lines[index + 1:end])
        return "\n".join(lines[:index] + rewritten + lines[end:])
    raise SystemExit(f"mutation fixture could not find {function_name}: {arm_header}")

def nest_function_tail_under_guard(source, function_name, start_line, guard):
    """Mutation fixture: guard every statement from START_LINE to function end."""
    function = source_function_raw(source, function_name)
    lines = function.splitlines()
    for index, line in enumerate(lines):
        code = line.split("#", 1)[0].rstrip()
        if compact_source(code) != compact_source(start_line):
            continue
        indent = len(code) - len(code.lstrip(" "))
        rewritten = [lines[index][:indent] + guard]
        rewritten.extend("    " + row if row.strip() else row for row in lines[index:])
        return "\n".join(lines[:index] + rewritten)
    raise SystemExit(f"mutation fixture could not find {function_name}: {start_line}")

consumer_sites = {
    "ownership_flow_expression": (2, 4, 3, (
        "literal=ownership_literal_bool(left)",
        "ifliteral.known:ownership_flow_expression(right,owner,table,flow,work,depth+1)if(operator==TokenKind.Andandliteral.value)or(operator==TokenKind.Orandnotliteral.value)",
        "literal=ownership_literal_bool(condition)",
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
    )),
    "ownership_flow_loop": (1, 2, 2, (
        "literal=ownership_literal_bool(condition)",
        "back.reachable<-back.reachableandliteral.valueifliteral.known",
        "elifliteral.knownandliteral.value:flow.reachable<-false",
    )),
    "ownership_flow_statements": (1, 2, 2, (
        "literal=ownership_literal_bool(condition)",
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
    )),
}

expected_known_lines = {
    "ownership_flow_expression": [
        "ifliteral.known:",
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
    ],
    "ownership_flow_loop": [
        "back.reachable<-back.reachableandliteral.valueifliteral.known",
        "elifliteral.knownandliteral.value:",
    ],
    "ownership_flow_statements": [
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
    ],
}

expected_reachability_writes = {
    "ownership_flow_expression": [
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
    ],
    "ownership_flow_loop": [
        "back.reachable<-back.reachableandliteral.valueifliteral.known",
        "flow.reachable<-false",
        "flow.reachable<-entry.reachable",
    ],
    "ownership_flow_statements": [
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
        "flow.reachable<-false",
    ],
}

expected_flow_control_transfers = {
    "ownership_flow_expression": [
        "returnifnotownership_flow_step(flow,work,depth)",
        "return",
        "return",
        "return",
    ],
    "ownership_flow_loop": ["return"],
    "ownership_flow_statements": ["returnifnotownership_flow_step(flow,work,depth)"],
}
