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

def count_i64(values: Sequence[int]) -> int: ...

def first_i64(values: Sequence[int]) -> int: ...

def identity_i64(values: Sequence[int]) -> list[int]: ...

def identity_u8(values: Sequence[int]) -> bytes: ...

def sum_u16(values: Sequence[int]) -> int: ...

def count_text(values: Sequence[str | bytes]) -> int: ...

def count_objects(values: Sequence[Any]) -> int: ...

def count_nullable(values: Sequence[int | None]) -> int: ...

__all__: list[str] = ["count_i64", "first_i64", "identity_i64", "identity_u8", "sum_u16", "count_text", "count_objects", "count_nullable", "ElisaError"]
