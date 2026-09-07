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

class RowsPayloadError(ElisaError):
    payload: list[dict[int, int]]

class StructRowsPayloadError(ElisaError):
    payload: list[dict[int, Point]]

class NestedRowsPayloadError(ElisaError):
    payload: list[dict[int, list[dict[str, int]]]]

class Point(TypedDict):
    x: int
    label: str

class PointInput(Protocol):
    x: int
    label: str | bytes

def fail_rows(values: Sequence[Mapping[int, int]]) -> int: ...
# raises RowsPayloadError
# error payload: list[dict[int, int]]

def fail_struct_rows(values: Sequence[Mapping[int, Point | PointInput]]) -> int: ...
# raises StructRowsPayloadError
# error payload: list[dict[int, Point]]

def fail_nested_rows(values: Sequence[Mapping[int, Sequence[Mapping[str | bytes, int]]]]) -> int: ...
# raises NestedRowsPayloadError
# error payload: list[dict[int, list[dict[str, int]]]]

__all__: list[str] = ["fail_rows", "fail_struct_rows", "fail_nested_rows", "RowsPayloadError", "StructRowsPayloadError", "NestedRowsPayloadError", "ElisaError", "Point"]
