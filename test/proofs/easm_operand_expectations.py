"""Expected operand scanning contracts and proof claims."""


expected_result_type = """
struct InstructionScanResult:
    start: usize
    count: usize
    first_separator: usize
    last_separator: usize
    has_address_group: bool
    address_open: usize
    address_close: usize
    valid: bool
"""

classifier_groups = {
    "is_zero_operand_instruction": (
        ("ret", "retq", "cpuid", "cld", "std"),
        ("lfence", "rdtsc", "pause", "yield", "isb"),
        ("emms", "vzeroall", "trap"),
    ),
    "is_one_operand_instruction": (
        ("push", "pushq", "pop", "popq"),
        ("inc", "incq", "dec", "decq", "neg", "negq", "not", "notq"),
        ("call", "callq", "jmp", "jmpq"),
        ("je", "jz", "jne", "jnz", "jl", "jle", "jg", "jge", "jb", "jbe", "ja", "jae"),
        ("fldcw", "fnstcw", "stmxcsr", "ldmxcsr"),
    ),
    "is_two_operand_instruction": (
        ("mov", "movq", "movb", "movw", "movl"),
        ("movsx", "movsxd", "movsbw", "movsbl", "movsbq", "movswl", "movswq", "movslq"),
        ("movzx", "movzbw", "movzbl", "movzbq", "movzwl", "movzwq"),
        ("lea", "leaq", "xchg", "xchgl", "xchgq"),
        ("add", "addq", "sub", "subq"),
        ("and", "andq", "or", "orq", "xor", "xorq"),
        ("cmp", "cmpq", "test", "testq", "mrs"),
    ),
    "is_shift_instruction": (("shl", "shlq", "sal", "salq", "shr", "shrq", "sar", "sarq"),),
}

expected_operand_arity = """
def operand_arity_supported(op: sview, operand_count: usize) -> bool:
    ensure result == (
        (is_zero_operand_instruction(op) and operand_count == 0) or
        (not is_zero_operand_instruction(op) and is_one_operand_instruction(op) and operand_count == 1) or
        (not is_zero_operand_instruction(op) and not is_one_operand_instruction(op) and is_two_operand_instruction(op) and operand_count == 2) or
        (not is_zero_operand_instruction(op) and not is_one_operand_instruction(op) and not is_two_operand_instruction(op) and is_shift_instruction(op) and (operand_count == 1 or operand_count == 2))
    )
    return (
        (is_zero_operand_instruction(op) and operand_count == 0) or
        (not is_zero_operand_instruction(op) and is_one_operand_instruction(op) and operand_count == 1) or
        (not is_zero_operand_instruction(op) and not is_one_operand_instruction(op) and is_two_operand_instruction(op) and operand_count == 2) or
        (not is_zero_operand_instruction(op) and not is_one_operand_instruction(op) and not is_two_operand_instruction(op) and is_shift_instruction(op) and (operand_count == 1 or operand_count == 2))
    )
"""

expected_mrs_form = """
def is_aarch64_mrs_form(result_register: sview, system_register: sview) -> bool:
    ensure result == (
        system_register == "cntvct_el0" and
        (result_register == "xzr" or
            (result_register.len == 2 and result_register[0] == ASCII_X and
                result_register[1] >= ASCII_ZERO and result_register[1] <= ASCII_NINE) or
            (result_register.len == 3 and result_register[0] == ASCII_X and
                (((result_register[1] == ASCII_ONE or result_register[1] == ASCII_TWO) and
                    result_register[2] >= ASCII_ZERO and result_register[2] <= ASCII_NINE) or
                    (result_register[1] == ASCII_THREE and result_register[2] == ASCII_ZERO)))
        )
    )
    return (
        system_register == "cntvct_el0" and
        (result_register == "xzr" or
            (result_register.len == 2 and result_register[0] == ASCII_X and
                result_register[1] >= ASCII_ZERO and result_register[1] <= ASCII_NINE) or
            (result_register.len == 3 and result_register[0] == ASCII_X and
                (((result_register[1] == ASCII_ONE or result_register[1] == ASCII_TWO) and
                    result_register[2] >= ASCII_ZERO and result_register[2] <= ASCII_NINE) or
                    (result_register[1] == ASCII_THREE and result_register[2] == ASCII_ZERO)))
        )
    )
"""

