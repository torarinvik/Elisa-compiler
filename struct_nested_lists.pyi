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

class NestedPoint(TypedDict):
    x: int
    label: str

class NestedPointInput(Protocol):
    x: int
    label: str | bytes

class NestedLists(TypedDict):
    values: list[list[int]]
    cubes: list[list[list[int]]]
    weights: list[list[float]]
    bytes: list[bytes]
    texts: list[list[str]]
    labels: list[list[str]]
    objects: list[list[Any]]
    optional: list[list[int | None]]
    points: list[list[NestedPoint]]

class NestedListsInput(Protocol):
    values: Sequence[Sequence[int]]
    cubes: Sequence[Sequence[Sequence[int]]]
    weights: Sequence[Sequence[float]]
    bytes: Sequence[bytes | bytearray | memoryview]
    texts: Sequence[Sequence[str | bytes]]
    labels: Sequence[Sequence[str | bytes]]
    objects: Sequence[Sequence[Any]]
    optional: Sequence[Sequence[int | None]]
    points: Sequence[Sequence[NestedPoint | NestedPointInput]]

def roundtrip(batch: NestedLists | NestedListsInput) -> NestedLists: ...

__all__: list[str] = ["roundtrip", "ElisaError", "NestedPoint", "NestedLists"]
