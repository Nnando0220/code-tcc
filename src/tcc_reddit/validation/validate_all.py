"""Auditoria final de uma execucao publicada."""

from __future__ import annotations

import json

import pandas as pd

from ..paths import RunPaths
from ..settings import PipelineConfig
from .data_quality import (
    validate_comment_ancestors,
    validate_final_dataset,
    validate_temporal_window,
    validate_weight_preservation,
)
from .graph_quality import validate_gexf_edge_count
from .privacy import validate_processed_privacy, validate_raw_is_not_under_results


def validate_run(config: PipelineConfig, paths: RunPaths) -> dict:
    posts_path = paths.processed_observational / "posts.parquet"
    comments_path = paths.processed_observational / "comments.parquet"
    edges_path = paths.observational / "networks" / "user_user_edges_detailed.csv"

    validate_processed_privacy(posts_path)
    validate_processed_privacy(comments_path)
    validate_raw_is_not_under_results(paths.raw, paths.results)

    posts = pd.read_parquet(posts_path)
    comments = pd.read_parquet(comments_path)
    edges = pd.read_csv(edges_path, low_memory=False)
    validate_final_dataset(
        posts,
        comments,
        edges,
        expected_subreddits=config.subreddits,
        expected_posts_per_subreddit=config.posts_per_subreddit,
    )
    validate_temporal_window(posts, config.window_start, config.window_end)

    balanced_posts_path = paths.processed_balanced / "posts.parquet"
    balanced_comments_path = paths.processed_balanced / "comments.parquet"
    validate_processed_privacy(balanced_posts_path)
    validate_processed_privacy(balanced_comments_path)
    balanced_posts = pd.read_parquet(balanced_posts_path)
    balanced_comments = pd.read_parquet(balanced_comments_path)
    balanced_edges = pd.read_csv(
        paths.balanced / "networks" / "user_user_edges_detailed.csv",
        low_memory=False,
    )
    validate_final_dataset(
        balanced_posts,
        balanced_comments,
        balanced_edges,
        expected_subreddits=config.subreddits,
        expected_posts_per_subreddit=config.posts_per_subreddit,
    )
    validate_temporal_window(
        balanced_posts,
        config.window_start,
        config.window_end,
    )
    validate_comment_ancestors(balanced_comments)

    graph_checks = {}
    for name in ("observational", "balanced"):
        variant = getattr(paths, name)
        pairs = {
            "directed": (
                variant / "networks" / "user_user_edges_directed.csv",
                variant / "gephi" / "user_user_directed.gexf",
            ),
            "undirected": (
                variant / "networks" / "user_user_edges_undirected.csv",
                variant / "gephi" / "user_user_undirected.gexf",
            ),
            "subreddit": (
                variant / "networks" / "subreddit_subreddit_edges.csv",
                variant / "gephi" / "subreddit_subreddit.gexf",
            ),
            "visualization": (
                variant / "gephi" / "user_user_visualization_edges.csv",
                variant / "gephi" / "user_user_visualization.gexf",
            ),
        }
        graph_checks[name] = {
            graph_name: validate_gexf_edge_count(*pair)
            for graph_name, pair in pairs.items()
        }

        detailed = pd.read_csv(
            variant / "networks" / "user_user_edges_detailed.csv",
            low_memory=False,
        )
        directed = pd.read_csv(
            variant / "networks" / "user_user_edges_directed.csv",
            low_memory=False,
        )
        undirected = pd.read_csv(
            variant / "networks" / "user_user_edges_undirected.csv",
            low_memory=False,
        )
        validate_weight_preservation(detailed, directed, undirected)

    result = {
        "run_id": config.run_id,
        "posts": len(posts),
        "comments": len(comments),
        "balanced_comments": len(balanced_comments),
        "graphs": graph_checks,
        "status": "valid",
    }
    output = paths.results / "validation_report.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
