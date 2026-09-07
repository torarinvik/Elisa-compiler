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

class StructuredOptionalPayloadErrorInvalidPayload(TypedDict):
    variant: Literal['Invalid']
    code: int
    value: int | None
    label: str | None
    object: Any | None
    text: str | None

StructuredOptionalPayloadErrorPayload = StructuredOptionalPayloadErrorInvalidPayload

class OptionalIntPayloadError(ElisaError):
    payload: int | None

class OptionalTextPayloadError(ElisaError):
    payload: str | None

class OptionalCStrPayloadError(ElisaError):
    payload: str | None

class OptionalObjectPayloadError(ElisaError):
    payload: Any | None

class StructuredOptionalPayloadError(ElisaError):
    payload: StructuredOptionalPayloadErrorPayload

def fail_int(value: int | None = None) -> int: ...
# raises OptionalIntPayloadError
# error payload: int | None

def fail_text(value: str | bytes | None = None) -> int: ...
# raises OptionalTextPayloadError
# error payload: str | None

def fail_cstr(value: str | bytes | None = None) -> int: ...
# raises OptionalCStrPayloadError
# error payload: str | None

def fail_object(value: Any | None = None) -> int: ...
# raises OptionalObjectPayloadError
# error payload: Any | None

def fail_struct(value: int | None = None, label: str | bytes | None = None, object: Any | None = None, text: str | bytes | None = None) -> int: ...
# raises StructuredOptionalPayloadError
# error payload: StructuredOptionalPayloadErrorPayload

__all__: list[str] = ["fail_int", "fail_text", "fail_cstr", "fail_object", "fail_struct", "OptionalIntPayloadError", "OptionalTextPayloadError", "OptionalCStrPayloadError", "OptionalObjectPayloadError", "StructuredOptionalPayloadError", "ElisaError"]
