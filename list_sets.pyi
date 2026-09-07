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

class Bundle(TypedDict):
    values: list[set[int]]

class BundleInput(Protocol):
    values: Sequence[Iterable[int]]

def roundtrip(values: Sequence[Iterable[int]]) -> list[set[int]]: ...

def count(values: Sequence[Iterable[int]]) -> int: ...

def roundtrip_bundle(value: Bundle | BundleInput) -> Bundle: ...

def roundtrip_map(value: Mapping[int, Sequence[Iterable[int]]]) -> dict[int, list[set[int]]]: ...

__all__: list[str] = ["roundtrip", "count", "roundtrip_bundle", "roundtrip_map", "ElisaError", "Bundle"]
