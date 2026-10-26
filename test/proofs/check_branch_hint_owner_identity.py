"""Branch-prediction hints must belong to the exact if/while token."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text()


parser = source("src/parser/parser_stmt_control_flow.elisa")
backend_module = source("src/backend/codegen_module.elisa")
backend_structs = source("src/backend/codegen_struct_table.elisa")
backend_attrs = source("src/backend/codegen_attrs.elisa")
backend_branching = source("src/backend/codegen_stmt_branching.elisa")
smoke = source("test/parity/backend_smoke_ir.sh")

if 'owner: "__branch_hint", name: hint_kind, line: token.line, offset: token.start' not in parser:
    raise SystemExit("if/elif hint rows must retain the if token offset")
if 'owner: "__branch_hint", name: hint_kind, line: while_token.line, offset: while_token.start' not in parser:
    raise SystemExit("while hint rows must retain the while token offset")
if "branch_hint_offsets: mutable darray[u32] = []" not in backend_structs:
    raise SystemExit("backend branch-hint table must preserve offsets")
if "branch_hint_offsets <- structs.annotations.branch_hint_offsets.push(annotation.offset)" not in backend_module:
    raise SystemExit("backend marker collection must retain the parser offset")
lookup_start = backend_attrs.find("def branch_hint_for(")
lookup_end = backend_attrs.find("\n\n", lookup_start)
lookup = backend_attrs[lookup_start:lookup_end]
if "line: u32, offset: u32" not in lookup or \
        "branch_hint_lines[index] == line and structs.annotations.branch_hint_offsets[index] == offset" not in lookup:
    raise SystemExit("branch-hint lookup must match the exact source position")
if "branch_hint_for(structs, if_line.line, if_line.offset)" not in backend_branching or \
        "branch_hint_for(structs, while_line.line, while_line.offset)" not in backend_branching:
    raise SystemExit("if and while lowering must query by their exact AST positions")
if "branch_hint_same_line_likely" not in smoke or "branch_hint_same_line_unlikely" not in smoke or \
        "#line 0 branch-hint-owner.elisa" not in smoke or "if likely a:" not in smoke or "if unlikely b:" not in smoke:
    raise SystemExit("IR smoke must cover both opposite hints on one logical line")
