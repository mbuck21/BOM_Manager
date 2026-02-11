from __future__ import annotations

from functools import wraps
from typing import Any, Callable


ServiceResult = dict[str, Any]


def make_result(
    ok: bool,
    data: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> ServiceResult:
    return {
        "ok": ok,
        "data": data or {},
        "errors": errors or [],
        "warnings": warnings or [],
    }


def ok_result(data: dict[str, Any] | None = None, warnings: list[str] | None = None) -> ServiceResult:
    return make_result(ok=True, data=data, warnings=warnings)


def err_result(errors: list[str] | str, data: dict[str, Any] | None = None) -> ServiceResult:
    if isinstance(errors, str):
        errors = [errors]
    return make_result(ok=False, data=data, errors=errors)


def service_guard(func: Callable[..., ServiceResult]) -> Callable[..., ServiceResult]:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> ServiceResult:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - defensive safety boundary
            return err_result(f"{func.__name__} failed: {exc}")

    return wrapper
