#!/usr/bin/env python3
"""Render a small, dependency-free Python stub from an Elisa pymodule manifest."""

from __future__ import annotations

import json
import keyword
import sys
from pathlib import Path


PRIMITIVES = {
    "i8": "int",
    "i16": "int",
    "i32": "int",
    "i64": "int",
    "int": "int",
    "isize": "int",
    "char": "int",
    "u8": "int",
    "u16": "int",
    "u32": "int",
    "u64": "int",
    "usize": "int",
    "uintptr": "int",
    "f32": "float",
    "f64": "float",
    "bool": "bool",
    "cstr": "str",
    "sview": "str",
    "py::Object": "Any",
    "void": "None",
}

# Names that can appear in generated annotations and can also be chosen as an
# exported Elisa function/constant/struct name. The renderer qualifies only
# the symbols that are shadowed by the generated module so ordinary stubs stay
# compact and readable while pathological-but-valid exports remain type-safe.
BUILTIN_TYPE_NAMES = {
    "bool", "bytes", "bytearray", "dict", "float", "int", "list",
    "memoryview", "object", "RuntimeError", "set", "str",
}
TYPING_TYPE_NAMES = {
    "Any", "Final", "Iterable", "Literal", "Mapping", "NotRequired", "Protocol",
    "Sequence", "TypedDict",
}


def qualified_type_symbol(name: str, type_context: dict[str, str] | None) -> str:
    if type_context is None:
        return name
    prefix = type_context.get(name)
    return f"{prefix}.{name}" if prefix else name


def unique_private_alias(base: str, reserved: set[str]) -> str:
    alias = base
    while alias in reserved:
        alias = f"_{alias}"
    return alias


def ascii_identifier(name: str) -> bool:
    """Match the compiler-owned Python-name contract for generated aliases."""
    if not name:
        return False
    first = name[0]
    if not (first == "_" or "A" <= first <= "Z" or "a" <= first <= "z"):
        return False
    return all(
        character == "_"
        or "A" <= character <= "Z"
        or "a" <= character <= "z"
        or "0" <= character <= "9"
        for character in name[1:]
    ) and not keyword.iskeyword(name) and name != "__debug__"


def typed_dict_class_safe(name: str, fields: list[dict]) -> bool:
    """Whether a TypedDict can use the readable class-body spelling."""
    if not name.isidentifier() or keyword.iskeyword(name):
        return False
    return all(
        isinstance(field.get("name"), str)
        and field["name"].isidentifier()
        and not keyword.iskeyword(field["name"])
        for field in fields
    )


def split_pair(text: str) -> tuple[str, str] | None:
    depth = 0
    for index, char in enumerate(text):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "," and depth == 0:
            return text[:index], text[index + 1 :]
    return None


