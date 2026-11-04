"""Request-scoped context (correlation id + client ip) for audit trails."""

from contextvars import ContextVar

request_id_ctx: ContextVar[str | None] = ContextVar("legacylock_request_id", default=None)
client_ip_ctx: ContextVar[str | None] = ContextVar("legacylock_client_ip", default=None)


def current_request_id() -> str | None:
    return request_id_ctx.get()


def current_client_ip() -> str | None:
    return client_ip_ctx.get()