expected_exact_register = """
def exact_register_form(operand: sview, register_name: sview) -> bool:
    ensure result == (
        (operand.len == register_name.len + SCAN_STEP and
            operand.len > 0 and operand[0] == ASCII_PERCENT and
            operand[SCAN_STEP:operand.len] == register_name) or
        (operand.len == register_name.len + INDIRECT_REGISTER_PREFIX_LENGTH and
            operand.len >= INDIRECT_REGISTER_PREFIX_LENGTH and operand[0] == ASCII_STAR and
            operand[1] == ASCII_PERCENT and
            operand[INDIRECT_REGISTER_PREFIX_LENGTH:operand.len] == register_name)
    )
    return (
        (operand.len == register_name.len + SCAN_STEP and
            operand.len > 0 and operand[0] == ASCII_PERCENT and
            operand[SCAN_STEP:operand.len] == register_name) or
        (operand.len == register_name.len + INDIRECT_REGISTER_PREFIX_LENGTH and
            operand.len >= INDIRECT_REGISTER_PREFIX_LENGTH and operand[0] == ASCII_STAR and
            operand[1] == ASCII_PERCENT and
            operand[INDIRECT_REGISTER_PREFIX_LENGTH:operand.len] == register_name)
    )
"""

expected_direct_target = """
def is_direct_control_target(op: sview, operand: sview, is_final_operand: bool) -> bool:
    ensure result == (
        is_final_operand and operand.len > 0 and
        operand[0] != ASCII_PERCENT and operand[0] != ASCII_DOLLAR and
        operand[0] != ASCII_STAR and operand[0] != ASCII_LEFT_PAREN and
        operand[0] != ASCII_LEFT_BRACKET and
        EasmTextScan::find(operand, ":") == operand.len and
        (op == "call" or op == "callq" or op == "jmp" or op == "jmpq" or
            op == "je" or op == "jz" or op == "jne" or op == "jnz" or
            op == "jl" or op == "jle" or op == "jg" or op == "jge" or
            op == "jb" or op == "jbe" or op == "ja" or op == "jae")
    )
    return is_final_operand and operand.len > 0 and operand[0] != ASCII_PERCENT and operand[0] != ASCII_DOLLAR and operand[0] != ASCII_STAR and operand[0] != ASCII_LEFT_PAREN and operand[0] != ASCII_LEFT_BRACKET and EasmTextScan::find(operand, ":") == operand.len and (op == "call" or op == "callq" or op == "jmp" or op == "jmpq" or op == "je" or op == "jz" or op == "jne" or op == "jnz" or op == "jl" or op == "jle" or op == "jg" or op == "jge" or op == "jb" or op == "jbe" or op == "ja" or op == "jae")
"""

role_expectations = {
    "easm_operand_is_direct_register": "return operand.len > 0 and operand[0] == EasmOperandScan::ASCII_PERCENT and EasmOperandScan::exact_register_form(operand, register) and easm_register_bit(register) != 0",
    "easm_operand_is_segment_register": 'return operand == "%fs" or operand == "%gs"',
    "easm_operand_is_supported_memory": 'base_supported: bool = base == "" or base == "rip" or easm_register_bit(base) != 0 index_supported: bool = index == "" or (easm_register_bit(index) != 0 and easm_register_bit(index) != EasmRegisterMasks::RSP) return base_supported and index_supported',
    "easm_operand_is_data_source": "return easm_operand_is_direct_register(operand) or easm_operand_is_supported_memory(operand) or easm_operand_is_immediate(operand)",
    "easm_operand_is_writable": "return easm_operand_is_direct_register(operand) or easm_operand_is_supported_memory(operand)",
    "easm_move_operand_roles_supported": "return false if source_segment and destination_segment if source_segment: return easm_operand_is_writable(destination) if destination_segment: return (easm_operand_is_direct_register(source) or easm_operand_is_supported_memory(source)) and not easm_operand_is_immediate(source) return easm_operand_is_data_source(source) and easm_operand_is_writable(destination)",
    "easm_operand_is_control_target": "return true if EasmOperandScan::is_direct_control_target(op, operand, true) and not easm_memory_operand(operand) false return if not easm_is_call_or_unconditional_jump(op) false return if operand.len < EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH or operand[0] != EasmOperandScan::ASCII_STAR indirect_operand: sview = easm_trim(operand[1:operand.len]) return easm_operand_is_direct_register(indirect_operand) or easm_operand_is_supported_memory(indirect_operand)",
    "easm_instruction_operand_roles_supported": "if op == \"push\" or op == \"pushq\": return easm_operand_is_data_source(source) or easm_operand_is_segment_register(source) if op == \"pop\" or op == \"popq\": return easm_operand_is_writable(destination) or easm_operand_is_segment_register(destination)",
}

