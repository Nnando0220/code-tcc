"""Testes dos calculos usados na comparacao historica."""

import pandas as pd
import pytest

from ._bootstrap import ROOT  # noqa: F401
from tcc_reddit.metrics.comparison import (
    BaselineMetric,
    build_coverage_comparison,
    delta_row,
    trend,
)


def test_delta_row_calculates_absolute_and_relative_change():
    baseline = BaselineMetric(100, "count", "high", "teste")

    result = delta_row("items", baseline, 125)

    assert result["absolute_change"] == 25
    assert result["relative_change"] == 0.25


def test_coverage_comparison_uses_percentage_points():
    current = pd.DataFrame(
        [
            {
                "subreddit": subreddit,
                "announced_comments": announced,
                "stored_comments": stored,
                "comment_coverage_estimate": coverage,
            }
            for subreddit, (announced, stored, coverage) in {
                "news": (200, 150, 0.75),
                "worldnews": (200, 150, 0.75),
                "politics": (200, 190, 0.95),
                "geopolitics": (100, 85, 0.85),
                "brasil": (100, 90, 0.90),
                "NoticiasBR": (100, 99, 0.99),
                "brasilivre": (100, 98, 0.98),
                "BrasildoB": (100, 99, 0.99),
            }.items()
        ]
    )

    result = build_coverage_comparison(current).set_index("subreddit")

    assert result.loc["news", "coverage_change_pp"] == pytest.approx(46.83)
    assert result.loc["politics", "coverage_change_pp"] == pytest.approx(55.19)


def test_trend_matches_numeric_direction():
    assert trend(0.7, 0.8) == "subiu"
    assert trend(0.8, 0.7) == "caiu"
    assert trend(0.8, 0.8) == "permaneceu estavel"
