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
    label: str

class PointInput(Protocol):
    x: int
    label: str | bytes

def roundtrip(values: Sequence[Sequence[int]]) -> list[list[int]]: ...

def count(values: Sequence[Sequence[int]]) -> int: ...

def roundtrip_deep(values: Sequence[Sequence[Sequence[Sequence[int]]]]) -> list[list[list[list[int]]]]: ...

def roundtrip_points(values: Sequence[Sequence[Point | PointInput]]) -> list[list[Point]]: ...

def roundtrip_points_deep(values: Sequence[Sequence[Sequence[Point | PointInput]]]) -> list[list[list[Point]]]: ...

__all__: list[str] = ["roundtrip", "count", "roundtrip_deep", "roundtrip_points", "roundtrip_points_deep", "ElisaError", "Point"]
