"""Atributos de participacao e posicao calculados sobre as redes completas."""

from __future__ import annotations

import math
from pathlib import Path

import networkx as nx
import pandas as pd


NODE_COLUMNS = [
    "user_hash",
    "primary_subreddit",
    "primary_share",
    "subreddit_count",
    "is_bridge",
    "block",
    "is_cross_block_bridge",
    "participation_entropy",
    "total_participation",
    "weighted_degree_full",
    "betweenness_full",
    "community_full",
    "node_role",
]


def calculate_participation_type_counts(
    posts_path: str | Path,
    comments_path: str | Path,
) -> pd.DataFrame:
    """Conta posts e comentarios sem carregar o texto dos Parquets."""
    frames = []
    for path, column in ((posts_path, "posts_count"), (comments_path, "comments_count")):
        frame = pd.read_parquet(path, columns=["author_hash", "subreddit"])
        frame = frame.dropna(subset=["author_hash", "subreddit"])
        counts = (
            frame.groupby(["author_hash", "subreddit"], as_index=False)
            .size()
            .rename(columns={"size": column, "author_hash": "source", "subreddit": "target"})
        )
        frames.append(counts)
    return frames[0].merge(frames[1], on=["source", "target"], how="outer").fillna(0)


def _entropy(weights: pd.Series) -> float:
    total = float(weights.sum())
    if total <= 0:
        return 0.0
    shares = weights.astype(float) / total
    return float(-sum(value * math.log(value) for value in shares if value > 0))


def calculate_user_membership_attributes(
    user_subreddit_edges: pd.DataFrame,
    brazilian_subreddits: tuple[str, ...] | list[str],
    international_subreddits: tuple[str, ...] | list[str],
    participation_counts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Transfere a participacao usuario-subreddit para atributos dos nos."""
    required = {"source", "target", "weight"}
    if missing := required - set(user_subreddit_edges.columns):
        raise ValueError(f"Colunas ausentes em user_subreddit_edges: {sorted(missing)}")

    edges = user_subreddit_edges.dropna(subset=["source", "target"]).copy()
    edges["source"] = edges["source"].astype(str)
    edges["target"] = edges["target"].astype(str)
    edges["weight"] = pd.to_numeric(edges["weight"], errors="raise")
    if participation_counts is not None:
        tie = participation_counts.copy()
        tie["source"] = tie["source"].astype(str)
        tie["target"] = tie["target"].astype(str)
        edges = edges.merge(tie, on=["source", "target"], how="left")
    for column in ("comments_count", "posts_count"):
        if column not in edges:
            edges[column] = 0
        edges[column] = pd.to_numeric(edges[column], errors="coerce").fillna(0)

    ranked = edges.sort_values(
        ["source", "weight", "comments_count", "posts_count", "target"],
        ascending=[True, False, False, False, True],
        kind="mergesort",
    )
    primary = ranked.drop_duplicates("source").set_index("source")
    grouped = edges.groupby("source", sort=True)
    totals = grouped["weight"].sum()
    subreddit_count = grouped["target"].nunique()
    entropy = grouped["weight"].apply(_entropy)
    memberships = grouped["target"].agg(lambda values: frozenset(values))
    brazil = set(brazilian_subreddits)
    international = set(international_subreddits)

    rows = []
    for user_hash in totals.index:
        communities = memberships.loc[user_hash]
        in_brazil = bool(communities & brazil)
        in_international = bool(communities & international)
        block = "Misto" if in_brazil and in_international else (
            "Brasil" if in_brazil else "Internacional"
        )
        primary_weight = float(primary.loc[user_hash, "weight"])
        total = float(totals.loc[user_hash])
        count = int(subreddit_count.loc[user_hash])
        rows.append(
            {
                "user_hash": user_hash,
                "primary_subreddit": str(primary.loc[user_hash, "target"]),
                "primary_share": primary_weight / total if total else 0.0,
                "subreddit_count": count,
                "is_bridge": count >= 2,
                "block": block,
                "is_cross_block_bridge": block == "Misto",
                "participation_entropy": float(entropy.loc[user_hash]),
                "total_participation": total,
            }
        )
    return pd.DataFrame(rows)


def calculate_full_communities(
    full_edges: pd.DataFrame,
    *,
    seed: int,
) -> dict[str, int]:
    """Calcula Louvain sobre a rede completa, nunca sobre o subgrafo visual."""
    graph = nx.from_pandas_edgelist(
        full_edges,
        source="node_a",
        target="node_b",
        edge_attr="weight",
        create_using=nx.Graph(),
    )
    if graph.number_of_edges() == 0:
        return {str(node): 0 for node in graph.nodes()}
    try:
        import community as community_louvain

        partition = community_louvain.best_partition(
            graph, weight="weight", random_state=seed
        )
        return {str(node): int(value) for node, value in partition.items()}
    except ImportError:
        communities = nx.community.louvain_communities(
            graph, weight="weight", seed=seed
        )
        return {
            str(node): community_id
            for community_id, nodes in enumerate(communities)
            for node in nodes
        }


def enrich_with_full_network_metrics(
    membership: pd.DataFrame,
    centrality: pd.DataFrame,
    communities: dict[str, int],
) -> pd.DataFrame:
    """Une participacao às metricas oficiais calculadas na rede completa."""
    metrics = centrality.rename(
        columns={
            "weighted_degree": "weighted_degree_full",
            "betweenness_centrality": "betweenness_full",
        }
    )[["user_hash", "weighted_degree_full", "betweenness_full"]].copy()
    metrics["user_hash"] = metrics["user_hash"].astype(str)
    result = membership.merge(metrics, on="user_hash", how="left")
    result["weighted_degree_full"] = result["weighted_degree_full"].fillna(0.0)
    result["betweenness_full"] = result["betweenness_full"].fillna(0.0)
    result["community_full"] = result["user_hash"].map(communities).fillna(-1).astype(int)

    positive = result.loc[result["weighted_degree_full"] > 0, "weighted_degree_full"]
    low = float(positive.quantile(0.25)) if not positive.empty else 0.0
    high = float(positive.quantile(0.95)) if not positive.empty else 0.0
    result["node_role"] = "ordinary"
    result.loc[result["weighted_degree_full"] <= low, "node_role"] = "peripheral"
    result.loc[result["weighted_degree_full"] >= high, "node_role"] = "central"
    result.loc[result["is_cross_block_bridge"], "node_role"] = "bridge"
    return result[NODE_COLUMNS].sort_values("user_hash").reset_index(drop=True)
