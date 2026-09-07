from __future__ import annotations

from typing import Any, Final, Generic, Iterable, Literal, Mapping, Protocol, Sequence, TypedDict, TypeVar
import sys
if sys.version_info >= (3, 11):
    from typing import NotRequired
else:
    try:
        from typing_extensions import NotRequired  # type: ignore
    except ImportError:
        # Keep generated stubs importable on Python versions whose stdlib typing
        # predates NotRequired and where typing_extensions is not installed. Type
        # checkers that understand the marker still get the precise form above; older
        # checkers see a regular generic compatibility marker instead of an import error.
        _ElisaNotRequiredT = TypeVar("_ElisaNotRequiredT")
        class NotRequired(Generic[_ElisaNotRequiredT]):
            pass



class ElisaError(RuntimeError):
    code: int
    function: str
    parameter: str | None
    expected: str | None
    path: str | None
    payload: Any

def roundtrip_sview(values: Mapping[int, Sequence[str | bytes]]) -> dict[int, list[str]]: ...

def roundtrip_cstr(values: Mapping[str | bytes, Sequence[str | bytes]]) -> dict[str, list[str]]: ...

def roundtrip_objects(values: Mapping[int, Sequence[Any]]) -> dict[int, list[Any]]: ...

def roundtrip_optional(values: Mapping[int, Sequence[int | None]]) -> dict[int, list[int | None]]: ...

def roundtrip_optional_text(values: Mapping[str | bytes, Sequence[str | bytes | None]]) -> dict[str, list[str | None]]: ...

def roundtrip_optional_objects(values: Mapping[int, Sequence[Any | None]]) -> dict[int, list[Any | None]]: ...

__all__: list[str] = ["roundtrip_sview", "roundtrip_cstr", "roundtrip_objects", "roundtrip_optional", "roundtrip_optional_text", "roundtrip_optional_objects", "ElisaError"]
