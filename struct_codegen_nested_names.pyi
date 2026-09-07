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

class NestedCodegenNames(TypedDict):
    result: dict[int, list[int | None]]
    result_index: dict[int, list[float | None]]
    nested_index: dict[int, list[Any | None]]

class NestedCodegenNamesInput(Protocol):
    result: Mapping[int, Sequence[int | None]]
    result_index: Mapping[int, Sequence[float | None]]
    nested_index: Mapping[int, Sequence[Any | None]]

def roundtrip(value: NestedCodegenNames | NestedCodegenNamesInput) -> NestedCodegenNames: ...

__all__: list[str] = ["roundtrip", "ElisaError", "NestedCodegenNames"]
