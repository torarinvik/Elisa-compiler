"""Region-parameter and body-derived arena ABI rows retain function identity."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


ast = read("src/parser/ast_side_tables.elisa")
parser = read("src/parser/parser_types_function.elisa")
table = read("src/backend/codegen_struct_table_side_tables.elisa")
collector = read("src/backend/codegen_module.elisa")
regions = read("src/backend/codegen_abi_regions.elisa")
region_facts = read("src/backend/codegen_region_forwarding/dependencies.elisa")
runtime = read("src/backend/codegen_runtime_types.elisa")
runtime_copy = read("src/backend/codegen_convert.elisa")
declaration_facts = read("src/backend/codegen_decl_facts.elisa")
body = read("src/backend/codegen_declare.elisa")
generic_inference = read("src/backend/codegen_generic_inference.elisa")
generic_layout = read("src/backend/codegen_packed_meta.elisa")
call = read("src/backend/codegen_call.elisa")
new_expr = read("src/backend/codegen_expr_literals.elisa")
in_block = read("src/backend/codegen_stmt_blocks_exprs.elisa")
var_decl = read("src/backend/codegen_stmt_vardecl_emit.elisa")
source_queries = read("src/backend/codegen_env_source_queries.elisa")
signature = read("src/backend/codegen_declare_signature.elisa")
fixture = read("test/repro/region_parameter_owner_offset.elisa")
pin_fixture = read("test/repro/region_local_pin_owner_offset.elisa")
fact_fixture = read("test/repro/region_fact_owner_offset.elisa")
cross_module_fact_fixture = read("test/repro/region_fact_cross_module_owner.elisa")
generic_fact_fixture = read("test/repro/region_generic_owner_offset.elisa")
smoke = read("test/parity/region_parameter_owner_offset_smoke.sh")

if "owner_offset: u32" not in ast or \
        'name: "__region_param"' not in parser or \
        "owner_offset: function_offset" not in parser:
    raise SystemExit("parser region-parameter rows must retain their function declaration offset")
if "region_param_owner_offsets: mutable darray[u32] = []" not in table or \
        "region_param_owner_offsets <- structs.regions.region_param_owner_offsets.push(region_annotation.owner_offset + 1)" not in collector:
    raise SystemExit("backend collection must normalize parser owner offsets into the function offset+1 domain")
if "local_region_offsets: mutable darray[u32] = []" not in table or \
        "local_region_offsets <- structs.regions.local_region_offsets.push(region_annotation.owner_offset)" not in collector or \
        "local_region_name_at(var_line.line, var_line.offset, structs)" not in var_decl or \
        "structs.regions.local_region_offsets[probe] != offset" not in source_queries:
    raise SystemExit("local arena pins must retain the exact declaration token offset")

if "def region_parameter_count(line: u32, owner_offset: u32" not in regions or \
        "region_param_owner_offsets[row] == owner_offset" not in regions or \
        "row_count != structs.regions.region_param_owner_offsets.count" not in regions:
    raise SystemExit("hidden arena slots must count only aligned rows owned by the exact function")
if "def region_parameter_index(line: u32, owner_offset: u32, name: sview, caller_region_parameter_start: i64" not in regions or \
        "region_param_owner_offsets[row] != owner_offset" not in regions:
    raise SystemExit("named region selectors must resolve inside the exact function's region list")
if "region_fact_offsets: mutable darray[u32] = []" not in table or \
        "region_fact_offsets <- structs.regions.region_fact_offsets.push(region_fact_line.offset + 1)" not in region_facts:
    raise SystemExit("body-derived arena rows must normalize declaration offsets into the function offset+1 domain")
if "region_fact_row_from_params(name, owner, params, line, owner_offset, structs)" not in regions or \
        "region_fact_names[row.usize()] == name" not in regions or \
        "region_fact_owners[row.usize()] == owner" not in regions or \
        "region_fact_offsets[row.usize()] == owner_offset" not in regions or \
        "structs.visibility.current_owner <- owner" not in regions:
    raise SystemExit("body-derived arena flags must select the exact name, module, and declaration position")
if "def region_bind_template_placeholders(name: sview, owner: sview, line: u32, owner_offset: u32" not in region_facts or \
        "generics.owners[template_slot] != owner" not in region_facts or \
        "template_line.offset + 1 == owner_offset" not in region_facts or \
        "region_bind_template_placeholders(region_fact_name, owner, region_fact_line.line, region_fact_line.offset + 1" not in region_facts or \
        "region_bind_template_placeholders(region_forward_fact_name, owner, region_forward_fact_line.line, region_forward_fact_line.offset + 1" not in region_facts:
    raise SystemExit("generic placeholder binding must use the exact lexical owner and normalized declaration offset at both fact scans")
if "region_flags_for_function(function_name, lexical_owner, params, body, line, offset" not in signature or \
        "region_flags_for_function(name, owner, params, body, line, owner_offset" not in regions or \
        "instantiation_arena_layout(function_name, instantiation_arena_owner, params, body, line.line, line.offset + 1," not in read("src/backend/codegen_packed_meta.elisa"):
    raise SystemExit("ordinary and generic signatures must pass explicit lexical owner and function name into body-fact lookup")
if "region_fact_row(region_forward_fact_name, owner, region_forward_fact_line.line, region_forward_fact_line.offset + 1, structs)" not in region_facts or \
        "region_fact_owners[row.usize()] == owner" not in regions:
    raise SystemExit("forwarding fact visits must resolve the exact function owner and normalized offset")
if "signature_arena_count(function_name, lexical_owner, params, return_value_type, body, line, offset, structs)" not in signature or \
        "signature_arena_count(function_name, owner, params, return_value_type, body, function_line_of(declaration), function_offset_of(declaration), structs)" not in body:
    raise SystemExit("signature and body ABI counts must receive the normalized declaration offset")
if "Decl.Func(function_name, params, return_type_opt, body, effects, decorators, line): line.offset + 1" not in declaration_facts or \
        "declare_function_impl(function_name, params, return_type_opt, body, effects, decorators, line.line, line.offset + 1" not in signature:
    raise SystemExit("function declaration and ABI rows must share the established offset+1 identity convention")
if "function_offset: mutable u32 = 0" not in runtime or \
        "local_runtime.function_offset <- function_offset_of(declaration)" not in body or \
        "function_offset: runtime.function_offset" not in runtime_copy or \
        "caller_region_parameter_start: mutable i64 = -1" not in runtime or \
        "caller_region_parameter_start: runtime.caller_region_parameter_start" not in runtime_copy or \
        "function_parameter_region_count(fns, function_region_row).i64()" not in body or \
        "value_type_returns_caller_region(return_value_type, structs) and not params_manage_arena(params, structs)" not in body:
    raise SystemExit("runtime copies must carry the explicit-region suffix base after hidden parameter and return slots")
if "region_parameter_index(runtime.function_line, runtime.function_offset, region_new_name, runtime.caller_region_parameter_start, structs)" not in new_expr or \
        "region_parameter_index(runtime.function_line, runtime.function_offset, block_clause[0], runtime.caller_region_parameter_start, structs)" not in in_block or \
        "region_parameter_index(runtime.function_line, runtime.function_offset, pinned_region, runtime.caller_region_parameter_start, structs)" not in var_decl or \
        "pinned_arena <- runtime.caller_arenas[pinned_parameter_index.usize()]" not in var_decl:
    raise SystemExit("region allocation, block selectors, and declaration pins must resolve the current function's hidden slot")
if "inst_arena_region_parameter_starts: mutable darray[i64]" not in generic_inference or \
        "instantiation_arena_layout(function_name, instantiation_arena_owner, params, body, line.line, line.offset + 1, instantiation_needs_arena, structs, instantiation_param_slots, instantiation_region_parameter_start)" not in generic_layout or \
        "generics.inst_arena_region_parameter_starts <- generics.inst_arena_region_parameter_starts.push(instantiation_region_parameter_start)" not in generic_layout or \
        "count <- count + 1.usize() if returns_region" not in generic_layout or \
        "region_parameter_start <- count.i64()" not in generic_layout or \
        "count <- count + region_parameter_count(line, owner_offset, structs)" not in generic_layout:
    raise SystemExit("generic arena layouts must append explicit region slots after parameter and return slots")
if "fns.offsets[index.usize()]" not in call or \
        "region_parameter_count(fns.lines[index.usize()], fns.offsets[index.usize()], structs)" not in call:
    raise SystemExit("region-only call matching must count parameters from the exact FnTable owner")

if fixture.count("#line 0 region-parameter-owner.elisa") != 2 or not all(fragment in fixture for fragment in (
    "def read_r[@r]",
    "def allocate_s[@s]",
    "new[s] value",
    "def allocate_after_hidden[@r](young: mutable darray[i64]&, old: mutable darray[i64]&",
    "-> mutable darray[i64] @r:",
    "old.push(allocated[0])",
    "result.push(allocated[0])",
    "in r:",
    "new[r] value",
    "region inner(1024):",
    "result <- allocate_after_hidden[outer](young, old, 41)",
    "read_r[caller](anchor) + allocate_s[caller](anchor, 41) == 43",
)):
    raise SystemExit("regression must collide region owners and verify selectors after hidden parameter and return slots")
if fact_fixture.count("#line 0 region-fact-owner.elisa") != 2 or not all(fragment in fact_fixture for fragment in (
    "def value_count(values: darray[i64]&) -> usize:",
    "def append_value(values: mutable darray[i64]&) -> void:",
    "values.push(42)",
)):
    raise SystemExit("region fact regression must collide same-line, same-arity functions with different growth flags")
if cross_module_fact_fixture.count("#line 0 region-fact-cross-module.elisa") != 2 or not all(fragment in cross_module_fact_fixture for fragment in (
    "module Left:",
    "module Right:",
    "def act(values: darray[i64]&) -> usize:",
    "def act(values: mutable darray[i64]&) -> void:",
    "Right::act(&values)",
    "Left::act(values) == 1",
)):
    raise SystemExit("cross-module regression must pair same-line, same-name, same-arity facts by their lexical owner")
if generic_fact_fixture.count("#line 0 region-generic-owner.elisa") != 2 or not all(fragment in generic_fact_fixture for fragment in (
    "module ReadOwner:",
    "module GrowOwner:",
    "def mutate[T](values: darray[T]&, value: T) -> bool:",
    "def mutate[Element](values: mutable darray[Element]&, value: Element) -> void:",
    "values.push(value)",
    "GrowOwner::mutate[i64](&values, 42)",
    "ReadOwner::mutate[i64](values, 0)",
)):
    raise SystemExit("generic regression must distinguish same-line same-name templates by owner and formal bindings")
if "region_parameter_owner_offset" not in smoke or \
        "region_local_pin_owner_offset" not in smoke or \
        "region_fact_owner_offset" not in smoke or \
        "region_fact_cross_module_owner" not in smoke or \
        "region_generic_owner_offset" not in smoke or \
        "for optimization in 0 2" not in smoke:
    raise SystemExit("behavioral smoke must run both same-line region ABI regressions")
if pin_fixture.count("#line 0 ") != 2 or "result: mutable darray[i64] @r = []" not in pin_fixture or \
        "result: mutable darray[i64] @s = []" not in pin_fixture or \
        "target[outer](young, 42)" not in pin_fixture or "result[0] == 42" not in pin_fixture:
    raise SystemExit("local pin regression must collide declaration lines across distinct region owners")

print("region ABI owner offset source proof OK")
