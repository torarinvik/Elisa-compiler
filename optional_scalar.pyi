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

def maybe_int(value: int | None = None) -> int | None: ...

def maybe_float(value: float | None = None) -> float | None: ...

def maybe_bool(value: bool | None = None) -> bool | None: ...

def maybe_i8(value: int | None = None) -> int | None: ...

def maybe_u8(value: int | None = None) -> int | None: ...

def maybe_i32(value: int | None = None) -> int | None: ...

def maybe_f32(value: float | None = None) -> float | None: ...

__all__: list[str] = ["maybe_int", "maybe_float", "maybe_bool", "maybe_i8", "maybe_u8", "maybe_i32", "maybe_f32", "ElisaError"]
