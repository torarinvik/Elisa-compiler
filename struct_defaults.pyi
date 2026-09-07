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

class Point(TypedDict):
    x: int
    y: int

class PointInput(Protocol):
    x: int
    y: int

class Config(TypedDict):
    retries: NotRequired[int]
    enabled: NotRequired[bool]
    ratio: NotRequired[float]
    label: NotRequired[str]
    text: NotRequired[str]
    tags: NotRequired[list[int]]
    numbers: NotRequired[list[int]]
    bytes: NotRequired[bytes]
    mapping: NotRequired[dict[int, int]]
    unique: NotRequired[set[int]]
    view_values: NotRequired[list[int]]
    nested: NotRequired[list[list[int]]]
    origin: NotRequired[Point]

class ConfigInput(Protocol):
    pass
    # optional attribute 'retries': int
    # optional attribute 'enabled': bool
    # optional attribute 'ratio': float
    # optional attribute 'label': str | bytes
    # optional attribute 'text': str | bytes
    # optional attribute 'tags': Sequence[int]
    # optional attribute 'numbers': Sequence[int]
    # optional attribute 'bytes': bytes | bytearray | memoryview
    # optional attribute 'mapping': Mapping[int, int]
    # optional attribute 'unique': Iterable[int]
    # optional attribute 'view_values': Sequence[int]
    # optional attribute 'nested': Sequence[Sequence[int]]
    # optional attribute 'origin': Point | PointInput

def roundtrip(config: Config | ConfigInput) -> Config: ...

def point_roundtrip(point: Point | PointInput = {"x": 10, "y": 20}) -> Point: ...

__all__: list[str] = ["roundtrip", "point_roundtrip", "ElisaError", "Point", "Config"]
