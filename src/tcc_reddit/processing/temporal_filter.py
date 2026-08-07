"""Regras comuns de janela temporal e exclusao de posts fixados."""

from __future__ import annotations

from datetime import datetime, timezone


def _parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_collection_window(config) -> tuple[datetime, datetime]:
    """Converte a janela fixa configurada e valida seus limites."""
    collection_start = _parse_utc_datetime(config.window_start)
    collection_end = _parse_utc_datetime(config.window_end)
    if collection_start >= collection_end:
        raise ValueError("A janela de coleta deve ter inicio anterior ao fim.")
    return collection_start, collection_end


def submission_exclusion_reason(
    *,
    created_at: datetime,
    window_start: datetime,
    window_end: datetime,
    stickied: bool,
    exclude_stickied: bool = True,
) -> str | None:
    if exclude_stickied and stickied:
        return "stickied"
    if created_at < window_start:
        return "before_window"
    if created_at > window_end:
        return "after_window"
    return None