required_label_lookup = (
    "ensure result >= -1",
    "ensure target.len == 0 implies result == -1",
    "ensure result >= 0 implies result.usize() < instructions.count",
    "ensure result >= 0 implies instructions[result.usize()].op == \"label\" and easm_equal(easm_label_name(instructions[result.usize()]), target)",
    "ensure result >= 0 implies (forall prior in 0..<result.usize(): instructions[prior].op != \"label\" or not easm_equal(easm_label_name(instructions[prior]), target))",
    "ensure (instructions.count.i64() >= 0 and instructions.count.i64().usize() == instructions.count and result == -1 and target.len > 0) implies (forall candidate in 0..<instructions.count: instructions[candidate].op != \"label\" or not easm_equal(easm_label_name(instructions[candidate]), target))",
    "return -1 if target.len == 0 or count_signed < 0 or count_signed.usize() != count",
    "for index in 0..<count |count, instructions, target|:",
    "invariant forall prior in 0..<index: instructions[prior].op != \"label\" or not easm_equal(easm_label_name(instructions[prior]), target)",
    "if instructions[index].op == \"label\" and easm_equal(easm_label_name(instructions[index]), target):",
    "return found_index",
    "assert forall candidate in 0..<count: instructions[candidate].op != \"label\" or not easm_equal(easm_label_name(instructions[candidate]), target)",
)

positive_names = {
    "indexed_address_commas_stay_inside_one_operand",
    "three_top_level_operands_exceed_the_modeled_limit",
    "a_single_indexed_memory_operand_has_arity_one",
    "unmatched_address_parenthesis_fails_closed",
    "unmatched_closing_parenthesis_fails_closed",
    "nested_address_parentheses_fail_closed",
    "no_operand_instruction_has_zero_operands",
    "scan_records_exact_top_level_separator_prefix",
    "valid_scan_exposes_only_its_delimited_address_pair",
    "first_operand_byte_is_the_least_non_whitespace",
    "next_separator_is_the_first_comma_outside_address",
    "zero_operand_opcode_classifier_matches_its_exact_set",
    "modeled_arity_matches_zero_operand_opcode_class",
    "zero_operand_ret_arity_is_accepted",
    "unary_push_arity_is_accepted",
    "binary_move_arity_is_accepted",
    "one_operand_shift_arity_is_accepted",
    "two_operand_shift_arity_is_accepted",
    "mrs_arity_is_binary",
    "direct_register_token_is_recognized_exactly",
    "indirect_register_token_is_recognized_exactly",
    "segment_address_is_not_a_register_token",
    "exact_register_form_matches_its_complete_token_equation",
    "direct_control_target_classifier_matches_its_exact_set",
    "direct_call_symbol_target_is_classified_as_control",
    "conditional_symbol_target_is_classified_as_control",
    "aarch64_mrs_form_classifier_matches_x0_through_x30_and_xzr",
    "mrs_accepts_low_x_register",
    "mrs_accepts_high_x_register",
    "mrs_accepts_zero_register",
    "bare_symbol_data_operands_are_rejected",
    "direct_call_symbol_targets_are_exempt_from_data_operand_rejection",
    "register_immediate_and_address_operands_are_modeled",
    "immediate_return_operands_are_rejected",
    "conditional_jump_targets_require_local_labels_or_explicit_authorization",
    "segment_address_is_not_an_exact_register_operand",
}

negative_names = {
    "indexed_address_has_four_operands",
    "three_top_level_operands_are_supported",
    "unmatched_address_parenthesis_is_valid",
    "invalid_scan_preserves_address_group_metadata",
    "zero_operand_scan_has_non_sentinel_separator",
    "single_operand_scan_has_an_empty_operand",
    "next_separator_selects_a_comma_inside_address",
    "cpuid_is_not_a_zero_operand_instruction",
    "movq_is_a_zero_operand_instruction",
    "movq_with_one_operand_is_accepted",
    "incq_with_two_operands_is_accepted",
    "mrs_with_one_operand_is_accepted",
    "register_suffix_is_accepted_as_the_exact_register",
    "bare_register_name_is_accepted_as_att_syntax",
    "register_operand_is_classified_as_a_direct_target",
    "immediate_operand_is_classified_as_a_direct_target",
    "nonfinal_symbol_is_classified_as_a_direct_target",
    "mrs_accepts_x31",
    "mrs_accepts_zero_padded_x09",
    "mrs_accepts_general_purpose_w_register",
    "mrs_accepts_unsupported_system_register",
    "nested_address_parentheses_are_valid",
    "bare_data_symbol_is_accepted",
    "immediate_return_is_stack_neutral",
    "unresolved_conditional_target_is_always_accepted",
}

