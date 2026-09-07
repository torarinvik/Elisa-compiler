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

class StructuredPointPayloadErrorBadPayload(TypedDict):
    variant: Literal['Bad']
    code: int
    point: Point

StructuredPointPayloadErrorPayload = StructuredPointPayloadErrorBadPayload

class PointPayloadError(ElisaError):
    payload: Point

class StructuredPointPayloadError(ElisaError):
    payload: StructuredPointPayloadErrorPayload

class Point(TypedDict):
    x: int
    label: str

class PointInput(Protocol):
    x: int
    label: str | bytes

def fail_point(point: Point | PointInput) -> int: ...
# raises PointPayloadError
# error payload: Point

def fail_structured(code: int, point: Point | PointInput) -> int: ...
# raises StructuredPointPayloadError
# error payload: StructuredPointPayloadErrorPayload

__all__: list[str] = ["fail_point", "fail_structured", "PointPayloadError", "StructuredPointPayloadError", "ElisaError", "Point"]
