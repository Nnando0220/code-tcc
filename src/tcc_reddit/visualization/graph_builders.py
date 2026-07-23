"""Construtores dos subgrafos sem modificar os grafos analiticos."""

from __future__ import annotations

from collections import Counter

import networkx as nx
import pandas as pd


EDGE_ATTRIBUTES = [
    "total_weight",
    "dominant_subreddit",
    "subreddit_count",
    "subreddits",
    "cross_primary_subreddit",
    "cross_block",
]


def build_user_graph(
    enriched_edges: pd.DataFrame,
    selected_attributes: pd.DataFrame,
) -> nx.Graph:
    selected = set(selected_attributes["user_hash"].astype(str))
    edges = enriched_edges[
        enriched_edges["node_a"].isin(selected)
        & enriched_edges["node_b"].isin(selected)
    ]
    graph = nx.from_pandas_edgelist(
        edges,
        source="node_a",
        target="node_b",
        edge_attr=EDGE_ATTRIBUTES,
        create_using=nx.Graph(),
    )
    attributes = selected_attributes.set_index("user_hash").to_dict("index")
    for node in selected:
        graph.add_node(node, **attributes[node], node_type="user")
    return graph


def filter_components(graph: nx.Graph, config: dict) -> tuple[nx.Graph, dict]:
    before = graph.number_of_nodes()
    result = graph.copy()
    if config.get("remove_isolates", True):
        result.remove_nodes_from(list(nx.isolates(result)))
    if result.number_of_nodes():
        components = list(nx.connected_components(result))
        if config.get("keep_largest_component_only", False):
            keep = max(components, key=len)
        else:
            minimum = int(config.get("minimum_component_size", 1))
            keep = set().union(*(part for part in components if len(part) >= minimum))
        result = result.subgraph(keep).copy()
    return result, {
        "nodes_before_component_filter": before,
        "nodes_after_component_filter": result.number_of_nodes(),
        "nodes_removed": before - result.number_of_nodes(),
        "components_after_filter": nx.number_connected_components(result)
        if result.number_of_nodes()
        else 0,
    }


def build_bridge_bipartite_graph(
    user_subreddit_edges: pd.DataFrame,
    bridge_attributes: pd.DataFrame,
    subreddits: list[str] | tuple[str, ...],
) -> nx.Graph:
    users = set(bridge_attributes["user_hash"].astype(str))
    memberships = user_subreddit_edges[user_subreddit_edges["source"].isin(users)]
    graph = nx.Graph()
    for subreddit in subreddits:
        graph.add_node(
            f"subreddit:{subreddit}",
            label=f"r/{subreddit}",
            node_type="subreddit",
            subreddit=subreddit,
            weighted_degree_full=float(
                memberships.loc[memberships["target"] == subreddit, "weight"].sum()
            ),
        )
    lookup = bridge_attributes.set_index("user_hash").to_dict("index")
    for user in users:
        graph.add_node(user, **lookup[user], node_type="user")
    for row in memberships.itertuples(index=False):
        graph.add_edge(
            str(row.source),
            f"subreddit:{row.target}",
            total_weight=float(row.weight),
            dominant_subreddit=str(row.target),
            cross_block=False,
        )
    return graph


def build_subreddit_overlap_graph(
    user_subreddit_edges: pd.DataFrame,
    subreddit_edges: pd.DataFrame,
    node_attributes: pd.DataFrame,
    brazilian_subreddits: list[str] | tuple[str, ...],
    international_subreddits: list[str] | tuple[str, ...],
) -> nx.Graph:
    memberships = user_subreddit_edges.copy()
    memberships["source"] = memberships["source"].astype(str)
    users_by_subreddit = memberships.groupby("target")["source"].agg(set).to_dict()
    graph = nx.Graph()
    brazil = set(brazilian_subreddits)
    for subreddit in [*brazilian_subreddits, *international_subreddits]:
        users = users_by_subreddit.get(subreddit, set())
        user_rows = node_attributes[node_attributes["user_hash"].isin(users)]
        graph.add_node(
            subreddit,
            label=f"r/{subreddit}",
            node_type="subreddit",
            subreddit=subreddit,
            block="Brasil" if subreddit in brazil else "Internacional",
            users_count=len(users),
            exclusive_users=int((user_rows["subreddit_count"] == 1).sum()),
            bridge_users=int(user_rows["is_bridge"].sum()),
            weighted_degree=float(
                memberships.loc[memberships["target"] == subreddit, "weight"].sum()
            ),
            weighted_degree_full=float(
                memberships.loc[memberships["target"] == subreddit, "weight"].sum()
            ),
        )
    for row in subreddit_edges.itertuples(index=False):
        left = users_by_subreddit.get(str(row.source), set())
        right = users_by_subreddit.get(str(row.target), set())
        shared = len(left & right)
        union = len(left | right)
        minimum = min(len(left), len(right))
        graph.add_edge(
            str(row.source),
            str(row.target),
            total_weight=float(row.weight),
            shared_users=shared,
            jaccard=shared / union if union else 0.0,
            overlap_coefficient=shared / minimum if minimum else 0.0,
            cross_block=(str(row.source) in brazil) != (str(row.target) in brazil),
        )
    return graph


def graph_summary(graph: nx.Graph) -> dict:
    primary = Counter(
        data.get("primary_subreddit")
        for _, data in graph.nodes(data=True)
        if data.get("node_type") == "user"
    )
    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "total_weight": float(
            sum(data.get("total_weight", 0.0) for _, _, data in graph.edges(data=True))
        ),
        "primary_subreddit_counts": dict(sorted(primary.items())),
    }
