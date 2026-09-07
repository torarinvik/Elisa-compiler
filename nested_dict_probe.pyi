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

class NestedPayload(TypedDict):
    values: dict[int, dict[str, int]]

class NestedPayloadInput(Protocol):
    values: Mapping[int, Mapping[str | bytes, int]]

def roundtrip(values: Mapping[int, Mapping[int, int]]) -> dict[int, dict[int, int]]: ...

def roundtrip_struct(value: NestedPayload | NestedPayloadInput) -> NestedPayload: ...

def roundtrip_text(values: Mapping[str | bytes, Mapping[int, str | bytes]]) -> dict[str, dict[int, str]]: ...

def roundtrip_lists(values: Mapping[int, Mapping[str | bytes, Sequence[int]]]) -> dict[int, dict[str, list[int]]]: ...

def roundtrip_optional(values: Mapping[int, Mapping[str | bytes, int | None]]) -> dict[int, dict[str, int | None]]: ...

def roundtrip_objects(values: Mapping[int, Mapping[str | bytes, Any]]) -> dict[int, dict[str, Any]]: ...

__all__: list[str] = ["roundtrip", "roundtrip_struct", "roundtrip_text", "roundtrip_lists", "roundtrip_optional", "roundtrip_objects", "ElisaError", "NestedPayload"]
