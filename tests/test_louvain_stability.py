"""Testes da verificacao complementar de estabilidade do Louvain."""

import pandas as pd
import pytest

from ._bootstrap import ROOT  # noqa: F401
from tcc_reddit.validation.louvain_stability import (
    LOUVAIN_STABILITY_SEEDS,
    run_louvain_stability,
    summarize_louvain_stability,
)


def test_louvain_stability_runs_all_seeds_for_each_subreddit():
    edges = pd.DataFrame(
        [
            {"source": "a", "target": "b", "subreddit": "one", "weight": 2},
            {"source": "b", "target": "c", "subreddit": "one", "weight": 1},
            {"source": "c", "target": "a", "subreddit": "one", "weight": 1},
            {"source": "d", "target": "e", "subreddit": "two", "weight": 3},
            {"source": "e", "target": "f", "subreddit": "two", "weight": 1},
            {"source": "f", "target": "d", "subreddit": "two", "weight": 1},
        ]
    )

    result = run_louvain_stability(edges)
    summary = summarize_louvain_stability(result)

    assert set(result["seed"]) == set(LOUVAIN_STABILITY_SEEDS)
    assert result.groupby("subreddit").size().to_dict() == {"one": 5, "two": 5}
    assert summary["seeds"] == sorted(LOUVAIN_STABILITY_SEEDS)
    assert summary["subreddits"] == 2
    assert summary["executions"] == 10


def test_louvain_stability_requires_expected_columns():
    with pytest.raises(ValueError, match="Colunas ausentes"):
        run_louvain_stability(pd.DataFrame({"source": ["a"]}))
