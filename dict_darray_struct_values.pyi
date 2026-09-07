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
    label: str

class PointInput(Protocol):
    x: int
    label: str | bytes

class Catalog(TypedDict):
    rows: dict[int, list[Point]]

class CatalogInput(Protocol):
    rows: Mapping[int, Sequence[Point | PointInput]]

def roundtrip(rows: Mapping[int, Sequence[Point | PointInput]]) -> dict[int, list[Point]]: ...

def roundtrip_rows(rows: Sequence[Mapping[int, Sequence[Point | PointInput]]]) -> list[dict[int, list[Point]]]: ...

def roundtrip_catalog(catalog: Catalog | CatalogInput) -> Catalog: ...

__all__: list[str] = ["roundtrip", "roundtrip_rows", "roundtrip_catalog", "ElisaError", "Point", "Catalog"]
