"""Amostragem estratificada e auditavel dos nos de visualizacao."""

from __future__ import annotations

from collections import defaultdict
import math

import pandas as pd


RANK_COLUMNS = [
    "betweenness_full",
    "weighted_degree_full",
    "subreddit_count",
    "participation_entropy",
    "user_hash",
]
RANK_ASCENDING = [False, False, False, False, True]


def _rank(frame: pd.DataFrame, *, bridge_first: bool = False) -> pd.DataFrame:
    columns = RANK_COLUMNS
    ascending = RANK_ASCENDING
    if not bridge_first:
        columns = ["weighted_degree_full", "betweenness_full", "user_hash"]
        ascending = [False, False, True]
    return frame.sort_values(columns, ascending=ascending, kind="mergesort")


def select_stratified_users(
    node_attributes: pd.DataFrame,
    config: dict,
    expected_subreddits: list[str] | tuple[str, ...],
) -> pd.DataFrame:
    """Seleciona por comunidade principal, pontes e preenchimento central."""
    maximum = int(config["maximum_nodes"])
    per_subreddit = int(config["nodes_per_subreddit"])
    selected: dict[str, list[str]] = defaultdict(list)
    lookup = node_attributes.set_index("user_hash")

    def add(user_hash: str, reason: str) -> None:
        if len(selected) >= maximum:
            return
        if reason not in selected[user_hash]:
            selected[user_hash].append(reason)

    for subreddit in expected_subreddits:
        candidates = node_attributes[
            node_attributes["primary_subreddit"] == subreddit
        ]
        ranked = _rank(candidates)
        # Reserva representacao dos dois papeis quando ambos existem.
        exclusive = ranked[~ranked["is_bridge"]].head(1)
        bridges = _rank(ranked[ranked["is_bridge"]], bridge_first=True).head(1)
        for row in pd.concat([exclusive, bridges]).drop_duplicates("user_hash").itertuples():
            add(str(row.user_hash), "top_primary_subreddit")
        for row in ranked.itertuples():
            current = sum(
                lookup.loc[user, "primary_subreddit"] == subreddit
                for user in selected
            )
            if current >= per_subreddit:
                break
            add(str(row.user_hash), "top_primary_subreddit")

    bridges = _rank(node_attributes[node_attributes["is_bridge"]], bridge_first=True)
    for row in bridges.head(int(config["bridge_nodes"])).itertuples():
        add(str(row.user_hash), "top_bridge")

    cross = _rank(
        node_attributes[node_attributes["is_cross_block_bridge"]], bridge_first=True
    )
    for row in cross.head(int(config["cross_block_bridge_nodes"])).itertuples():
        add(str(row.user_hash), "cross_block_bridge")

    if config.get("fill_remaining", True):
        counts: dict[str, int] = defaultdict(int)
        for user_hash in selected:
            counts[str(lookup.loc[user_hash, "primary_subreddit"])] += 1
        soft_cap = max(per_subreddit, math.ceil(maximum / len(expected_subreddits)))
        for row in _rank(node_attributes).itertuples():
            if len(selected) >= maximum:
                break
            subreddit = str(row.primary_subreddit)
            if counts[subreddit] >= soft_cap or str(row.user_hash) in selected:
                continue
            add(str(row.user_hash), "centrality_fill")
            counts[subreddit] += 1

    selected_rows = node_attributes[
        node_attributes["user_hash"].isin(selected)
    ].copy()
    selected_rows["selection_reason"] = selected_rows["user_hash"].map(
        lambda value: "|".join(selected[str(value)])
    )
    return selected_rows.sort_values(
        ["primary_subreddit", "weighted_degree_full", "user_hash"],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def select_bridge_users(node_attributes: pd.DataFrame, maximum: int) -> pd.DataFrame:
    return _rank(node_attributes[node_attributes["is_bridge"]], bridge_first=True).head(
        maximum
    )


def build_matched_attributes(
    observational: pd.DataFrame,
    balanced: pd.DataFrame,
) -> pd.DataFrame:
    """Cria atributos comuns usando a maior centralidade das variantes."""
    common = set(observational["user_hash"]) & set(balanced["user_hash"])
    obs = observational[observational["user_hash"].isin(common)].set_index("user_hash")
    bal = balanced[balanced["user_hash"].isin(common)].set_index("user_hash")
    result = obs.copy()
    for column in ("weighted_degree_full", "betweenness_full", "subreddit_count", "participation_entropy"):
        result[column] = pd.concat([obs[column], bal[column]], axis=1).max(axis=1)
    result["is_bridge"] = obs["is_bridge"] | bal["is_bridge"]
    result["is_cross_block_bridge"] = (
        obs["is_cross_block_bridge"] | bal["is_cross_block_bridge"]
    )
    result.loc[result["is_cross_block_bridge"], "block"] = "Misto"
    result.loc[result["is_cross_block_bridge"], "node_role"] = "bridge"
    return result.reset_index()
