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

class TextPayloadError(ElisaError):
    payload: str

class CStrPayloadError(ElisaError):
    payload: str

class ObjectPayloadError(ElisaError):
    payload: Any

def fail_sview(text: str | bytes) -> None: ...
# raises TextPayloadError
# error payload: str

def fail_cstr(text: str | bytes) -> None: ...
# raises CStrPayloadError
# error payload: str

def fail_object(value: Any) -> None: ...
# raises ObjectPayloadError
# error payload: Any

__all__: list[str] = ["fail_sview", "fail_cstr", "fail_object", "TextPayloadError", "CStrPayloadError", "ObjectPayloadError", "ElisaError"]
