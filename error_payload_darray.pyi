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

class StructuredListPayloadErrorEmptyPayload(TypedDict):
    variant: Literal['Empty']
    items: list[int]
    label: str

StructuredListPayloadErrorPayload = StructuredListPayloadErrorEmptyPayload

class ListPayloadError(ElisaError):
    payload: list[int]

class BytesPayloadError(ElisaError):
    payload: bytes

class StructuredListPayloadError(ElisaError):
    payload: StructuredListPayloadErrorPayload

def fail_list(values: Sequence[int]) -> int: ...
# raises ListPayloadError
# error payload: list[int]

def fail_constructed() -> int: ...
# raises ListPayloadError
# error payload: list[int]

def fail_bytes(values: bytes | bytearray | memoryview) -> int: ...
# raises BytesPayloadError
# error payload: bytes

def fail_structured(values: Sequence[int], label: str | bytes) -> int: ...
# raises StructuredListPayloadError
# error payload: StructuredListPayloadErrorPayload

__all__: list[str] = ["fail_list", "fail_constructed", "fail_bytes", "fail_structured", "ListPayloadError", "BytesPayloadError", "StructuredListPayloadError", "ElisaError"]
