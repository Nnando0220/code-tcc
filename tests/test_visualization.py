"""Contratos da camada exclusiva de visualizacao."""

from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from ._bootstrap import ROOT  # noqa: F401
from tcc_reddit.visualization.edge_attributes import calculate_edge_context_attributes
from tcc_reddit.visualization.exporters import (
    export_graph,
    generate_display_mapping,
    prepare_graph_for_export,
)
from tcc_reddit.visualization.graph_builders import (
    build_bridge_bipartite_graph,
    build_user_graph,
)
from tcc_reddit.visualization.layouts import calculate_shared_layout
from tcc_reddit.visualization.node_attributes import (
    calculate_user_membership_attributes,
)
from tcc_reddit.visualization.palettes import BLOCK_COLORS, ROLE_COLORS
from tcc_reddit.visualization.sampling import (
    select_role_stratified_users,
    select_stratified_users,
)
from tcc_reddit.visualization.validation import validate_visualization_graph


BRAZIL = ("brasil", "brasilivre")
INTERNATIONAL = ("politics", "news")


def test_membership_attributes_use_documented_tie_breakers():
    memberships = pd.DataFrame(
        [
            {"source": "A", "target": "brasil", "weight": 10},
            {"source": "A", "target": "politics", "weight": 10},
            {"source": "B", "target": "news", "weight": 8},
        ]
    )
    counts = pd.DataFrame(
        [
            {"source": "A", "target": "brasil", "comments_count": 8, "posts_count": 2},
            {"source": "A", "target": "politics", "comments_count": 9, "posts_count": 1},
            {"source": "B", "target": "news", "comments_count": 7, "posts_count": 1},
        ]
    )
    result = calculate_user_membership_attributes(
        memberships, BRAZIL, INTERNATIONAL, counts
    ).set_index("user_hash")

    assert result.loc["A", "primary_subreddit"] == "politics"
    assert result.loc["A", "primary_share"] == pytest.approx(0.5)
    assert result.loc["A", "subreddit_count"] == 2
    assert bool(result.loc["A", "is_bridge"])
    assert result.loc["A", "block"] == "Misto"
    assert bool(result.loc["A", "is_cross_block_bridge"])
    assert result.loc["B", "block"] == "Internacional"


def _node_attributes() -> pd.DataFrame:
    rows = []
    for index, subreddit in enumerate((*BRAZIL, *INTERNATIONAL)):
        for offset in range(4):
            rows.append(
                {
                    "user_hash": f"{subreddit}-{offset}",
                    "primary_subreddit": subreddit,
                    "primary_share": 1.0 if offset == 0 else 0.6,
                    "subreddit_count": 1 if offset == 0 else 2,
                    "is_bridge": offset > 0,
                    "block": "Brasil" if subreddit in BRAZIL else "Internacional",
                    "is_cross_block_bridge": offset == 3,
                    "participation_entropy": offset / 10,
                    "total_participation": 20 - offset,
                    "weighted_degree_full": 100 - index * 10 - offset,
                    "betweenness_full": offset / 100,
                    "community_full": index,
                    "node_role": "bridge" if offset == 3 else "ordinary",
                }
            )
    return pd.DataFrame(rows)


def test_stratified_selection_represents_every_subreddit_and_is_bounded():
    attributes = _node_attributes()
    selected = select_stratified_users(
        attributes,
        {
            "maximum_nodes": 12,
            "nodes_per_subreddit": 2,
            "bridge_nodes": 2,
            "cross_block_bridge_nodes": 2,
            "fill_remaining": True,
        },
        (*BRAZIL, *INTERNATIONAL),
    )
    assert len(selected) <= 12
    assert set(selected["primary_subreddit"]) == set((*BRAZIL, *INTERNATIONAL))
    assert selected["selection_reason"].str.len().gt(0).all()
    assert selected["is_cross_block_bridge"].any()


def test_edge_context_preserves_weight_and_adds_semantics():
    detailed = pd.DataFrame(
        [
            {"source": "A", "target": "B", "subreddit": "brasil", "weight": 3},
            {"source": "B", "target": "A", "subreddit": "brasil", "weight": 2},
            {"source": "A", "target": "B", "subreddit": "politics", "weight": 1},
        ]
    )
    nodes = pd.DataFrame(
        [
            {"user_hash": "A", "primary_subreddit": "brasil", "block": "Misto"},
            {"user_hash": "B", "primary_subreddit": "politics", "block": "Internacional"},
        ]
    )
    result = calculate_edge_context_attributes(detailed, nodes).iloc[0]
    assert result["total_weight"] == 6
    assert result["dominant_subreddit"] == "brasil"
    assert result["subreddit_count"] == 2
    assert bool(result["cross_primary_subreddit"])
    assert bool(result["cross_block"])


