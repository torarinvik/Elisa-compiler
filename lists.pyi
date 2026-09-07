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

def count(values: Sequence[int]) -> int: ...

def count_i8(values: Sequence[int]) -> int: ...

def first(values: Sequence[int]) -> int: ...

def echo_f64(values: Sequence[float]) -> list[float]: ...

def echo_i8(values: Sequence[int]) -> list[int]: ...

def echo_u16(values: Sequence[int]) -> list[int]: ...

def echo_bool(values: Sequence[bool]) -> list[bool]: ...

def echo_f32(values: Sequence[float]) -> list[float]: ...

def first_bool(values: Sequence[bool]) -> bool: ...

def list_and_text(values: Sequence[int], text: str | bytes) -> str: ...

def list_and_object(values: Sequence[int], value: Any) -> Any: ...

__all__: list[str] = ["count", "count_i8", "first", "echo_f64", "echo_i8", "echo_u16", "echo_bool", "echo_f32", "first_bool", "list_and_text", "list_and_object", "ElisaError"]
