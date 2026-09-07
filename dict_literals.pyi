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

class DictBucket(TypedDict):
    key: Any
    value: Any
    state: int

class DictBucketInput(Protocol):
    key: Any
    value: Any
    state: int

class DynDict(TypedDict):
    items: Any
    count: int
    used: int
    capacity: int
    arena: int

class DynDictInput(Protocol):
    items: Any
    count: int
    used: int
    capacity: int
    arena: int

def literal_i64() -> dict[int, int]: ...

def comprehension_i64() -> dict[int, int]: ...

__all__: list[str] = ["literal_i64", "comprehension_i64", "ElisaError", "DictBucket", "DynDict"]
