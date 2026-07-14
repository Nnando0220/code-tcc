"""Testes da agregacao de redes e da amostragem balanceada."""

from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from ._bootstrap import ROOT  # noqa: F401
from tcc_reddit.networks.pipeline import (
    aggregate_directed_edges,
    aggregate_undirected_edges,
    build_balanced_datasets,
    write_validated_gexf,
)


@pytest.fixture
def edges():
    return pd.DataFrame(
        [
            {"source": "A", "target": "B", "subreddit": "brasil", "interaction_type": "reply_comment", "weight": 3},
            {"source": "A", "target": "B", "subreddit": "brasil", "interaction_type": "reply_post", "weight": 2},
            {"source": "A", "target": "B", "subreddit": "politics", "interaction_type": "reply_comment", "weight": 1},
            {"source": "B", "target": "A", "subreddit": "brasil", "interaction_type": "reply_comment", "weight": 4},
        ]
    )


def test_directed_aggregation_preserves_total_weight(edges):
    result = aggregate_directed_edges(edges)
    assert len(result) == 2
    assert int(result["weight"].sum()) == 10
    a_to_b = result[(result["source"] == "A") & (result["target"] == "B")]
    assert int(a_to_b.iloc[0]["weight"]) == 6


def test_undirected_aggregation_merges_both_directions(edges):
    result = aggregate_undirected_edges(edges)
    assert len(result) == 1
    assert int(result.iloc[0]["weight"]) == 10


def test_gexf_edge_count_is_validated(edges, tmp_path: Path):
    result = aggregate_directed_edges(edges)
    path = tmp_path / "network.gexf"
    write_validated_gexf(
        result,
        path,
        directed=True,
        source="source",
        target="target",
        edge_attributes=["weight", "subreddits", "interaction_types"],
    )
    graph = nx.read_gexf(path)
    assert graph.number_of_edges() == len(result)


def test_ancestors_are_preserved():
    posts = pd.DataFrame(
        [
            {"submission_id": "p1", "subreddit": "s1", "num_comments": 6},
            {"submission_id": "p2", "subreddit": "s2", "num_comments": 0},
        ]
    )
    collections = pd.DataFrame(
        [
            {"submission_id": "p1", "subreddit": "s1", "sort_origin": "top", "sort_rank": 1, "eligible": True},
            {"submission_id": "p2", "subreddit": "s2", "sort_origin": "top", "sort_rank": 1, "eligible": True},
        ]
    )
    comments = pd.DataFrame(
        [
            {
                "comment_id": f"c{index}",
                "submission_id": "p1",
                "parent_id": "t3_p1" if index == 0 else f"t1_c{index - 1}",
                "depth": index,
                "created_utc": index,
            }
            for index in range(6)
        ]
    )
    _, sampled, manifest = build_balanced_datasets(
        posts,
        comments,
        collections,
        target_posts_per_subreddit=1,
        max_comments_per_post=1,
        seed=42,
    )
    selected_ids = set(sampled["comment_id"])
    for row in sampled.itertuples(index=False):
        if str(row.parent_id).startswith("t1_"):
            assert str(row.parent_id).removeprefix("t1_") in selected_ids
    post_manifest = manifest[manifest["submission_id"] == "p1"].iloc[0]
    assert post_manifest["ancestors_added"] > 0
