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


def select_role_stratified_users(
    node_attributes: pd.DataFrame,
    full_edges: pd.DataFrame,
    config: dict,
    expected_subreddits: list[str] | tuple[str, ...],
) -> pd.DataFrame:
    """Seleciona papeis estruturais e conecta a periferia ao nucleo amostrado."""
    maximum = int(config["maximum_nodes"])
    role_limits = {
        str(role): int(limit)
        for role, limit in config["segmented_role_nodes"].items()
    }
    if sum(role_limits.values()) > maximum:
        raise ValueError(
            "A soma de segmented_role_nodes ultrapassa selection.maximum_nodes."
        )

    selected: dict[str, str] = {}

    def role_count(role: str) -> int:
        return sum(
            reason == f"structural_role:{role}" for reason in selected.values()
        )

    def add_ranked(frame: pd.DataFrame, role: str, limit: int) -> None:
        if limit <= 0 or frame.empty:
            return
        per_subreddit = max(1, limit // max(len(expected_subreddits), 1))
        for subreddit in expected_subreddits:
            candidates = _rank(
                frame[frame["primary_subreddit"] == subreddit]
            ).head(per_subreddit)
            for user_hash in candidates["user_hash"].astype(str):
                if len(selected) < maximum and role_count(role) < limit:
                    selected.setdefault(user_hash, f"structural_role:{role}")
        for user_hash in _rank(frame)["user_hash"].astype(str):
            if len(selected) >= maximum or role_count(role) >= limit:
                break
            selected.setdefault(user_hash, f"structural_role:{role}")

    # Primeiro seleciona o nucleo e os papeis intermediarios.
    for role in ("central", "bridge", "ordinary"):
        add_ranked(
            node_attributes[node_attributes["node_role"] == role],
            role,
            role_limits.get(role, 0),
        )

    # A periferia e escolhida entre usuarios ligados ao conjunto acima. Assim,
    # os nos de baixo grau permanecem visiveis no subgrafo induzido.
    anchors = set(selected)
    connected_edges = full_edges[
        full_edges["node_a"].astype(str).isin(anchors)
        | full_edges["node_b"].astype(str).isin(anchors)
    ]
    connected_users = set(connected_edges["node_a"].astype(str)) | set(
        connected_edges["node_b"].astype(str)
    )
    peripheral = node_attributes[
        (node_attributes["node_role"] == "peripheral")
        & node_attributes["user_hash"].astype(str).isin(connected_users - anchors)
    ]
    add_ranked(peripheral, "peripheral", role_limits.get("peripheral", 0))

    # Completa eventuais cotas sem alterar a prioridade dos papeis ja escolhidos.
    for role in ("peripheral", "ordinary", "central", "bridge"):
        if role_count(role) >= role_limits.get(role, 0):
            continue
        candidates = node_attributes[
            (node_attributes["node_role"] == role)
            & ~node_attributes["user_hash"].astype(str).isin(selected)
        ]
        add_ranked(candidates, role, role_limits.get(role, 0))

    result = node_attributes[
        node_attributes["user_hash"].astype(str).isin(selected)
    ].copy()
    result["selection_reason"] = result["user_hash"].astype(str).map(selected)
    return result.sort_values(
        ["node_role", "primary_subreddit", "weighted_degree_full", "user_hash"],
        ascending=[True, True, False, True],
    ).reset_index(drop=True)


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
