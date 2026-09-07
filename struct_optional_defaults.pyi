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

class Config(TypedDict):
    retries: NotRequired[int | None]
    ratio: NotRequired[float | None]
    enabled: NotRequired[bool | None]
    name: NotRequired[str | None]
    c_name: NotRequired[str | None]
    missing: NotRequired[Any | None]

class ConfigInput(Protocol):
    pass
    # optional attribute 'retries': int | None
    # optional attribute 'ratio': float | None
    # optional attribute 'enabled': bool | None
    # optional attribute 'name': str | bytes | None
    # optional attribute 'c_name': str | bytes | None
    # optional attribute 'missing': Any | None

def roundtrip(config: Config | ConfigInput) -> Config: ...

__all__: list[str] = ["roundtrip", "ElisaError", "Config"]
