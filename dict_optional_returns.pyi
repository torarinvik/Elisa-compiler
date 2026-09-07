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

def maybe_count(values: Mapping[int, int]) -> int | None: ...

def text_from_dict(values: Mapping[int, int]) -> str: ...

def view_from_dict(values: Mapping[int, int]) -> str: ...

def object_from_dict(values: Mapping[int, int], value: Any) -> Any: ...

def nullable_text_from_dict(values: Mapping[int, int]) -> str | None: ...

def list_from_dict(values: Mapping[int, int], items: Sequence[int]) -> list[int]: ...

__all__: list[str] = ["maybe_count", "text_from_dict", "view_from_dict", "object_from_dict", "nullable_text_from_dict", "list_from_dict", "ElisaError", "DictBucket", "DynDict"]
