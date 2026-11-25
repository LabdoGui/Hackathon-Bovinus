import secrets
from datetime import UTC, datetime


def transaction_code(now: datetime | None = None) -> str:
    """Código legível e único de transação, ex.: ``PC-20261125-7F3A9C``."""
    now = now or datetime.now(UTC)
    return f"PC-{now:%Y%m%d}-{secrets.token_hex(3).upper()}"
