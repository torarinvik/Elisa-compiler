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

class StructuredSetPayloadErrorBadPayload(TypedDict):
    variant: Literal['Bad']
    code: int
    values: set[int]
    labels: set[str]

StructuredSetPayloadErrorPayload = StructuredSetPayloadErrorBadPayload

class SetPayloadError(ElisaError):
    payload: set[int]

class StructuredSetPayloadError(ElisaError):
    payload: StructuredSetPayloadErrorPayload

class HolderSetPayloadError(ElisaError):
    payload: Holder

class Holder(TypedDict):
    values: set[int]

class HolderInput(Protocol):
    values: Iterable[int]

def fail(values: Iterable[int]) -> int: ...
# raises SetPayloadError
# error payload: set[int]

def fail_structured(code: int, values: Iterable[int], labels: Iterable[str | bytes]) -> int: ...
# raises StructuredSetPayloadError
# error payload: StructuredSetPayloadErrorPayload

def fail_holder(holder: Holder | HolderInput) -> int: ...
# raises HolderSetPayloadError
# error payload: Holder

__all__: list[str] = ["fail", "fail_structured", "fail_holder", "SetPayloadError", "StructuredSetPayloadError", "HolderSetPayloadError", "ElisaError", "Holder"]
