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

def bad(values: Sequence[int] = [1]) -> int: ...

def mapping(values: Mapping[int, int] = {1: 2}) -> int: ...

def unique(values: Iterable[int] = {1, 2}) -> int: ...

def bytes_default(values: bytes | bytearray | memoryview = b"\x01\x02\xff") -> int: ...

def nested(values: Sequence[Sequence[int]] = [[1, 2], [3]]) -> int: ...

def viewed(values: Sequence[int] = [1, 2]) -> int: ...

__all__: list[str] = ["bad", "mapping", "unique", "bytes_default", "nested", "viewed", "ElisaError"]
