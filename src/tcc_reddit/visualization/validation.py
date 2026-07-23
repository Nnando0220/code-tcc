"""Invariantes que impedem artefatos visuais metodologicamente invalidos."""

from __future__ import annotations

import re

import networkx as nx


HASH_LABEL = re.compile(r"^[0-9a-fA-F]{48,}$")


def _pair(source: str, target: str) -> tuple[str, str]:
    return tuple(sorted((str(source), str(target))))


def validate_visualization_graph(
    graph: nx.Graph,
    full_graph: nx.Graph,
    *,
    maximum_nodes: int | None,
    expected_subreddits: list[str] | tuple[str, ...] | None = None,
    exact_edge_weights: bool = True,
) -> None:
    if any(node is None or str(node).strip() == "" for node in graph.nodes()):
        raise ValueError("Grafo de visualizacao contem no sem identificador.")
    if nx.number_of_selfloops(graph):
        raise ValueError("Grafo de visualizacao contem autointeracao.")
    if maximum_nodes is not None and graph.number_of_nodes() > maximum_nodes:
        raise ValueError("O limite maximo de nos da visualizacao foi ultrapassado.")

    for node, data in graph.nodes(data=True):
        if data.get("node_type") == "user":
            if not data.get("primary_subreddit"):
                raise ValueError(f"primary_subreddit ausente no usuario {node}.")
            if data.get("block") == "Misto" and not data.get("is_cross_block_bridge"):
                raise ValueError(f"Usuario misto nao marcado como ponte: {node}.")
        label = str(data.get("label", ""))
        if HASH_LABEL.fullmatch(label):
            raise ValueError("Um hash completo foi exposto como rotulo.")

    if expected_subreddits:
        represented = {
            data.get("primary_subreddit")
            for _, data in graph.nodes(data=True)
            if data.get("node_type") == "user"
        }
        missing = set(expected_subreddits) - represented
        if missing:
            raise ValueError(
                "Subreddits sem representacao no grafo visual: " + ", ".join(sorted(missing))
            )

    full_edges = {
        _pair(source, target): float(data.get("total_weight", data.get("weight", 0)))
        for source, target, data in full_graph.edges(data=True)
    }
    visual_sum = 0.0
    for source, target, data in graph.edges(data=True):
        pair = _pair(source, target)
        if pair not in full_edges:
            raise ValueError(f"Aresta visual inexistente na rede completa: {pair}.")
        weight = float(data.get("total_weight", data.get("weight", 0)))
        invalid_weight = (
            abs(weight - full_edges[pair]) > 1e-9
            if exact_edge_weights
            else weight > full_edges[pair] + 1e-9
        )
        if invalid_weight:
            raise ValueError(f"Peso alterado na aresta visual {pair}.")
        visual_sum += weight
    if visual_sum > sum(full_edges.values()) + 1e-9:
        raise ValueError("A soma dos pesos visuais excede a rede completa.")


def validate_matched_graphs(observational: nx.Graph, balanced: nx.Graph) -> None:
    if set(observational.nodes()) != set(balanced.nodes()):
        raise ValueError(
            "As redes comparativas observacional e balanceada possuem nos diferentes."
        )
