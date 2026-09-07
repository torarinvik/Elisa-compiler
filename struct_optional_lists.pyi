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

class OptionalBatch(TypedDict):
    signed: list[int | None]
    narrow: list[int | None]
    flags: list[bool | None]
    ratio: list[float | None]
    labels: list[str | None]
    text: list[str | None]

class OptionalBatchInput(Protocol):
    signed: Sequence[int | None]
    narrow: Sequence[int | None]
    flags: Sequence[bool | None]
    ratio: Sequence[float | None]
    labels: Sequence[str | bytes | None]
    text: Sequence[str | bytes | None]

def echo(batch: OptionalBatch | OptionalBatchInput) -> OptionalBatch: ...

__all__: list[str] = ["echo", "ElisaError", "OptionalBatch"]
