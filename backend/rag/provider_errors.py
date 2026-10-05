from __future__ import annotations

from langchain_google_genai.chat_models import GoogleRateLimitError


def exception_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def provider_error_kind(error: BaseException) -> str | None:
    if any(isinstance(item, GoogleRateLimitError) for item in exception_chain(error)):
        return "rate_limit"
    return None


def provider_status_code(error: BaseException) -> int | None:
    for item in exception_chain(error):
        for attribute in ("status_code", "code"):
            try:
                value = getattr(item, attribute, None)
            except Exception:  # pragma: no cover - defensive for provider properties
                continue
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 100 <= value <= 599
            ):
                return value
    return None


class ProviderCallError(RuntimeError):
    """Provider failure carrying only diagnostics safe for logs and eval output."""

    def __init__(
        self,
        *,
        error_stage: str,
        cause_type: str,
        provider_error_kind: str,
        provider_status_code: int | None,
        elapsed_ms: float,
    ) -> None:
        super().__init__("Provider call failed")
        self.error_stage = error_stage
        self.cause_type = cause_type
        self.category = "provider"
        self.provider_error_kind = provider_error_kind
        self.provider_status_code = provider_status_code
        self.elapsed_ms = elapsed_ms


def wrap_rate_limit_error(
    error: GoogleRateLimitError,
    *,
    error_stage: str,
    elapsed_ms: float,
) -> ProviderCallError:
    return ProviderCallError(
        error_stage=error_stage,
        cause_type=type(error).__name__,
        provider_error_kind="rate_limit",
        provider_status_code=provider_status_code(error),
        elapsed_ms=elapsed_ms,
    )