scan_decl = "scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction(text)"

expected_positive = {
    "indexed_address_commas_stay_inside_one_operand": (
        'ensure result == true text: sview = "movq (%rax,%rcx,8), %rbx" ' + scan_decl + ' return ( scan.valid and scan.count == 2 and '
        'text[scan.start:scan.first_separator] == "(%rax,%rcx,8)" and '
        'text[scan.last_separator + 1.usize():text.len] == "%rbx" )'
    ),
    "three_top_level_operands_exceed_the_modeled_limit": (
        'ensure result == true text: sview = "shld %cl, %rbx, (%rax)" ' + scan_decl + ' return scan.valid and scan.count == 3 and '
        'EasmOperandScan::needs_arity_rejection(scan.count)'
    ),
    "a_single_indexed_memory_operand_has_arity_one": (
        'ensure result == true text: sview = "callq *(%rax,%rcx,8)" ' + scan_decl + ' return scan.valid and scan.count == 1 and '
        'not EasmOperandScan::needs_arity_rejection(scan.count)'
    ),
    "unmatched_address_parenthesis_fails_closed": (
        'ensure result == true text: sview = "movq (%rax,%rcx,8, %rbx" ' + scan_decl + ' return not scan.valid'
    ),
    "unmatched_closing_parenthesis_fails_closed": (
        'ensure result == true text: sview = "movq %rax), %rbx" ' + scan_decl + ' return not scan.valid'
    ),
    "nested_address_parentheses_fail_closed": (
        'ensure result == true text: sview = "movq ((%rax)), %rbx" ' + scan_decl + ' return not scan.valid'
    ),
    "no_operand_instruction_has_zero_operands": (
        'ensure result == true scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction("ret") '
        'return scan.valid and scan.count == 0'
    ),
    "scan_records_exact_top_level_separator_prefix": (
        "ensure result == true scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction(text) "
        "if not scan.valid: return scan.count == 0 and scan.first_separator == text.len and scan.last_separator == text.len and not scan.has_address_group "
        "if scan.count == 0: return (scan.start == text.len and scan.first_separator == text.len and scan.last_separator == text.len and not scan.has_address_group and scan.address_open == text.len and scan.address_close == text.len ) "
        "if scan.count == 1: return (scan.first_separator == text.len and scan.last_separator == text.len and scan.start < text.len and EasmOperandScan::first_operand_byte(text[scan.start:text.len], 0.usize()) < (text[scan.start:text.len]).len and EasmOperandScan::next_top_level_separator(text, scan.start, scan.has_address_group, scan.address_open, scan.address_close) == text.len ) "
        "first: usize = EasmOperandScan::next_top_level_separator(text, scan.start, scan.has_address_group, scan.address_open, scan.address_close) "
        "if scan.count == 2: return (scan.first_separator == first and scan.last_separator == first and EasmOperandScan::next_top_level_separator(text, first + 1.usize(), scan.has_address_group, scan.address_open, scan.address_close) == text.len ) "
        "second: usize = EasmOperandScan::next_top_level_separator(text, first + 1.usize(), scan.has_address_group, scan.address_open, scan.address_close) "
        "return scan.count == EasmOperandScan::TOO_MANY_OPERANDS_SENTINEL and scan.first_separator == first and scan.last_separator == second"
    ),
    "valid_scan_exposes_only_its_delimited_address_pair": (
        "ensure result == true scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction(text) "
        "if not scan.valid: return true "
        "if scan.has_address_group: return (scan.start <= scan.address_open and scan.address_open < scan.address_close and scan.address_close < text.len and text[scan.address_open] == EasmOperandScan::ASCII_LEFT_PAREN and text[scan.address_close] == EasmOperandScan::ASCII_RIGHT_PAREN and "
        "(forall candidate in scan.start..<scan.address_open: text[candidate] != EasmOperandScan::ASCII_LEFT_PAREN and text[candidate] != EasmOperandScan::ASCII_RIGHT_PAREN) and "
        "(forall candidate in scan.address_open + 1.usize()..<scan.address_close: text[candidate] != EasmOperandScan::ASCII_LEFT_PAREN and text[candidate] != EasmOperandScan::ASCII_RIGHT_PAREN) and "
        "(forall candidate in scan.address_close + 1.usize()..<text.len: text[candidate] != EasmOperandScan::ASCII_LEFT_PAREN and text[candidate] != EasmOperandScan::ASCII_RIGHT_PAREN) ) "
        "return (scan.address_open == text.len and scan.address_close == text.len and "
        "(forall candidate in scan.start..<text.len: text[candidate] != EasmOperandScan::ASCII_LEFT_PAREN and text[candidate] != EasmOperandScan::ASCII_RIGHT_PAREN) )"
    ),
    "first_operand_byte_is_the_least_non_whitespace": (
        "requires from <= text.len ensure result == true index: usize = EasmOperandScan::first_operand_byte(text, from) return ((index == text.len and "
        "(forall candidate in from..<text.len: text[candidate] == EasmOperandScan::ASCII_SPACE or text[candidate] == EasmOperandScan::ASCII_TAB)) or "
        "(index < text.len and text[index] != EasmOperandScan::ASCII_SPACE and text[index] != EasmOperandScan::ASCII_TAB and "
        "(forall candidate in from..<index: text[candidate] == EasmOperandScan::ASCII_SPACE or text[candidate] == EasmOperandScan::ASCII_TAB)))"
    ),
    "next_separator_is_the_first_comma_outside_address": (
        "requires from <= text.len and open <= text.len and close <= text.len ensure result == true separator: usize = EasmOperandScan::next_top_level_separator(text, from, has_address, open, close) "
        "return ((separator == text.len or (separator >= from and text[separator] == EasmOperandScan::ASCII_COMMA and (not has_address or separator < open or separator > close))) and "
        "(forall candidate in from..<separator: text[candidate] != EasmOperandScan::ASCII_COMMA or (has_address and candidate >= open and candidate <= close)))"
    ),
    "zero_operand_opcode_classifier_matches_its_exact_set": (
        'ensure result == true return EasmOperandScan::is_zero_operand_instruction(op) == ( op == "ret" or op == "retq" or op == "cpuid" or op == "cld" or op == "std" or '
        'op == "lfence" or op == "rdtsc" or op == "pause" or op == "yield" or op == "isb" or op == "emms" or op == "vzeroall" or op == "trap" )'
    ),
    "modeled_arity_matches_zero_operand_opcode_class": (
        "ensure result == true rejected: bool = ( EasmOperandScan::needs_arity_rejection(count) or (count == 0 and not zero_operand_opcode) or (count != 0 and zero_operand_opcode) ) "
        "return (not rejected) == ( count <= EasmOperandScan::MAX_MODELED_OPERAND_COUNT and ((count == 0) == zero_operand_opcode) )"
    ),
    "zero_operand_ret_arity_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("ret", 0.usize())'
    ),
    "unary_push_arity_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("pushq", 1.usize())'
    ),
    "binary_move_arity_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("movq", 2.usize())'
    ),
    "one_operand_shift_arity_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("shlq", 1.usize())'
    ),
    "two_operand_shift_arity_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("shlq", 2.usize())'
    ),
    "mrs_arity_is_binary": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("mrs", 2.usize())'
    ),
    "direct_register_token_is_recognized_exactly": (
        'ensure result == true return EasmOperandScan::exact_register_form("%rax", "rax")'
    ),
    "indirect_register_token_is_recognized_exactly": (
        'ensure result == true return EasmOperandScan::exact_register_form("*%rax", "rax")'
    ),
    "segment_address_is_not_a_register_token": (
        'ensure result == true return not EasmOperandScan::exact_register_form("%fs:0x28", "fs")'
    ),
    "exact_register_form_matches_its_complete_token_equation": (
        "ensure result == true return EasmOperandScan::exact_register_form(operand, register_name) == ( "
        "(operand.len == register_name.len + EasmOperandScan::SCAN_STEP and operand.len > 0 and operand[0] == EasmOperandScan::ASCII_PERCENT and operand[EasmOperandScan::SCAN_STEP:operand.len] == register_name) or "
        "(operand.len == register_name.len + EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH and operand.len >= EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH and operand[0] == EasmOperandScan::ASCII_STAR and operand[1] == EasmOperandScan::ASCII_PERCENT and operand[EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH:operand.len] == register_name) )"
    ),
    "direct_control_target_classifier_matches_its_exact_set": (
        "ensure result == true return EasmOperandScan::is_direct_control_target(op, operand, is_final_operand) == ( is_final_operand and operand.len > 0 and "
        "operand[0] != EasmOperandScan::ASCII_PERCENT and operand[0] != EasmOperandScan::ASCII_DOLLAR and operand[0] != EasmOperandScan::ASCII_STAR and "
        "operand[0] != EasmOperandScan::ASCII_LEFT_PAREN and operand[0] != EasmOperandScan::ASCII_LEFT_BRACKET and EasmTextScan::find(operand, \":\") == operand.len and "
        '(op == "call" or op == "callq" or op == "jmp" or op == "jmpq" or op == "je" or op == "jz" or op == "jne" or op == "jnz" or op == "jl" or op == "jle" or op == "jg" or op == "jge" or op == "jb" or op == "jbe" or op == "ja" or op == "jae") )'
    ),
    "direct_call_symbol_target_is_classified_as_control": (
        'ensure result == true return EasmOperandScan::is_direct_control_target("callq", "runtime_helper", true)'
    ),
    "conditional_symbol_target_is_classified_as_control": (
        'ensure result == true return EasmOperandScan::is_direct_control_target("jz", "local_done", true)'
    ),
    "aarch64_mrs_form_classifier_matches_x0_through_x30_and_xzr": (
        "ensure result == true return EasmOperandScan::is_aarch64_mrs_form(result_register, system_register) == ( system_register == \"cntvct_el0\" and "
        "(result_register == \"xzr\" or (result_register.len == 2 and result_register[0] == EasmOperandScan::ASCII_X and result_register[1] >= EasmOperandScan::ASCII_ZERO and result_register[1] <= EasmOperandScan::ASCII_NINE) or "
        "(result_register.len == 3 and result_register[0] == EasmOperandScan::ASCII_X and (((result_register[1] == EasmOperandScan::ASCII_ONE or result_register[1] == EasmOperandScan::ASCII_TWO) and result_register[2] >= EasmOperandScan::ASCII_ZERO and result_register[2] <= EasmOperandScan::ASCII_NINE) or (result_register[1] == EasmOperandScan::ASCII_THREE and result_register[2] == EasmOperandScan::ASCII_ZERO))) ) )"
    ),
    "mrs_accepts_low_x_register": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("x0", "cntvct_el0")'
    ),
    "mrs_accepts_high_x_register": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("x30", "cntvct_el0")'
    ),
    "mrs_accepts_zero_register": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("xzr", "cntvct_el0")'
    ),
    "bare_symbol_data_operands_are_rejected": (
        "requires operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target "
        "ensure result == true return operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target"
    ),
    "direct_call_symbol_targets_are_exempt_from_data_operand_rejection": (
        "requires operand_present and not memory_address and not register_operand and not immediate_operand and direct_target "
        "ensure result == false return operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target"
    ),
    "register_immediate_and_address_operands_are_modeled": (
        "requires operand_present and (memory_address or register_operand or immediate_operand) "
        "ensure result == false return operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target"
    ),
    "immediate_return_operands_are_rejected": (
        'requires immediate_operand and (op == "ret" or op == "retq") ensure result == true '
        'return immediate_operand and (op == "ret" or op == "retq")'
    ),
    "conditional_jump_targets_require_local_labels_or_explicit_authorization": (
        "ensure result == true return EasmOperandScan::rejects_unresolved_conditional_target( is_conditional_jump, target_is_local, direct_control_capability, relocation_symbol_capability ) == ( is_conditional_jump and not target_is_local and not direct_control_capability and not relocation_symbol_capability )"
    ),
    "segment_address_is_not_an_exact_register_operand": (
        'ensure result == true operand: sview = "%fs:0x28" register_name: sview = "fs" return not ( '
        '(operand.len == register_name.len + EasmOperandScan::SCAN_STEP and operand.len > 0 and '
        'operand[0] == EasmOperandScan::ASCII_PERCENT and operand[EasmOperandScan::SCAN_STEP:operand.len] == register_name) or '
        '(operand.len == register_name.len + EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH and '
        'operand.len >= EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH and '
        'operand[0] == EasmOperandScan::ASCII_STAR and operand[1] == EasmOperandScan::ASCII_PERCENT and '
        'operand[EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH:operand.len] == register_name) )'
    ),
}

