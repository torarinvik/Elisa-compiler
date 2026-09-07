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

class StructDictPayloadErrorBadPayload(TypedDict):
    variant: Literal['Bad']
    code: int
    values: dict[int, int]

StructDictPayloadErrorPayload = StructDictPayloadErrorBadPayload

class TextStructDictPayloadErrorBadPayload(TypedDict):
    variant: Literal['Bad']
    label: str
    values: dict[str, str]

TextStructDictPayloadErrorPayload = TextStructDictPayloadErrorBadPayload

class StructDictPayloadError(ElisaError):
    payload: StructDictPayloadErrorPayload

class TextStructDictPayloadError(ElisaError):
    payload: TextStructDictPayloadErrorPayload

def fail_dict(code: int, values: Mapping[int, int]) -> int: ...
# raises StructDictPayloadError
# error payload: StructDictPayloadErrorPayload

def fail_text(label: str | bytes, values: Mapping[str | bytes, str | bytes]) -> int: ...
# raises TextStructDictPayloadError
# error payload: TextStructDictPayloadErrorPayload

__all__: list[str] = ["fail_dict", "fail_text", "StructDictPayloadError", "TextStructDictPayloadError", "ElisaError"]
