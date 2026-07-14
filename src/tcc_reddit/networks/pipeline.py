"""Transformações reproduzíveis para as redes observacional e balanceada."""

from __future__ import annotations

import hashlib
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd


EDGE_DETAIL_COLUMNS = [
    "source",
    "target",
    "subreddit",
    "interaction_type",
    "weight",
]


def join_unique(values: pd.Series) -> str:
    return "|".join(sorted(set(values.dropna().astype(str))))


def aggregate_directed_edges(df_edges: pd.DataFrame) -> pd.DataFrame:
    """Soma todas as interações A -> B sem perder atributos de auditoria."""
    if df_edges.empty:
        return pd.DataFrame(
            columns=["source", "target", "weight", "subreddits", "interaction_types"]
        )
    clean = df_edges.dropna(subset=["source", "target"]).copy()
    clean = clean[clean["source"] != clean["target"]]
    return (
        clean.groupby(["source", "target"], as_index=False)
        .agg(
            weight=("weight", "sum"),
            subreddits=("subreddit", join_unique),
            interaction_types=("interaction_type", join_unique),
        )
        .sort_values(["source", "target"])
        .reset_index(drop=True)
    )


def aggregate_undirected_edges(df_edges: pd.DataFrame) -> pd.DataFrame:
    """Consolida A -> B e B -> A no mesmo par não direcionado."""
    if df_edges.empty:
        return pd.DataFrame(
            columns=["node_a", "node_b", "weight", "subreddits", "interaction_types"]
        )
    clean = df_edges.dropna(subset=["source", "target"]).copy()
    clean = clean[clean["source"] != clean["target"]]
    clean["node_a"] = clean[["source", "target"]].min(axis=1)
    clean["node_b"] = clean[["source", "target"]].max(axis=1)
    return (
        clean.groupby(["node_a", "node_b"], as_index=False)
        .agg(
            weight=("weight", "sum"),
            subreddits=("subreddit", join_unique),
            interaction_types=("interaction_type", join_unique),
        )
        .sort_values(["node_a", "node_b"])
        .reset_index(drop=True)
    )


