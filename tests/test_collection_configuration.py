"""Testes de regressao para os parametros que governam a coleta."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ._bootstrap import ROOT  # noqa: F401
from tcc_reddit.processing.temporal_filter import (
    resolve_collection_window,
    submission_exclusion_reason,
)


def test_collection_window_uses_configured_absolute_dates():
    config = SimpleNamespace(
        window_start="2025-07-13T06:20:34.222843Z",
        window_end="2026-07-13T06:20:34.222843Z",
    )

    start, end = resolve_collection_window(config)

    assert start == datetime(2025, 7, 13, 6, 20, 34, 222843, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 13, 6, 20, 34, 222843, tzinfo=timezone.utc)


def test_collection_window_rejects_inverted_limits():
    config = SimpleNamespace(
        window_start="2026-07-13T06:20:34Z",
        window_end="2025-07-13T06:20:34Z",
    )

    with pytest.raises(ValueError, match="inicio anterior ao fim"):
        resolve_collection_window(config)


def test_stickied_exclusion_respects_configuration():
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    start = datetime(2025, 7, 13, tzinfo=timezone.utc)
    end = datetime(2026, 7, 13, tzinfo=timezone.utc)

    assert submission_exclusion_reason(
        created_at=created_at,
        window_start=start,
        window_end=end,
        stickied=True,
        exclude_stickied=True,
    ) == "stickied"
    assert submission_exclusion_reason(
        created_at=created_at,
        window_start=start,
        window_end=end,
        stickied=True,
        exclude_stickied=False,
    ) is None
