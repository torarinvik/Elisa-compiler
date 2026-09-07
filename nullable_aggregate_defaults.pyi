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

def list_default(values: Sequence[int | None] = [1, None, -2]) -> list[int | None]: ...

def dict_default(values: Mapping[str | bytes, int | None] = {"a": 1, "b": None}) -> dict[str, int | None]: ...

def text_default(values: Sequence[str | bytes | None] = ["hello", None, "a\0b"]) -> list[str | None]: ...

def object_default(values: Sequence[Any | None] = [None]) -> list[Any | None]: ...

def optional_scalar_default(value: int | None = 7) -> int | None: ...

def optional_text_default(value: str | bytes | None = "hello") -> str | None: ...

def optional_cstr_default(value: str | bytes | None = "world") -> str | None: ...

def optional_object_default(value: Any | None = None) -> Any | None: ...

__all__: list[str] = ["list_default", "dict_default", "text_default", "object_default", "optional_scalar_default", "optional_text_default", "optional_cstr_default", "optional_object_default", "ElisaError"]
