"""Derived-state backend rows and lookups retain the owning module."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


ast = read("src/parser/ast_side_tables.elisa")
parser = read("src/parser/parser_types_struct.elisa")
table = read("src/backend/codegen_struct_table.elisa")
collector = read("src/backend/codegen_module.elisa")
lookup_source = read("src/backend/codegen_env.elisa")
runtime_consumer = read("src/backend/codegen_expr_optional_binary.elisa")
annotation_consumer = read("src/backend/codegen_annotation_index.elisa")
fixture = read("test/repro/derived_state_module_identity.elisa")
smoke = read("test/parity/derived_state_module_identity_smoke.sh")

if "module_name: sview @source = \"\"" not in ast or "module_name: parser.current_module" not in parser:
    raise SystemExit("derived-state AST/parser must preserve the declaring module")
if "derived_state_modules: mutable darray[sview] = []" not in table or \
        "derived_state_modules <- structs.annotations.derived_state_modules.push(derived_rule.module_name)" not in collector:
    raise SystemExit("backend derived-state rows must retain module identity in an aligned side table")

lookup_start = lookup_source.find("def derived_state_rule_index(")
lookup_end = lookup_source.find("\n\n\n", lookup_start)
lookup = lookup_source[lookup_start:lookup_end]
if lookup_start < 0 or not all(fragment in lookup for fragment in (
    "module_name: sview",
    "rule_count != structs.annotations.derived_state_modules.count",
    "structs.annotations.derived_state_modules[probe] == resolved_module",
    "return exact_index if exact_count == 1.usize()",
    "structs.visibility.current_owner <- module_name",
    "resolved_type: ValueType = resolve_type_head(owner, structs)",
    "structs.visibility.current_owner <- saved_owner",
    "resolved_module: sview = struct_owner_at(structs, resolved_type.bits.usize())",
)):
    raise SystemExit("derived-state lookup must use the resolved struct owner and fail closed without a local rule")
if "return unique_index if unique_count" in lookup:
    raise SystemExit("derived-state lookup must not reuse a unique same-leaf rule from another module")

if "derived_state_rule_index(structs, ds_type_name, ds_state_name, structs.visibility.current_owner)" not in runtime_consumer:
    raise SystemExit("runtime derived-state tests must pass their lexical module to rule lookup")
if "derived_state_rule_index(structs, container_name, named_state, structs.visibility.current_owner)" not in annotation_consumer:
    raise SystemExit("derived-state annotation erasure must pass its resolved module to rule lookup")

if not all(fragment in fixture for fragment in (
    "struct Gauge[state Active]",
    "module Left:",
    "module Right:",
    "Active when self.value == 42",
    "Active when self.value > 0",
    "Active when self.value < 0",
    "return value is Gauge[Active]",
    "value: Gauge[Active]",
)):
    raise SystemExit("regression fixture must cover same-leaf opposite predicates and annotation lookup")
shadow_fixture = read("test/repro/derived_state_wrong_owner.neg.elisa")
if not all(fragment in shadow_fixture for fragment in (
    "struct Gauge[state Active]",
    "module Left:",
    "Ready when self.value > 0",
    "def root_cannot_borrow_left_ready(value: Gauge) -> bool:",
    "value is Gauge[Ready]",
)):
    raise SystemExit("shadow regression must give the root type no state while a module has the unique same-leaf rule")
if "derived_state_module_identity.elisa" not in smoke or \
        "derived_state_wrong_owner.neg.elisa" not in smoke or \
        'for optimization in 0 2' not in smoke:
    raise SystemExit("behavioral smoke must cover cross-module predicates and reject a foreign same-leaf state at O0 and O2")

print("backend derived-state module identity source proof OK")
