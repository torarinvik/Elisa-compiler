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

class DictSetBundle(TypedDict):
    numbers: dict[int, set[int]]
    labels: dict[str, set[str]]
    nested: dict[int, dict[int, set[int]]]

class DictSetBundleInput(Protocol):
    numbers: Mapping[int, Iterable[int]]
    labels: Mapping[str | bytes, Iterable[str | bytes]]
    nested: Mapping[int, Mapping[int, Iterable[int]]]

def echo(bundle: DictSetBundle | DictSetBundleInput) -> DictSetBundle: ...

__all__: list[str] = ["echo", "ElisaError", "DictSetBundle"]