def write_validated_gexf(
    df_edges: pd.DataFrame,
    output_path: str | Path,
    directed: bool,
    source: str,
    target: str,
    edge_attributes: list[str],
) -> nx.Graph:
    """Exporta GEXF e confirma que nenhuma aresta foi sobrescrita."""
    graph_type = nx.DiGraph() if directed else nx.Graph()
    graph = nx.from_pandas_edgelist(
        df_edges,
        source=source,
        target=target,
        edge_attr=edge_attributes,
        create_using=graph_type,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(graph, output_path)
    graph_check = nx.read_gexf(output_path)
    if graph_check.number_of_edges() != len(df_edges):
        raise ValueError(
            f"GEXF inválido: {graph_check.number_of_edges()} arestas gravadas para "
            f"{len(df_edges)} linhas agregadas em {output_path}."
        )
    return graph


def stable_seed(seed: int, value: str) -> int:
    digest = hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def select_posts_round_robin(
    subreddit_posts: pd.DataFrame,
    subreddit_collections: pd.DataFrame,
    target: int,
    sorts: list[str],
) -> list[str]:
    available = set(subreddit_posts["submission_id"].astype(str))
    collections = subreddit_collections.copy()
    collections["submission_id"] = collections["submission_id"].astype(str)
    collections = collections[collections["submission_id"].isin(available)]
    if "eligible" in collections.columns:
        collections = collections[collections["eligible"].fillna(False).astype(bool)]
    if "sort_rank" not in collections.columns:
        collections["sort_rank"] = collections.groupby("sort_origin").cumcount() + 1

    queues: dict[str, list[str]] = {}
    for sort_origin in sorts:
        rows = collections[collections["sort_origin"] == sort_origin].sort_values(
            ["sort_rank", "submission_id"]
        )
        queues[sort_origin] = rows["submission_id"].drop_duplicates().tolist()

    selected: list[str] = []
    selected_set: set[str] = set()
    positions = {sort_origin: 0 for sort_origin in sorts}
    while len(selected) < target:
        changed = False
        for sort_origin in sorts:
            queue = queues[sort_origin]
            while positions[sort_origin] < len(queue):
                submission_id = queue[positions[sort_origin]]
                positions[sort_origin] += 1
                if submission_id in selected_set:
                    continue
                selected.append(submission_id)
                selected_set.add(submission_id)
                changed = True
                break
            if len(selected) >= target:
                break
        if not changed:
            break

    if len(selected) < target:
        remaining = sorted(available - selected_set)
        selected.extend(remaining[: target - len(selected)])
    return selected


def _sample_comments_for_post(
    post_comments: pd.DataFrame,
    submission_id: str,
    max_comments: int,
    seed: int,
) -> tuple[pd.DataFrame, dict]:
    if post_comments.empty:
        return post_comments.copy(), {
            "submission_id": submission_id,
            "available_comments": 0,
            "quota_selected": 0,
            "ancestors_added": 0,
            "balanced_comments": 0,
        }

    comments = post_comments.drop_duplicates("comment_id").copy()
    comments["depth"] = pd.to_numeric(comments["depth"], errors="coerce").fillna(0).astype(int)
    comments["sampling_stratum"] = np.select(
        [comments["depth"] == 0, comments["depth"].between(1, 2)],
        ["depth_0", "depth_1_2"],
        default="depth_3_plus",
    )
    quotas = {
        "depth_0": round(max_comments * 0.40),
        "depth_1_2": round(max_comments * 0.40),
        "depth_3_plus": max_comments - 2 * round(max_comments * 0.40),
    }
    random_state = stable_seed(seed, submission_id)
    selected_ids: set[str] = set()
    for offset, (stratum, quota) in enumerate(quotas.items()):
        candidates = comments[comments["sampling_stratum"] == stratum]
        if len(candidates) <= quota:
            chosen = candidates
        else:
            chosen = candidates.sample(n=quota, random_state=random_state + offset)
        selected_ids.update(chosen["comment_id"].astype(str))

    if len(selected_ids) < max_comments:
        remaining = comments[~comments["comment_id"].astype(str).isin(selected_ids)]
        needed = min(max_comments - len(selected_ids), len(remaining))
        if needed:
            fill = remaining.sample(n=needed, random_state=random_state + 10)
            selected_ids.update(fill["comment_id"].astype(str))

    quota_ids = set(selected_ids)
    by_id = comments.set_index(comments["comment_id"].astype(str), drop=False)
    queue = list(selected_ids)
    while queue:
        comment_id = queue.pop()
        if comment_id not in by_id.index:
            continue
        parent_id = str(by_id.loc[comment_id, "parent_id"])
        if not parent_id.startswith("t1_"):
            continue
        parent_comment_id = parent_id.removeprefix("t1_")
        if parent_comment_id in by_id.index and parent_comment_id not in selected_ids:
            selected_ids.add(parent_comment_id)
            queue.append(parent_comment_id)

    sampled = comments[comments["comment_id"].astype(str).isin(selected_ids)].copy()
    sampled["sampling_role"] = np.where(
        sampled["comment_id"].astype(str).isin(quota_ids), "stratified", "ancestor"
    )
    sampled = sampled.sort_values(["created_utc", "comment_id"]).reset_index(drop=True)
    manifest = {
        "submission_id": submission_id,
        "available_comments": int(len(comments)),
        "quota_selected": int(len(quota_ids)),
        "ancestors_added": int(len(selected_ids - quota_ids)),
        "balanced_comments": int(len(sampled)),
    }
    return sampled, manifest


def build_balanced_datasets(
    df_posts: pd.DataFrame,
    df_comments: pd.DataFrame,
    df_collections: pd.DataFrame,
    target_posts_per_subreddit: int = 150,
    max_comments_per_post: int = 300,
    seed: int = 42,
    sorts: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Cria uma amostra comparável, sem alterar os dados observacionais."""
    sorts = sorts or ["top", "controversial", "hot", "new"]
    if df_posts.empty:
        return df_posts.copy(), df_comments.iloc[0:0].copy(), pd.DataFrame()

    counts = df_posts.groupby("subreddit")["submission_id"].nunique()
    effective_target = min(target_posts_per_subreddit, int(counts.min()))
    selected_ids: set[str] = set()
    for subreddit, subreddit_posts in df_posts.groupby("subreddit"):
        collections = df_collections[df_collections["subreddit"] == subreddit]
        selected_ids.update(
            select_posts_round_robin(
                subreddit_posts,
                collections,
                effective_target,
                sorts,
            )
        )

    balanced_posts = df_posts[
        df_posts["submission_id"].astype(str).isin(selected_ids)
    ].copy()
    balanced_comments_parts = []
    manifest_rows = []
    for submission_id in sorted(selected_ids):
        post_comments = df_comments[
            df_comments["submission_id"].astype(str) == submission_id
        ]
        sampled, manifest = _sample_comments_for_post(
            post_comments,
            submission_id,
            max_comments_per_post,
            seed,
        )
        post_row = balanced_posts[
            balanced_posts["submission_id"].astype(str) == submission_id
        ].iloc[0]
        announced = int(post_row.get("num_comments", 0) or 0)
        manifest.update(
            {
                "subreddit": post_row["subreddit"],
                "announced_comments": announced,
                "source_coverage_estimate": (
                    manifest["available_comments"] / announced if announced else None
                ),
                "target_posts_per_subreddit": target_posts_per_subreddit,
                "effective_posts_per_subreddit": effective_target,
                "max_comments_per_post": max_comments_per_post,
                "random_seed": seed,
            }
        )
        manifest_rows.append(manifest)
        balanced_comments_parts.append(sampled)

    balanced_comments = (
        pd.concat(balanced_comments_parts, ignore_index=True)
        if balanced_comments_parts
        else df_comments.iloc[0:0].copy()
    )
    return balanced_posts, balanced_comments, pd.DataFrame(manifest_rows)


def comment_coverage_by_subreddit(
    df_posts: pd.DataFrame, df_comments: pd.DataFrame
) -> pd.DataFrame:
    announced = df_posts.groupby("subreddit")["num_comments"].sum()
    stored = df_comments.groupby("subreddit").size()
    result = pd.concat(
        [announced.rename("announced_comments"), stored.rename("stored_comments")],
        axis=1,
    ).fillna(0)
    result["announced_comments"] = result["announced_comments"].astype(int)
    result["stored_comments"] = result["stored_comments"].astype(int)
    result["coverage_estimate"] = np.where(
        result["announced_comments"] > 0,
        result["stored_comments"] / result["announced_comments"],
        np.nan,
    )
    return result.reset_index()
