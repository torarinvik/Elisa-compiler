"""Render proofs derived from the generated Unicode classifier."""

import re
from typing import Optional

SCALAR_MAX = "0x10FFFF"
SURROGATE_MIN = "0xD800"
SURROGATE_MAX = "0xDFFF"


def ensure_interval(lower: str, upper: str) -> str:
    return (f"({lower} >= 0 and {lower} <= {upper} and {upper} <= {SCALAR_MAX} "
            f"and ({upper} < {SURROGATE_MIN} or {lower} > {SURROGATE_MAX}))")


def ensure_page_interval_conditions(lower: str, upper: str) -> tuple[str, ...]:
    return (f"{lower} >= 0", f"{lower} <= {upper}", f"{upper} <= {SCALAR_MAX}")


def render_bounds(table: dict) -> str:
    lines = ["# Scalar validity and strict ordering for every generated Unicode interval.", ""]
    for name, item in table.items():
        if item["kind"] != "leaf":
            continue
        lines.extend((f"def {name}_intervals_are_valid_and_ordered() -> bool:",))
        atoms = item["atoms"]
        for lower, upper in atoms:
            lines.append(f"    ensure {ensure_interval(lower, upper)}")
        for (_, previous_upper), (next_lower, _) in zip(atoms, atoms[1:]):
            lines.append(f"    ensure {previous_upper} < {next_lower}")
        lines.extend(("    ensure result == true", "    return true", ""))

    for name, item in table.items():
        if item["kind"] != "dispatch":
            continue
        lines.append(f"def {name}_page_intervals_are_valid_and_ordered() -> bool:")
        routes = item["routes"]
        for lower, upper, _ in routes:
            for condition in ensure_page_interval_conditions(lower, upper):
                lines.append(f"    ensure {condition}")
        for (_, previous_upper, _), (next_lower, _, _) in zip(routes, routes[1:]):
            lines.append(f"    ensure {previous_upper} < {next_lower}")
        lines.extend(("    ensure result == true", "    return true", ""))
    return "\n".join(lines).rstrip() + "\n"


def render_bounds_parts(table: dict) -> dict[str, str]:
    """Keep complete proof functions together in bounded generated files."""
    blocks = render_bounds(table).strip().split("\n\n")
    files = {}
    current = []

    def add_file(group: list[str]) -> None:
        content = "\n\n".join(group) + "\n"
        names = re.findall(r"(?m)^def (unicode_[a-z0-9_]+?)(?:_page)?_intervals_are_valid_and_ordered\(", content)
        if not names:
            raise ValueError("generated Unicode bounds have no theorem names")
        files[f"lexer_bounds_{names[0]}_through_{names[-1]}.elisa"] = content

    for block in blocks:
        candidate = "\n\n".join(current + [block]) + "\n"
        if len(candidate.splitlines()) > 590 and current:
            add_file(current)
            current = []
        current.append(block)
        if len(("\n\n".join(current) + "\n").splitlines()) > 600:
            raise ValueError("one generated Unicode proof exceeds 600 lines")
    if current:
        add_file(current)
    return files


