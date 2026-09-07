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

class StructuredDictSetPayloadErrorBadPayload(TypedDict):
    variant: Literal['Bad']
    code: int
    values: dict[int, set[int]]

StructuredDictSetPayloadErrorPayload = StructuredDictSetPayloadErrorBadPayload

class DictSetPayloadError(ElisaError):
    payload: dict[int, set[int]]

class StructuredDictSetPayloadError(ElisaError):
    payload: StructuredDictSetPayloadErrorPayload

class NestedDictSetPayloadError(ElisaError):
    payload: dict[int, dict[str, set[int]]]

def fail(values: Mapping[int, Iterable[int]]) -> int: ...
# raises DictSetPayloadError
# error payload: dict[int, set[int]]

def fail_structured(code: int, values: Mapping[int, Iterable[int]]) -> int: ...
# raises StructuredDictSetPayloadError
# error payload: StructuredDictSetPayloadErrorPayload

def fail_nested(values: Mapping[int, Mapping[str | bytes, Iterable[int]]]) -> int: ...
# raises NestedDictSetPayloadError
# error payload: dict[int, dict[str, set[int]]]

__all__: list[str] = ["fail", "fail_structured", "fail_nested", "DictSetPayloadError", "StructuredDictSetPayloadError", "NestedDictSetPayloadError", "ElisaError"]
