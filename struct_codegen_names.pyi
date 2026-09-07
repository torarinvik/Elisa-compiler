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

class CodegenNames(TypedDict):
    arena: dict[int, int]
    result: dict[int, int]
    field_value: list[int]
    field_seq: list[int]
    field_view: list[int]
    payload: set[int]
    items: list[int]
    count: int
    value: int
    object: Any
    key: str
    index: int
    error_type: int
    error_value: int
    error_traceback: int
    owned: int
    result_index: int
    nested_index: int
    list: list[int]
    view: list[int]

class CodegenNamesInput(Protocol):
    arena: Mapping[int, int]
    result: Mapping[int, int]
    field_value: Sequence[int]
    field_seq: Sequence[int]
    field_view: Sequence[int]
    payload: Iterable[int]
    items: Sequence[int]
    count: int
    value: int
    object: Any
    key: str | bytes
    index: int
    error_type: int
    error_value: int
    error_traceback: int
    owned: int
    result_index: int
    nested_index: int
    list: Sequence[int]
    view: Sequence[int]

def roundtrip(value: CodegenNames | CodegenNamesInput) -> CodegenNames: ...

__all__: list[str] = ["roundtrip", "ElisaError", "CodegenNames"]