def render_model(table: dict) -> str:
    lines = [
        "# The checker binds each atom flag to one exact source interval or singleton.",
        "# These lemmas prove OR reduction and page routing after abstraction.",
        "",
    ]
    for name, item in table.items():
        if item["kind"] == "leaf":
            params = []
            for index, (lower, upper) in enumerate(item["atoms"]):
                atom_label = lower[2:].lower()
                if lower != upper:
                    atom_label += "_" + upper[2:].lower()
                params.append(f"atom_{index:02d}_{atom_label}_reported: bool")
            expression = " or ".join(param.split(":", 1)[0] for param in params)
            theorem = f"proof_{name}_accumulates_source_intervals"
        elif item["kind"] == "aggregate":
            params = [f"{child}_reported: bool" for child in item["children"]]
            expression = " or ".join(param.split(":", 1)[0] for param in params)
            theorem = f"proof_{name}_accumulates_source_parts"
        elif item["kind"] == "dispatch":
            params = ["value: i64"]
            route_terms = []
            for index, (lower, upper, _) in enumerate(item["routes"]):
                params.append(f"page_{index:02d}_reported: bool")
                route_terms.append(
                    f"((value >= {lower} and value <= {upper}) and page_{index:02d}_reported)"
                )
            expression = " or ".join(route_terms)
            theorem = f"proof_{name}_routes_inside_page_intervals"
        else:
            params = [f"dispatch_reported: bool"]
            expression = "dispatch_reported"
            theorem = f"proof_{name}_preserves_dispatch_result"

        signature = ", ".join(params)
        lines.append(f"def {theorem}({signature}) -> bool:")
        lines.append(f"    ensure result == ({expression})")
        lines.append(f"    return {expression}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def hex_literal(value: int) -> str:
    return f"0x{value:X}"


def leaf_at_expression(table: dict, name: str, value: int) -> str:
    item = table[name]
    if item["kind"] != "leaf":
        raise SystemExit(f"{name} is not a source interval predicate")
    value_text = hex_literal(value)
    terms = []
    for lower, upper in item["atoms"]:
        if lower == upper:
            terms.append(f"{value_text} == {lower}")
        else:
            terms.append(f"({value_text} >= {lower} and {value_text} <= {upper})")
    return " or ".join(terms)


def dispatch_at_expression(table: dict, name: str, value: int, selected_page: Optional[int]) -> str:
    item = table[name]
    if item["kind"] != "dispatch":
        raise SystemExit(f"{name} is not a page dispatcher")
    value_text = hex_literal(value)
    terms = []
    for index, (lower, upper, _) in enumerate(item["routes"]):
        reported = "true" if selected_page is None or index == selected_page else "false"
        terms.append(
            f"(({value_text} >= {lower} and {value_text} <= {upper}) and {reported})"
        )
    return " or ".join(terms)


def render_witnesses(table: dict) -> str:
    cjk_lower, cjk_upper = table["unicode_letter_p00_r21"]["atoms"][3]
    digit_lower, digit_upper = table["unicode_digit_p01_r02"]["atoms"][4]
    first_letter_lower, _ = table["unicode_letter_p00_r00"]["atoms"][0]
    _, final_letter_upper = table["unicode_letter_p03_r00"]["atoms"][-1]
    page_boundary = int(table["unicode_letter_dispatch_00"]["routes"][1][0], 16)
    page_limit = int(table["unicode_letter_dispatch_00"]["routes"][-1][1], 16)
    cases = [
        ("unicode_letter_cjk_extension_a_lower_boundary_is_in_table", "true",
         leaf_at_expression(table, "unicode_letter_p00_r21", int(cjk_lower, 16))),
        ("unicode_letter_cjk_extension_a_upper_boundary_is_in_table", "true",
         leaf_at_expression(table, "unicode_letter_p00_r21", int(cjk_upper, 16))),
        ("unicode_digit_mathematical_digit_lower_boundary_is_in_table", "true",
         leaf_at_expression(table, "unicode_digit_p01_r02", int(digit_lower, 16))),
        ("unicode_digit_mathematical_digit_upper_boundary_is_in_table", "true",
         leaf_at_expression(table, "unicode_digit_p01_r02", int(digit_upper, 16))),
        ("unicode_digit_scalar_before_mathematical_digits_is_outside_table", "false",
         leaf_at_expression(table, "unicode_digit_p01_r02", int(digit_lower, 16) - 1)),
        ("unicode_digit_scalar_after_mathematical_digits_is_outside_table", "false",
         leaf_at_expression(table, "unicode_digit_p01_r02", int(digit_upper, 16) + 1)),
        ("unicode_letter_first_generated_lower_boundary_is_in_table", "true",
         leaf_at_expression(table, "unicode_letter_p00_r00", int(first_letter_lower, 16))),
        ("unicode_letter_final_generated_upper_boundary_is_in_table", "true",
         leaf_at_expression(table, "unicode_letter_p03_r00", int(final_letter_upper, 16))),
        ("unicode_letter_scalar_after_final_generated_range_is_outside_table", "false",
         leaf_at_expression(table, "unicode_letter_p03_r00", int(final_letter_upper, 16) + 1)),
        ("unicode_letter_supplementary_boundary_routes_to_page_one", "true",
         dispatch_at_expression(table, "unicode_letter_dispatch_00", page_boundary, 1)),
        ("unicode_letter_scalar_after_last_dispatch_page_is_unrouted", "false",
         dispatch_at_expression(table, "unicode_letter_dispatch_00", page_limit + 1, None)),
        ("unicode_surrogate_interval_is_not_a_scalar_interval", "false",
         ensure_interval("0xD800", "0xDFFF")),
    ]
    lines = ["# Concrete endpoint witnesses rendered from the generated classifier.", ""]
    for name, expected, expression in cases:
        lines.extend((f"def {name}() -> bool:", f"    ensure result == {expected}",
                      f"    return {expression}", ""))
    return "\n".join(lines).rstrip() + "\n"


def render_negative(table: dict) -> str:
    by_atoms = {}
    for name, item in table.items():
        if item["kind"] == "leaf":
            for index, interval in enumerate(item["atoms"]):
                by_atoms[(name, index)] = interval
    cjk_lower, cjk_upper = by_atoms[("unicode_letter_p00_r21", 3)]
    digit_lower, digit_upper = by_atoms[("unicode_digit_p01_r02", 4)]
    first_atoms = table["unicode_letter_p00_r00"]["atoms"]
    previous_upper = first_atoms[0][1]
    next_lower = first_atoms[1][0]
    letter_routes = table["unicode_letter_dispatch_00"]["routes"]
    wrong_page_value = letter_routes[1][0]
    outside_page_value = hex(int(letter_routes[-1][1], 16) + 1).upper().replace("0X", "0x")
    wrong_page_terms = []
    outside_page_terms = []
    for index, (lower, upper, _) in enumerate(letter_routes):
        wrong_page_terms.append(
            f"(({wrong_page_value} >= {lower} and {wrong_page_value} <= {upper}) and "
            f"{'true' if index == 0 else 'false'})"
        )
        outside_page_terms.append(
            f"(({outside_page_value} >= {lower} and {outside_page_value} <= {upper}) and true)"
        )

    lines = [
        "# False controls: each intentionally contradicts a concrete source-bound fact.",
        "",
        "def false_cjk_extension_a_start_is_not_a_letter() -> bool:",
        "    ensure result == true",
        f"    return not (0x3400 >= {cjk_lower} and 0x3400 <= {cjk_upper})",
        "",
        "def false_mathematical_decimal_digit_start_is_not_a_digit() -> bool:",
        "    ensure result == true",
        f"    return not (0x1D7CE >= {digit_lower} and 0x1D7CE <= {digit_upper})",
        "",
        "def false_supplementary_letter_uses_the_bmp_page() -> bool:",
        "    ensure result == true",
        "    return " + " or ".join(wrong_page_terms),
        "",
        "def false_codepoint_above_generated_pages_is_reported() -> bool:",
        "    ensure result == true",
        "    return " + " or ".join(outside_page_terms),
        "",
        "def false_surrogate_span_is_a_scalar_interval() -> bool:",
        "    ensure result == true",
        f"    return {ensure_interval('0xD800', '0xDFFF')}",
        "",
        "def false_generated_intervals_are_not_strictly_ordered() -> bool:",
        "    ensure result == true",
        f"    return {previous_upper} >= {next_lower}",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


