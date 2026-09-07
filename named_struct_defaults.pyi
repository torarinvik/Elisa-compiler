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
    y: int

class PointInput(Protocol):
    x: int
    y: int

def list_default(points: Sequence[Point | PointInput] = [{"x": 1, "y": 2}, {"x": 3, "y": 4}]) -> list[Point]: ...

def map_default(points: Mapping[int, Point | PointInput] = {1: {"x": 5, "y": 6}}) -> dict[int, Point]: ...

def map_list_default(points: Mapping[int, Sequence[Point | PointInput]] = {1: [{"x": 11, "y": 12}]}) -> dict[int, list[Point]]: ...

def nested_default(points: Sequence[Sequence[Point | PointInput]] = [[{"x": 7, "y": 8}], [{"x": 9, "y": 10}]]) -> list[list[Point]]: ...

__all__: list[str] = ["list_default", "map_default", "map_list_default", "nested_default", "ElisaError", "Point"]