def test_shared_layout_and_gexf_keep_coordinates_and_private_labels(tmp_path: Path):
    attributes = _node_attributes().head(3).copy()
    edges = pd.DataFrame(
        [
            {
                "node_a": attributes.iloc[0]["user_hash"],
                "node_b": attributes.iloc[1]["user_hash"],
                "total_weight": 3,
                "dominant_subreddit": "brasil",
                "subreddit_count": 1,
                "subreddits": "brasil",
                "cross_primary_subreddit": False,
                "cross_block": False,
            },
            {
                "node_a": attributes.iloc[1]["user_hash"],
                "node_b": attributes.iloc[2]["user_hash"],
                "total_weight": 2,
                "dominant_subreddit": "brasil",
                "subreddit_count": 1,
                "subreddits": "brasil",
                "cross_primary_subreddit": False,
                "cross_block": False,
            },
        ]
    )
    first = build_user_graph(edges, attributes)
    second = first.edge_subgraph(list(first.edges())[:1]).copy()
    second.add_nodes_from((node, dict(first.nodes[node])) for node in first if node not in second)
    positions = calculate_shared_layout(first, second, 42)
    mapping = generate_display_mapping(first.nodes())
    prepared = prepare_graph_for_export(
        first,
        display_mapping=mapping,
        positions=positions,
        color_mode="primary",
        node_size_config={"attribute": "weighted_degree_full", "minimum": 6, "maximum": 45},
        edge_width_config={"attribute": "total_weight", "minimum": 0.2, "maximum": 3.0},
    )
    path = tmp_path / "network.gexf"
    export_graph(prepared, path, title="Teste", color_mode="primary")
    loaded = nx.read_gexf(path)

    assert set(positions) == set(first.nodes())
    assert all(str(node).startswith("U") for node in loaded.nodes())
    assert all(data["label"].startswith("U") for _, data in loaded.nodes(data=True))
    assert all("viz" in data for _, data in loaded.nodes(data=True))


def test_validation_rejects_artificial_edges():
    full = nx.Graph()
    full.add_edge("A", "B", total_weight=2)
    visual = nx.Graph()
    for node in ("A", "C"):
        visual.add_node(
            node,
            node_type="user",
            primary_subreddit="brasil",
            block="Brasil",
            is_cross_block_bridge=False,
            label=f"U{node}",
        )
    visual.add_edge("A", "C", total_weight=2)
    with pytest.raises(ValueError, match="inexistente"):
        validate_visualization_graph(visual, full, maximum_nodes=10)


def test_role_selection_includes_connected_periphery():
    rows = []
    for index, role in enumerate(("central", "bridge", "ordinary", "peripheral")):
        rows.append(
            {
                "user_hash": f"user-{role}",
                "primary_subreddit": BRAZIL[index % 2],
                "primary_share": 1.0,
                "subreddit_count": 2 if role == "bridge" else 1,
                "is_bridge": role == "bridge",
                "block": "Misto" if role == "bridge" else "Brasil",
                "is_cross_block_bridge": role == "bridge",
                "participation_entropy": 0.0,
                "total_participation": 4,
                "weighted_degree_full": 10 - index,
                "betweenness_full": 0.1,
                "community_full": 0,
                "node_role": role,
            }
        )
    attributes = pd.DataFrame(rows)
    edges = pd.DataFrame(
        [
            {"node_a": "user-central", "node_b": "user-bridge", "weight": 2},
            {"node_a": "user-central", "node_b": "user-ordinary", "weight": 1},
            {"node_a": "user-central", "node_b": "user-peripheral", "weight": 1},
        ]
    )
    selected = select_role_stratified_users(
        attributes,
        edges,
        {
            "maximum_nodes": 4,
            "segmented_role_nodes": {
                "central": 1,
                "bridge": 1,
                "ordinary": 1,
                "peripheral": 1,
            },
        },
        BRAZIL,
    )
    assert set(selected["node_role"]) == {
        "central",
        "bridge",
        "ordinary",
        "peripheral",
    }


def test_bridge_graph_and_export_colors_use_blocks_and_roles():
    memberships = pd.DataFrame(
        [
            {"source": "long-private-user-id", "target": "brasil", "weight": 2},
            {"source": "long-private-user-id", "target": "politics", "weight": 1},
        ]
    )
    attributes = pd.DataFrame(
        [
            {
                "user_hash": "long-private-user-id",
                "primary_subreddit": "brasil",
                "block": "Misto",
                "node_role": "bridge",
                "weighted_degree_full": 3,
            }
        ]
    )
    graph = build_bridge_bipartite_graph(
        memberships,
        attributes,
        ("brasil", "politics"),
        ("brasil",),
    )
    positions = {
        str(node): (float(index), 0.0, 0.0)
        for index, node in enumerate(graph.nodes())
    }
    prepared = prepare_graph_for_export(
        graph,
        display_mapping={"long-private-user-id": "U0001"},
        positions=positions,
        color_mode="block",
        node_size_config={
            "attribute": "weighted_degree_full",
            "minimum": 6,
            "maximum": 45,
        },
        edge_width_config={
            "attribute": "total_weight",
            "minimum": 0.2,
            "maximum": 3.0,
        },
    )
    assert prepared.nodes["subreddit:brasil"]["visual_color"] == BLOCK_COLORS["Brasil"]
    assert (
        prepared.nodes["subreddit:politics"]["visual_color"]
        == BLOCK_COLORS["Internacional"]
    )
    assert prepared.nodes["U0001"]["visual_color"] == BLOCK_COLORS["Misto"]

    role_graph = nx.Graph()
    role_graph.add_node(
        "private",
        node_type="user",
        node_role="peripheral",
        weighted_degree_full=1,
    )
    role_prepared = prepare_graph_for_export(
        role_graph,
        display_mapping={"private": "U0002"},
        positions={"private": (0.0, 0.0, 0.0)},
        color_mode="role",
        node_size_config={
            "attribute": "weighted_degree_full",
            "minimum": 6,
            "maximum": 45,
        },
        edge_width_config={
            "attribute": "total_weight",
            "minimum": 0.2,
            "maximum": 3.0,
        },
    )
    assert role_prepared.nodes["U0002"]["visual_color"] == ROLE_COLORS["peripheral"]