def python_type(
    type_name: str,
    known_structs: dict[str, str],
    *,
    input_position: bool = False,
    type_context: dict[str, str] | None = None,
) -> str:
    if type_name.endswith("?"):
        return f"{python_type(type_name[:-1], known_structs, input_position=input_position, type_context=type_context)} | None"
    if type_name in {"cstr", "sview"} and input_position:
        # Text-bearing aggregates use the same ergonomic boundary as scalar
        # parameters: callers may provide Unicode or UTF-8 bytes. Results stay
        # ordinary Python strings because the native bridge decodes them.
        return " | ".join(
            [
                qualified_type_symbol("str", type_context),
                qualified_type_symbol("bytes", type_context),
            ]
        )
    if type_name in PRIMITIVES:
        return qualified_type_symbol(PRIMITIVES[type_name], type_context)
    if type_name.startswith("array[") and type_name.endswith("]"):
        # Borrowed fixed-array inputs accept validated sequence-like values; fixed-array
        # returns are fresh owning lists, matching ordinary darray returns.
        pair = split_pair(type_name[6:-1])
        if pair is not None:
            element = python_type(pair[0], known_structs, input_position=input_position, type_context=type_context)
            sequence_or_list = "Sequence" if input_position else "list"
            return f"{qualified_type_symbol(sequence_or_list, type_context)}[{element}]"
    if type_name.startswith("darray[") and type_name.endswith("]"):
        # Inputs accept the structural `FooInput` protocol; native results are
        # concrete `Foo` dictionaries. Propagate the position instead of
        # accidentally widening every list return to an input union.
        element = python_type(type_name[7:-1], known_structs, input_position=input_position, type_context=type_context)
        if type_name == "darray[u8]":
            bytes_type = qualified_type_symbol("bytes", type_context)
            if input_position:
                return " | ".join(
                    [
                        bytes_type,
                        qualified_type_symbol("bytearray", type_context),
                        qualified_type_symbol("memoryview", type_context),
                    ]
                )
            return bytes_type
        sequence_type = qualified_type_symbol("Sequence", type_context)
        list_type = qualified_type_symbol("list", type_context)
        return f"{sequence_type}[{element}]" if input_position else f"{list_type}[{element}]"
    if type_name.startswith("view[") and type_name.endswith("]"):
        element = python_type(type_name[5:-1], known_structs, input_position=input_position, type_context=type_context)
        if input_position:
            return f"{qualified_type_symbol('Sequence', type_context)}[{element}]"
        if type_name == "view[u8]":
            return qualified_type_symbol("bytes", type_context)
        return f"{qualified_type_symbol('list', type_context)}[{element}]"
    if type_name.startswith("set[") and type_name.endswith("]"):
        # Inputs are iterable, while results are concrete sets. Preserve the
        # position for the element too so text results stay `str` rather than
        # inheriting the input-only `bytes` widening.
        element = python_type(type_name[4:-1], known_structs, input_position=input_position, type_context=type_context)
        return f"{qualified_type_symbol('Iterable', type_context)}[{element}]" if input_position else f"{qualified_type_symbol('set', type_context)}[{element}]"
    if type_name.startswith("dict[") and type_name.endswith("]"):
        pair = split_pair(type_name[5:-1])
        if pair is not None:
            key, value = pair
            if input_position:
                return f"{qualified_type_symbol('Mapping', type_context)}[{python_type(key, known_structs, input_position=True, type_context=type_context)}, {python_type(value, known_structs, input_position=True, type_context=type_context)}]"
            return f"{qualified_type_symbol('dict', type_context)}[{python_type(key, known_structs, type_context=type_context)}, {python_type(value, known_structs, type_context=type_context)}]"
    struct_name = known_structs.get(type_name)
    if struct_name is None:
        return qualified_type_symbol("Any", type_context)
    return f"{struct_name} | {struct_name}Input" if input_position else struct_name


def stub_parameter_name(name: object, index: int) -> tuple[str, str | None]:
    """Return a valid stub identifier and preserve the Elisa spelling in a comment."""
    if isinstance(name, str) and name.isidentifier() and not keyword.iskeyword(name):
        return name, None
    original = name if isinstance(name, str) else f"arg{index}"
    return f"_arg{index}", str(original)


def identifier_fragment(value: object, fallback: str) -> str:
    """Make a stable, readable identifier fragment for generated payload types."""
    text = value if isinstance(value, str) else fallback
    fragment = "".join(char if char.isalnum() or char == "_" else "_" for char in text)
    if not fragment or fragment[0].isdigit() or keyword.iskeyword(fragment):
        fragment = f"_{fragment}"
    return fragment if fragment.isidentifier() else fallback


def unique_generated_name(base: str, used: set[str]) -> str:
    """Return a stable module-level name that does not shadow another declaration."""
    candidate = base
    suffix = 0
    while candidate in used:
        suffix += 1
        candidate = f"{base}_{suffix}"
    used.add(candidate)
    return candidate