expected_negative = {
    "indexed_address_has_four_operands": (
        'ensure result == true scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction("movq (%rax,%rcx,8), %rbx") '
        'return scan.count == 4'
    ),
    "three_top_level_operands_are_supported": (
        'ensure result == true scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction("shld %cl, %rbx, (%rax)") '
        "return scan.valid and not EasmOperandScan::needs_arity_rejection(scan.count)"
    ),
    "unmatched_address_parenthesis_is_valid": (
        'ensure result == true scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction("movq (%rax,%rcx,8, %rbx") '
        "return scan.valid"
    ),
    "invalid_scan_preserves_address_group_metadata": (
        'ensure result == true scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction("movq (%rax") '
        "return not scan.valid and scan.has_address_group"
    ),
    "zero_operand_scan_has_non_sentinel_separator": (
        'ensure result == true scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction("ret") '
        'return scan.valid and scan.count == 0 and scan.first_separator < ("ret").len'
    ),
    "single_operand_scan_has_an_empty_operand": (
        'ensure result == true text: sview = "callq *(%rax)" scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction(text) '
        "operand: sview = text[scan.start:text.len] return scan.valid and scan.count == 1 and EasmOperandScan::first_operand_byte(operand, 0.usize()) == operand.len"
    ),
    "next_separator_selects_a_comma_inside_address": (
        'ensure result == true text: sview = "(%rax,%rcx),%rbx" separator: usize = EasmOperandScan::next_top_level_separator(text, 0.usize(), true, 0.usize(), 10.usize()) '
        "return separator < text.len and separator <= 10.usize()"
    ),
    "cpuid_is_not_a_zero_operand_instruction": (
        'ensure result == true return not EasmOperandScan::is_zero_operand_instruction("cpuid")'
    ),
    "movq_is_a_zero_operand_instruction": (
        'ensure result == true return EasmOperandScan::is_zero_operand_instruction("movq")'
    ),
    "movq_with_one_operand_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("movq", 1.usize())'
    ),
    "incq_with_two_operands_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("incq", 2.usize())'
    ),
    "mrs_with_one_operand_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("mrs", 1.usize())'
    ),
    "register_suffix_is_accepted_as_the_exact_register": (
        'ensure result == true return EasmOperandScan::exact_register_form("%rax_extra", "rax")'
    ),
    "bare_register_name_is_accepted_as_att_syntax": (
        'ensure result == true return EasmOperandScan::exact_register_form("rax", "rax")'
    ),
    "register_operand_is_classified_as_a_direct_target": (
        'ensure result == true return EasmOperandScan::is_direct_control_target("callq", "%rax", true)'
    ),
    "immediate_operand_is_classified_as_a_direct_target": (
        'ensure result == true return EasmOperandScan::is_direct_control_target("callq", "$runtime_helper", true)'
    ),
    "nonfinal_symbol_is_classified_as_a_direct_target": (
        'ensure result == true return EasmOperandScan::is_direct_control_target("callq", "runtime_helper", false)'
    ),
    "mrs_accepts_x31": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("x31", "cntvct_el0")'
    ),
    "mrs_accepts_zero_padded_x09": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("x09", "cntvct_el0")'
    ),
    "mrs_accepts_general_purpose_w_register": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("w0", "cntvct_el0")'
    ),
    "mrs_accepts_unsupported_system_register": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("x0", "cntfrq_el0")'
    ),
    "nested_address_parentheses_are_valid": (
        'ensure result == true scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction("movq ((%rax)), %rbx") '
        "return scan.valid"
    ),
    "bare_data_symbol_is_accepted": (
        "requires operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target "
        "ensure result == true return not (operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target)"
    ),
    "immediate_return_is_stack_neutral": (
        'requires immediate_operand and (op == "ret" or op == "retq") ensure result == true '
        'return not (immediate_operand and (op == "ret" or op == "retq"))'
    ),
    "unresolved_conditional_target_is_always_accepted": (
        "ensure result == true return not EasmOperandScan::rejects_unresolved_conditional_target(true, false, false, false)"
    ),
}
