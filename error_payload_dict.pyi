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

class DictPayloadError(ElisaError):
    payload: dict[int, int]

class TextDictPayloadError(ElisaError):
    payload: dict[str, str]

class ObjectDictPayloadError(ElisaError):
    payload: dict[int, Any]

def fail_dict(values: Mapping[int, int]) -> int: ...
# raises DictPayloadError
# error payload: dict[int, int]

def fail_text(values: Mapping[str | bytes, str | bytes]) -> int: ...
# raises TextDictPayloadError
# error payload: dict[str, str]

def fail_objects(values: Mapping[int, Any]) -> int: ...
# raises ObjectDictPayloadError
# error payload: dict[int, Any]

__all__: list[str] = ["fail_dict", "fail_text", "fail_objects", "DictPayloadError", "TextDictPayloadError", "ObjectDictPayloadError", "ElisaError"]