def render_error_payload_types(
    manifest: dict,
    struct_aliases: dict[str, str],
    type_context: dict[str, str] | None = None,
    reserved_names: set[str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Render TypedDict payload variants and return family-to-union aliases."""
    lines: list[str] = []
    aliases: dict[str, str] = {}
    used_names = set(reserved_names or ())
    used_names.update(struct_aliases.values())
    used_names.update(f"{alias}Input" for alias in struct_aliases.values())
    seen_families: set[str] = set()
    for function in manifest.get("functions", []):
        if function.get("payload") != "struct" or not function.get("raises"):
            continue
        family = function["raises"]
        if family in seen_families:
            continue
        variants = function.get("payload_variants")
        if not isinstance(variants, list) or not variants:
            continue
        seen_families.add(family)
        family_id = identifier_fragment(family, f"Error{len(aliases)}")
        variant_types: list[str] = []
        for variant_index, variant in enumerate(variants):
            if not isinstance(variant, dict):
                continue
            variant_name = variant.get("name", f"Variant{variant_index}")
            variant_id = identifier_fragment(variant_name, f"Variant{variant_index}")
            class_name = f"{family_id}{variant_id}Payload"
            fields = [{"name": "variant", "type": f"{qualified_type_symbol('Literal', type_context)}[{variant_name!r}]"}]
            for field_index, field in enumerate(variant.get("fields", [])):
                if not isinstance(field, dict):
                    continue
                fields.append({
                    "name": field.get("name", f"field_{field_index}"),
                    "type": python_type(field.get("type", ""), struct_aliases, type_context=type_context),
                })
            class_name = unique_generated_name(class_name, used_names)
            if typed_dict_class_safe(class_name, fields):
                lines.append(f"class {class_name}({qualified_type_symbol('TypedDict', type_context)}):")
                for field in fields:
                    lines.append(f"    {field['name']}: {field['type']}")
            else:
                fields_literal = ", ".join(f"{field['name']!r}: {field['type']}" for field in fields)
                lines.append(f"{class_name} = {qualified_type_symbol('TypedDict', type_context)}({class_name!r}, {{{fields_literal}}})")
            lines.append("")
            variant_types.append(class_name)
        if variant_types:
            alias_name = unique_generated_name(f"{family_id}Payload", used_names)
            lines.append(f"{alias_name} = {' | '.join(variant_types)}")
            lines.append("")
            aliases[family] = alias_name
    return lines, aliases


def render_error_payload_annotations(
    manifest: dict,
    struct_aliases: dict[str, str],
    payload_aliases: dict[str, str],
    type_context: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return the most precise `.payload` annotation for each exported error family."""
    annotations: dict[str, str] = {}
    for function in manifest.get("functions", []):
        family = function.get("raises")
        if not isinstance(family, str) or not family or family in annotations:
            continue
        payload = function.get("payload")
        if payload == "struct":
            fallback = f"{qualified_type_symbol('dict', type_context)}[{qualified_type_symbol('str', type_context)}, {qualified_type_symbol('Any', type_context)}]"
            annotations[family] = payload_aliases.get(family, fallback)
        elif isinstance(payload, str) and payload:
            annotations[family] = python_type(payload, struct_aliases, type_context=type_context)
        else:
            # The generated runtime initializes every no-payload exception with
            # ``payload = None``. Keep the family-specific stub precise while the
            # base ElisaError remains broad for module-wide catches.
            annotations[family] = qualified_type_symbol("None", type_context)
    return annotations


def validate_manifest(manifest: dict) -> None:
    """Reject source contracts that cannot be represented by valid Python syntax."""
    for function in manifest.get("functions", []):
        if not isinstance(function, dict):
            continue
        function_name = function.get("name", "function")
        saw_optional = False
        for parameter in function.get("parameters", []):
            if not isinstance(parameter, dict):
                continue
            if "default" in parameter:
                saw_optional = True
            elif saw_optional:
                parameter_name = parameter.get("name", "parameter")
                raise ValueError(
                    f"function {function_name!r} has a required parameter {parameter_name!r} "
                    "after a default/nullable parameter"
                )


def render(manifest: dict) -> str:
    validate_manifest(manifest)
    structs = manifest.get("structs", [])
    error_classes: dict[str, str] = {}
    for function in manifest.get("functions", []):
        family = function.get("raises")
        if not isinstance(family, str) or not family:
            continue
        if family not in error_classes:
            error_classes[family] = identifier_fragment(family, f"ElisaError{len(error_classes)}")

    reserved_names = {
        name
        for entry in manifest.get("functions", []) + manifest.get("constants", [])
        for name in [entry.get("name")]
        if isinstance(name, str) and name
    }
    reserved_names.update(error_classes.values())
    reserved_names.update({"ElisaError", "__all__"})

    # Struct declarations are emitted as module-level TypedDict/Protocol names even though
    # they are not runtime exports. Avoid colliding with generated exceptions, __all__, exported
    # callables/constants, or another struct's companion ``Input`` protocol.
    struct_aliases: dict[str, str] = {}
    used_struct_names: set[str] = set()
    for index, entry in enumerate(structs):
        name = entry.get("name", "")
        if not isinstance(name, str) or not name:
            continue
        readable = name if ascii_identifier(name) else ""
        alias = readable if readable else f"_ElisaStruct_{index}"
        collides = (
            alias in reserved_names
            or alias in used_struct_names
            or f"{alias}Input" in reserved_names
            or f"{alias}Input" in used_struct_names
        )
        if collides:
            alias = f"_ElisaStruct_{index}"
            suffix = 0
            while (
                alias in reserved_names
                or alias in used_struct_names
                or f"{alias}Input" in reserved_names
                or f"{alias}Input" in used_struct_names
            ):
                suffix += 1
                alias = f"_ElisaStruct_{index}_{suffix}"
        struct_aliases[name] = alias
        used_struct_names.add(alias)
        used_struct_names.add(f"{alias}Input")

    reserved_names.update(struct_aliases.values())
    builtin_alias = unique_private_alias("_elisa_builtins", reserved_names)
    typing_alias = unique_private_alias("_elisa_typing", reserved_names | {builtin_alias})
    type_context: dict[str, str] = {}
    if reserved_names.intersection(BUILTIN_TYPE_NAMES):
        for name in BUILTIN_TYPE_NAMES:
            if name in reserved_names:
                type_context[name] = builtin_alias
    if reserved_names.intersection(TYPING_TYPE_NAMES):
        for name in TYPING_TYPE_NAMES:
            if name in reserved_names:
                type_context[name] = typing_alias

    lines = [
        "from __future__ import annotations",
        "",
        "from typing import Any, Final, Generic, Iterable, Literal, Mapping, Protocol, Sequence, TypedDict, TypeVar",
        "import sys",
        "if sys.version_info >= (3, 11):",
        "    from typing import NotRequired",
        "else:",
        "    try:",
        "        from typing_extensions import NotRequired  # type: ignore",
        "    except ImportError:",
        "        # Keep generated stubs importable on Python versions whose stdlib typing",
        "        # predates NotRequired and where typing_extensions is not installed. Type",
        "        # checkers that understand the marker still get the precise form above; older",
        "        # checkers see a regular generic compatibility marker instead of an import error.",
        "        _ElisaNotRequiredT = TypeVar(\"_ElisaNotRequiredT\")",
        "        class NotRequired(Generic[_ElisaNotRequiredT]):",
        "            pass",
        "",
        "",
    ]
    if any(prefix == builtin_alias for prefix in type_context.values()):
        lines.append(f"import builtins as {builtin_alias}")
    if any(prefix == typing_alias for prefix in type_context.values()):
        lines.append(f"import typing as {typing_alias}")
    lines.extend([
        "",
        f"class ElisaError({qualified_type_symbol('RuntimeError', type_context)}):",
        f"    code: {qualified_type_symbol('int', type_context)}",
        f"    function: {qualified_type_symbol('str', type_context)}",
        f"    parameter: {qualified_type_symbol('str', type_context)} | {qualified_type_symbol('None', type_context)}",
        f"    expected: {qualified_type_symbol('str', type_context)} | {qualified_type_symbol('None', type_context)}",
        f"    path: {qualified_type_symbol('str', type_context)} | {qualified_type_symbol('None', type_context)}",
        f"    payload: {qualified_type_symbol('Any', type_context)}",
        "",
    ])

    payload_lines, payload_aliases = render_error_payload_types(
        manifest, struct_aliases, type_context, reserved_names
    )
    if payload_lines:
        lines.extend(payload_lines)

    payload_annotations = render_error_payload_annotations(manifest, struct_aliases, payload_aliases, type_context)
    for family, class_name in error_classes.items():
        lines.append(f"class {class_name}(ElisaError):")
        lines.append(f"    payload: {payload_annotations.get(family, qualified_type_symbol('Any', type_context))}")
        lines.append("")

    for struct in structs:
        name = struct.get("name", "")
        if not name:
            continue
        name_text = name if isinstance(name, str) else str(name)
        fields = struct.get("fields", [])
        alias = struct_aliases.get(name_text, name_text)
        if typed_dict_class_safe(alias, fields):
            lines.append(f"class {alias}({qualified_type_symbol('TypedDict', type_context)}):")
            if not fields:
                lines.append("    pass")
            for field in fields:
                field_name = field.get("name", "field")
                field_type = python_type(field.get("type", ""), struct_aliases, type_context=type_context)
                if field.get("default") is not None:
                    field_type = f"{qualified_type_symbol('NotRequired', type_context)}[{field_type}]"
                elif field.get("optional"):
                    field_type = f"{qualified_type_symbol('NotRequired', type_context)}[{field_type}]"
                lines.append(f"    {field_name}: {field_type}")
        else:
            rendered_fields = []
            for field in fields:
                field_name = field.get("name", "field")
                field_type = python_type(field.get("type", ""), struct_aliases, type_context=type_context)
                if field.get("default") is not None:
                    field_type = f"{qualified_type_symbol('NotRequired', type_context)}[{field_type}]"
                elif field.get("optional"):
                    field_type = f"{qualified_type_symbol('NotRequired', type_context)}[{field_type}]"
                rendered_fields.append(f"{field_name!r}: {field_type}")
            fields_literal = ", ".join(rendered_fields)
            lines.append(f"{alias} = {qualified_type_symbol('TypedDict', type_context)}({name_text!r}, {{{fields_literal}}})")
        lines.append("")

        lines.append(f"class {alias}Input({qualified_type_symbol('Protocol', type_context)}):")
        required_fields = [
            field
            for field in fields
            if field.get("default") is None and not field.get("optional")
        ]
        if not required_fields:
            lines.append("    pass")
        for field in fields:
            field_name = field.get("name", "field")
            field_type = python_type(field.get("type", ""), struct_aliases, input_position=True, type_context=type_context)
            if field.get("optional") and field.get("default") is None and " | None" not in field_type:
                field_type = f"{field_type} | None"
            if field.get("default") is not None or field.get("optional"):
                # Protocol attributes are always required by type checkers;
                # NotRequired only has its intended meaning inside TypedDict.
                # Keep these fields as documentation while allowing the
                # attribute-based input object to omit them, matching the
                # runtime's default/nullable lookup behavior.
                if isinstance(field_name, str):
                    lines.append(f"    # optional attribute {field_name!r}: {field_type}")
                continue
            if isinstance(field_name, str) and field_name.isidentifier() and not keyword.iskeyword(field_name):
                lines.append(f"    {field_name}: {field_type}")
            else:
                lines.append(f"    # attribute {field_name!r}: {field_type}")
        lines.append("")

    for constant in manifest.get("constants", []):
        name = constant.get("name", "constant")
        constant_type = python_type(constant.get("type", ""), struct_aliases, type_context=type_context)
        lines.append(f"{name}: {qualified_type_symbol('Final', type_context)}[{constant_type}]")
    if manifest.get("constants"):
        lines.append("")

    for function in manifest.get("functions", []):
        name = function.get("name", "function")
        parameters = []
        renamed_parameters = []
        for parameter in function.get("parameters", []):
            parameter_name, original_name = stub_parameter_name(parameter.get("name", "value"), len(parameters))
            parameter_source_type = parameter.get("type", "")
            if parameter_source_type in {"cstr", "sview", "cstr?", "sview?"}:
                # Scalar text uses the CPython fast path for Unicode or UTF-8
                # bytes. Nullable forms add the natural Python None value.
                optional_text_suffix = " | None" if parameter_source_type.endswith("?") else ""
                parameter_type = (
                    f"{qualified_type_symbol('str', type_context)} | "
                    f"{qualified_type_symbol('bytes', type_context)}{optional_text_suffix}"
                )
            else:
                parameter_type = python_type(
                    parameter_source_type,
                    struct_aliases,
                    input_position=True,
                    type_context=type_context,
                )
            if "default" not in parameter:
                suffix = ""
            else:
                default = parameter.get("default")
                # Elisa spells the canonical empty set as `{}` because the parser reserves the
                # empty-brace form for both dict/set inference. The manifest keeps that literal
                # spelling, but a stub can use Python's more precise `set()` default directly.
                if isinstance(default, str) and default == "{}" and str(parameter.get("type", "")).startswith("set["):
                    default = "set()"
                # Empty byte darrays are exposed as bytes-like inputs. Keep a
                # type-correct fallback for manifests produced by older stage1
                # compilers that still serialized this default as `[]`.
                if isinstance(default, str) and default == "[]" and parameter.get("type") == "darray[u8]":
                    default = 'b""'
                suffix = " = ..." if not isinstance(default, str) or default == "<unsupported>" else f" = {default}"
            parameters.append(f"{parameter_name}: {parameter_type}{suffix}")
            if original_name is not None:
                renamed_parameters.append(f"{parameter_name} represents Elisa parameter {original_name!r}")
        return_type = python_type(function.get("return", "void"), struct_aliases, type_context=type_context)
        lines.append(f"def {name}({', '.join(parameters)}) -> {return_type}: ...")
        for renamed_parameter in renamed_parameters:
            lines.append(f"# {renamed_parameter}")
        if function.get("raises"):
            lines.append(f"# raises {function['raises']}")
            payload = function.get("payload")
            if payload == "struct":
                payload_alias = payload_aliases.get(
                    function["raises"],
                    f"{qualified_type_symbol('dict', type_context)}[{qualified_type_symbol('str', type_context)}, {qualified_type_symbol('Any', type_context)}]",
                )
                lines.append(f"# error payload: {payload_alias}")
            elif isinstance(payload, str):
                lines.append(f"# error payload: {python_type(payload, struct_aliases, type_context=type_context)}")
        lines.append("")

    exported = [entry.get("name") for entry in manifest.get("functions", [])]
    exported += [entry.get("name") for entry in manifest.get("constants", [])]
    exported += list(error_classes.values())
    exported.append("ElisaError")
    # Named records are real module-level construction helpers at runtime.  The
    # companion ``Input`` protocols remain typing-only, so only the concrete
    # record aliases participate in star imports and ``__all__``.
    exported += list(struct_aliases.values())
    # Keep the concrete value in the stub, not only in a comment: type checkers can then
    # resolve ``from module import *`` and IDEs can offer the same public surface as the
    # native extension without importing it.
    lines.append(f"__all__: list[str] = {json.dumps([name for name in exported if name])}")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} MANIFEST.json OUTPUT.pyi", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        Path(argv[2]).write_text(render(manifest), encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"pymodule-pyi: error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
