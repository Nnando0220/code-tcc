"""Layouts reproduziveis, inclusive coordenadas comuns entre variantes."""

from __future__ import annotations

import math

import networkx as nx


def _normalize(positions: dict, scale: float = 100.0) -> dict[str, tuple[float, float, float]]:
    if not positions:
        return {}
    xs = [float(value[0]) for value in positions.values()]
    ys = [float(value[1]) for value in positions.values()]
    center_x = (min(xs) + max(xs)) / 2
    center_y = (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-12)
    return {
        str(node): (
            (float(value[0]) - center_x) * 2 * scale / span,
            (float(value[1]) - center_y) * 2 * scale / span,
            0.0,
        )
        for node, value in positions.items()
    }


def calculate_layout(graph: nx.Graph, seed: int) -> dict[str, tuple[float, float, float]]:
    if graph.number_of_nodes() == 0:
        return {}
    if graph.number_of_nodes() == 1:
        node = next(iter(graph.nodes()))
        return {str(node): (0.0, 0.0, 0.0)}
    # forceatlas2_layout ainda nao esta disponivel em todas as versoes suportadas
    # do NetworkX. Spring/Kamada-Kawai preserva o contrato deterministico.
    if hasattr(nx, "forceatlas2_layout"):
        positions = nx.forceatlas2_layout(
            graph, seed=seed, weight="total_weight", max_iter=300
        )
    else:
        positions = nx.spring_layout(
            graph, seed=seed, weight="total_weight", iterations=200
        )
    return _normalize(positions)


def calculate_shared_layout(
    observational_graph: nx.Graph,
    balanced_graph: nx.Graph,
    seed: int,
) -> dict[str, tuple[float, float, float]]:
    """Calcula uma unica geometria sobre a uniao das duas redes."""
    union = nx.Graph()
    union.add_nodes_from(set(observational_graph) | set(balanced_graph))
    for graph in (observational_graph, balanced_graph):
        for source, target, data in graph.edges(data=True):
            weight = float(data.get("total_weight", 1.0))
            if union.has_edge(source, target):
                union[source][target]["total_weight"] = max(
                    union[source][target]["total_weight"], weight
                )
            else:
                union.add_edge(source, target, total_weight=weight)
    return calculate_layout(union, seed)


def calculate_bipartite_layout(
    graph: nx.Graph,
    brazilian_subreddits: list[str] | tuple[str, ...],
    international_subreddits: list[str] | tuple[str, ...],
) -> dict[str, tuple[float, float, float]]:
    """Layout categorico: Brasil à esquerda, pontes ao centro e exterior à direita."""
    positions: dict[str, tuple[float, float, float]] = {}

    def subreddit_positions(names, x):
        count = max(len(names), 1)
        for index, subreddit in enumerate(names):
            y = 90 - index * 180 / max(count - 1, 1)
            positions[f"subreddit:{subreddit}"] = (float(x), float(y), 0.0)

    subreddit_positions(brazilian_subreddits, -100)
    subreddit_positions(international_subreddits, 100)
    users = sorted(
        (node for node, data in graph.nodes(data=True) if data.get("node_type") == "user"),
        key=lambda node: (
            -float(graph.nodes[node].get("weighted_degree_full", 0)), str(node)
        ),
    )
    for index, user in enumerate(users):
        # Distribuicao em varias colunas centrais evita uma linha vertical ilegivel.
        column = (index % 5) - 2
        row = index // 5
        y = 92 - (row % 24) * 8
        jitter = 2.5 * math.sin(index * 1.7)
        positions[str(user)] = (float(column * 9), float(y + jitter), 0.0)
    return positions
