"""Regras comuns de janela temporal e exclusao de posts fixados."""

from __future__ import annotations

from datetime import datetime


def submission_exclusion_reason(
    *,
    created_at: datetime,
    window_start: datetime,
    window_end: datetime,
    stickied: bool,
) -> str | None:
    if stickied:
        return "stickied"
    if created_at < window_start:
        return "before_window"
    if created_at > window_end:
        return "after_window"
    return None
