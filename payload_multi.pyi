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

class MultiPayloadErrorBadPayload(TypedDict):
    variant: Literal['Bad']
    code: int
    detail: str

class MultiPayloadErrorOtherPayload(TypedDict):
    variant: Literal['Other']
    label: str
    value: Any

MultiPayloadErrorPayload = MultiPayloadErrorBadPayload | MultiPayloadErrorOtherPayload

class MultiPayloadError(ElisaError):
    payload: MultiPayloadErrorPayload

def fail(code: int, detail: str | bytes) -> int: ...
# raises MultiPayloadError
# error payload: MultiPayloadErrorPayload

def fail_other(label: str | bytes, value: Any) -> int: ...
# raises MultiPayloadError
# error payload: MultiPayloadErrorPayload

__all__: list[str] = ["fail", "fail_other", "MultiPayloadError", "ElisaError"]
