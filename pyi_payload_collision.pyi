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

class CollisionBadPayload_1(TypedDict):
    variant: Literal['Bad']
    code: int
    detail: int

CollisionPayload_1 = CollisionBadPayload_1

class Collision(ElisaError):
    payload: CollisionPayload_1

class CollisionBadPayload(TypedDict):
    marker: int

class CollisionBadPayloadInput(Protocol):
    marker: int

class CollisionPayload(TypedDict):
    marker: int

class CollisionPayloadInput(Protocol):
    marker: int

def fail() -> int: ...
# raises Collision
# error payload: CollisionPayload_1

__all__: list[str] = ["fail", "Collision", "ElisaError", "CollisionBadPayload", "CollisionPayload"]
