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

def count_i64(values: Iterable[int]) -> int: ...

def count_text(values: Iterable[str | bytes]) -> int: ...

def count_u8(values: Iterable[int]) -> int: ...

def count_bool(values: Iterable[bool]) -> int: ...

def roundtrip_i64(values: Iterable[int]) -> set[int]: ...

def roundtrip_i8(values: Iterable[int]) -> set[int]: ...

def roundtrip_text(values: Iterable[str | bytes]) -> set[str]: ...

def roundtrip_u8(values: Iterable[int]) -> set[int]: ...

def empty_i64() -> set[int]: ...

__all__: list[str] = ["count_i64", "count_text", "count_u8", "count_bool", "roundtrip_i64", "roundtrip_i8", "roundtrip_text", "roundtrip_u8", "empty_i64", "ElisaError"]
