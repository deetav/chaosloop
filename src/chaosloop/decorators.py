from collections.abc import Callable
from typing import Any, cast, overload


@overload
def chaos_test[F: Callable[..., Any]](_func: F, **kwargs: Any) -> F: ...


@overload
def chaos_test[F: Callable[..., Any]](_func: None = None, **kwargs: Any) -> Callable[[F], F]: ...


def chaos_test[F: Callable[..., Any]](
    _func: F | None = None, **kwargs: Any
) -> F | Callable[[F], F]:
    """Support both @chaos_test and @chaos_test(trials=200), lazily importing pytest."""
    import pytest

    def wrap(func: F) -> F:
        return cast(F, pytest.mark.chaos(**kwargs)(func))

    return wrap if _func is None else wrap(_func)
