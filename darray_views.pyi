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

class Point(TypedDict):
    x: int

class PointInput(Protocol):
    x: int

def roundtrip_i64(values: Sequence[Sequence[int]]) -> list[list[int]]: ...

def roundtrip_text(values: Sequence[Sequence[str | bytes]]) -> list[list[str]]: ...

def roundtrip_optional(values: Sequence[Sequence[int | None]]) -> list[list[int | None]]: ...

def roundtrip_objects(values: Sequence[Sequence[Any]]) -> list[list[Any]]: ...

def roundtrip_points(values: Sequence[Sequence[Point | PointInput]]) -> list[list[Point]]: ...

__all__: list[str] = ["roundtrip_i64", "roundtrip_text", "roundtrip_optional", "roundtrip_objects", "roundtrip_points", "ElisaError", "Point"]
