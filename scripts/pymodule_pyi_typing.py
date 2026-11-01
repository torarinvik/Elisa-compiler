"""Versioned typing imports and buffer annotations for Python interfaces."""
from __future__ import annotations

NUMERIC_ELEMENTS = frozenset({
    "i8", "i16", "i32", "i64", "int", "isize", "u8", "u16", "u32", "u64",
    "usize", "uintptr", "f32", "f64",
})


def numeric_view(type_name: str) -> bool:
    """Match the fixed-width numeric views accepted by the native buffer bridge."""
    return (type_name.startswith("view[") and type_name.endswith("]")
            and type_name[5:-1] in NUMERIC_ELEMENTS)


def uses_buffers(manifest: dict) -> bool:
    """Find numeric views in input signatures and generated record protocols."""
    types = [parameter.get("type", "") for function in manifest.get("functions", [])
             for parameter in function.get("parameters", [])]
    types += [field.get("type", "") for record in manifest.get("structs", [])
              for field in record.get("fields", [])]
    writable = any(parameter.get("mutable") for function in manifest.get("functions", [])
                   for parameter in function.get("parameters", []))
    return writable or any(f"view[{element}]" in type_name
               for type_name in types for element in NUMERIC_ELEMENTS)


def buffer_imports(module_alias: str, checking_alias: str) -> list[str]:
    """Use the standard protocol, with its official backport for older typing tools.

    Deferred annotations make the backport a type-checking import rather than a
    dependency when a stub is executed on an older interpreter.
    """
    return [
        "if sys.version_info >= (3, 12):",
        f"    import collections.abc as {module_alias}",
        f"elif {checking_alias}:",
        f"    import typing_extensions as {module_alias}",
        "",
    ]


def compatibility_imports(checking_alias: str, optional_alias: str | None = None) -> list[str]:
    """Use the real NotRequired marker; never manufacture a substitute class."""
    standard = (f"    import typing as {optional_alias}" if optional_alias
                else "    from typing import NotRequired")
    backport = (f"    import typing_extensions as {optional_alias}" if optional_alias
                else "    from typing_extensions import NotRequired")
    return [
        f"from typing import TYPE_CHECKING as {checking_alias}",
        "import sys",
        "if sys.version_info >= (3, 11):",
        standard,
        f"elif {checking_alias}:",
        backport,
        "",
    ]
