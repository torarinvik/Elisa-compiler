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

class StructuredNestedListPayloadErrorEmptyPayload(TypedDict):
    variant: Literal['Empty']
    items: list[list[int]]
    label: str

StructuredNestedListPayloadErrorPayload = StructuredNestedListPayloadErrorEmptyPayload

class NestedListPayloadError(ElisaError):
    payload: list[list[int]]

class StructuredNestedListPayloadError(ElisaError):
    payload: StructuredNestedListPayloadErrorPayload

class DeepNestedListPayloadError(ElisaError):
    payload: list[list[list[int]]]

class ListSetsPayloadError(ElisaError):
    payload: list[set[int]]

def fail_nested(values: Sequence[Sequence[int]]) -> int: ...
# raises NestedListPayloadError
# error payload: list[list[int]]

def fail_structured(values: Sequence[Sequence[int]], label: str | bytes) -> int: ...
# raises StructuredNestedListPayloadError
# error payload: StructuredNestedListPayloadErrorPayload

def fail_deep(values: Sequence[Sequence[Sequence[int]]]) -> int: ...
# raises DeepNestedListPayloadError
# error payload: list[list[list[int]]]

def fail_list_sets(values: Sequence[Iterable[int]]) -> int: ...
# raises ListSetsPayloadError
# error payload: list[set[int]]

__all__: list[str] = ["fail_nested", "fail_structured", "fail_deep", "fail_list_sets", "NestedListPayloadError", "StructuredNestedListPayloadError", "DeepNestedListPayloadError", "ListSetsPayloadError", "ElisaError"]
