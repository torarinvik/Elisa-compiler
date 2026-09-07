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

class StructuredNestedDictPayloadErrorBadPayload(TypedDict):
    variant: Literal['Bad']
    code: int
    values: dict[int, dict[str, int]]

StructuredNestedDictPayloadErrorPayload = StructuredNestedDictPayloadErrorBadPayload

class NestedDictPayloadError(ElisaError):
    payload: dict[int, dict[str, int]]

class StructuredNestedDictPayloadError(ElisaError):
    payload: StructuredNestedDictPayloadErrorPayload

def fail_nested(values: Mapping[int, Mapping[str | bytes, int]]) -> int: ...
# raises NestedDictPayloadError
# error payload: dict[int, dict[str, int]]

def fail_structured(code: int, values: Mapping[int, Mapping[str | bytes, int]]) -> int: ...
# raises StructuredNestedDictPayloadError
# error payload: StructuredNestedDictPayloadErrorPayload

__all__: list[str] = ["fail_nested", "fail_structured", "NestedDictPayloadError", "StructuredNestedDictPayloadError", "ElisaError"]
