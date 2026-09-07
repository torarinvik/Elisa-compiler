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

class NestedDictionaryError(ElisaError):
    payload: dict[int, list[list[int]]]

def roundtrip(values: Mapping[int, Sequence[Sequence[int]]]) -> dict[int, list[list[int]]]: ...

def roundtrip_text(values: Mapping[str | bytes, Sequence[Sequence[str | bytes]]]) -> dict[str, list[list[str]]]: ...

def roundtrip_objects(values: Mapping[int, Sequence[Sequence[Any]]]) -> dict[int, list[list[Any]]]: ...

def roundtrip_deep(values: Mapping[int, Sequence[Sequence[Sequence[Sequence[int]]]]]) -> dict[int, list[list[list[list[int]]]]]: ...

def roundtrip_rows(values: Mapping[int, Sequence[Mapping[str | bytes, int]]]) -> dict[int, list[dict[str, int]]]: ...

def roundtrip_batches(values: Sequence[Mapping[int, Sequence[Mapping[str | bytes, int]]]]) -> list[dict[int, list[dict[str, int]]]]: ...

def fail(values: Mapping[int, Sequence[Sequence[int]]]) -> int: ...
# raises NestedDictionaryError
# error payload: dict[int, list[list[int]]]

__all__: list[str] = ["roundtrip", "roundtrip_text", "roundtrip_objects", "roundtrip_deep", "roundtrip_rows", "roundtrip_batches", "fail", "NestedDictionaryError", "ElisaError"]
