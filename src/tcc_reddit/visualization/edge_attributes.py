"""Contexto semantico das arestas usuario-usuario."""

from __future__ import annotations

import pandas as pd


def calculate_edge_context_attributes(
    detailed_edges: pd.DataFrame,
    node_attributes: pd.DataFrame,
) -> pd.DataFrame:
    """Agrega pares sem alterar pesos e identifica o subreddit dominante."""
    required = {"source", "target", "subreddit", "weight"}
    if missing := required - set(detailed_edges.columns):
        raise ValueError(f"Colunas ausentes nas arestas detalhadas: {sorted(missing)}")
    edges = detailed_edges.dropna(subset=["source", "target", "subreddit"]).copy()
    edges = edges[edges["source"] != edges["target"]]
    edges["node_a"] = edges[["source", "target"]].min(axis=1).astype(str)
    edges["node_b"] = edges[["source", "target"]].max(axis=1).astype(str)
    edges["weight"] = pd.to_numeric(edges["weight"], errors="raise")
    per_subreddit = (
        edges.groupby(["node_a", "node_b", "subreddit"], as_index=False)["weight"]
        .sum()
        .rename(columns={"weight": "subreddit_weight"})
    )
    dominant = (
        per_subreddit.sort_values(
            ["node_a", "node_b", "subreddit_weight", "subreddit"],
            ascending=[True, True, False, True],
            kind="mergesort",
        )
        .drop_duplicates(["node_a", "node_b"])
        [["node_a", "node_b", "subreddit"]]
        .rename(columns={"subreddit": "dominant_subreddit"})
    )
    aggregated = per_subreddit.groupby(["node_a", "node_b"], as_index=False).agg(
        total_weight=("subreddit_weight", "sum"),
        subreddit_count=("subreddit", "nunique"),
        subreddits=("subreddit", lambda values: "|".join(sorted(set(values)))),
    )
    aggregated = aggregated.merge(dominant, on=["node_a", "node_b"], how="left")
    lookup = node_attributes.set_index("user_hash")
    primary = lookup["primary_subreddit"].to_dict()
    blocks = lookup["block"].to_dict()
    aggregated["cross_primary_subreddit"] = aggregated.apply(
        lambda row: primary.get(row.node_a) != primary.get(row.node_b), axis=1
    )

    def cross_block(row) -> bool:
        left, right = blocks.get(row.node_a), blocks.get(row.node_b)
        return bool(left and right and left != right)

    aggregated["cross_block"] = aggregated.apply(cross_block, axis=1)
    return aggregated.sort_values(["node_a", "node_b"]).reset_index(drop=True)
