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


import builtins as _elisa_builtins

class ElisaError(RuntimeError):
    code: int
    function: str
    parameter: str | None
    expected: str | None
    path: str | None
    payload: Any

class DivideError(ElisaError):
    payload: None

class ListError(ElisaError):
    payload: None

class ListPayloadError(ElisaError):
    payload: int

class DictResultError(ElisaError):
    payload: None

class DictResultPayloadError(ElisaError):
    payload: int

def divide(value: int, divisor: int) -> int: ...
# raises DivideError

def flag(flag: bool) -> bool: ...
# raises DivideError

def float(value: _elisa_builtins.float) -> _elisa_builtins.float: ...
# raises DivideError

def unsigned(value: int) -> int: ...
# raises DivideError

def text(text: str | bytes) -> str: ...
# raises DivideError

def rejected_text(text: str | bytes) -> str: ...
# raises DivideError

def object(value: Any) -> Any: ...
# raises DivideError

def checked_dict(values: Mapping[int, int]) -> int: ...
# raises DivideError

def checked_view(values: Sequence[int]) -> list[int]: ...
# raises DivideError

def checked_list(values: Sequence[int]) -> int: ...
# raises DivideError

def checked_list_result(values: Sequence[int]) -> list[int]: ...
# raises ListError

def checked_list_payload(values: Sequence[int]) -> list[int]: ...
# raises ListPayloadError
# error payload: int

def checked_bytes_result(values: bytes | bytearray | memoryview) -> bytes: ...
# raises ListError

def checked_dict_list(values: Mapping[int, int], items: Sequence[int]) -> list[int]: ...
# raises ListError

def checked_dict_result(values: Mapping[int, int]) -> dict[int, int]: ...
# raises DictResultError

def checked_dict_payload(values: Mapping[int, int]) -> dict[int, int]: ...
# raises DictResultPayloadError
# error payload: int

def ping() -> None: ...
# raises DivideError

__all__: list[str] = ["divide", "flag", "float", "unsigned", "text", "rejected_text", "object", "checked_dict", "checked_view", "checked_list", "checked_list_result", "checked_list_payload", "checked_bytes_result", "checked_dict_list", "checked_dict_result", "checked_dict_payload", "ping", "DivideError", "ListError", "ListPayloadError", "DictResultError", "DictResultPayloadError", "ElisaError"]
