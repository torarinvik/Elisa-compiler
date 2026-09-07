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

class PayloadError(ElisaError):
    payload: int

class BoolPayloadError(ElisaError):
    payload: bool

class FloatPayloadError(ElisaError):
    payload: float

class DictPayloadError(ElisaError):
    payload: int

class RefPayloadError(ElisaError):
    payload: int

def fail(code: int) -> int: ...
# raises PayloadError
# error payload: int

def maybe(code: int) -> int: ...
# raises PayloadError
# error payload: int

def fail_bool(flag: bool) -> None: ...
# raises BoolPayloadError
# error payload: bool

def fail_float(value: float) -> None: ...
# raises FloatPayloadError
# error payload: float

def fail_dict(values: Mapping[int, int]) -> int: ...
# raises DictPayloadError
# error payload: int

def fail_ref(values: Sequence[int]) -> int: ...
# raises RefPayloadError
# error payload: int

__all__: list[str] = ["fail", "maybe", "fail_bool", "fail_float", "fail_dict", "fail_ref", "PayloadError", "BoolPayloadError", "FloatPayloadError", "DictPayloadError", "RefPayloadError", "ElisaError"]
