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

def scaled(base: int, factor: int = 3, offset: int = 5) -> int: ...

def enabled(flag: bool = False) -> bool: ...

def ratio(value: float, scale: float = 0.5) -> float: ...

def count_from(start: int = 0) -> int: ...

def char_code(value: int = 65) -> int: ...

def cstr_default(value: str | bytes = "hello") -> str: ...

def sview_default(value: str | bytes = "α") -> str: ...

def escaped_default(value: str | bytes = "line\nnext") -> str: ...

def empty_list(values: Sequence[int] = []) -> int: ...

def empty_bytes(values: bytes | bytearray | memoryview = b"") -> int: ...

def empty_dict(values: Mapping[int, int] = {}) -> int: ...

def empty_set(values: Iterable[int] = set()) -> int: ...

def empty_view(values: Sequence[int] = []) -> int: ...

def empty_mix(values: Sequence[int] = [], mapping: Mapping[int, int] = {}, unique: Iterable[int] = set()) -> int: ...

__all__: list[str] = ["scaled", "enabled", "ratio", "count_from", "char_code", "cstr_default", "sview_default", "escaped_default", "empty_list", "empty_bytes", "empty_dict", "empty_set", "empty_view", "empty_mix", "ElisaError"]
