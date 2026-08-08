"""Verificacao complementar da estabilidade do Louvain entre sementes."""

from __future__ import annotations

from collections.abc import Iterable

import networkx as nx
import pandas as pd


LOUVAIN_STABILITY_SEEDS = (42, 123, 456, 789, 2026)


def build_subreddit_graph(edges: pd.DataFrame, subreddit: str) -> nx.Graph:
    """Reconstroi a rede nao dirigida e ponderada de um subreddit."""
    subset = edges.loc[
        edges["subreddit"].eq(subreddit),
        ["source", "target", "weight"],
    ].dropna(subset=["source", "target"])
    subset = subset[subset["source"] != subset["target"]]

    ordered = pd.DataFrame(
        {
            "node_a": subset[["source", "target"]].min(axis=1),
            "node_b": subset[["source", "target"]].max(axis=1),
            "weight": pd.to_numeric(subset["weight"], errors="raise"),
        }
    )
    ordered = ordered.groupby(["node_a", "node_b"], as_index=False)["weight"].sum()

    return nx.from_pandas_edgelist(
        ordered,
        source="node_a",
        target="node_b",
        edge_attr="weight",
        create_using=nx.Graph(),
    )


def evaluate_louvain_seeds(
    graph: nx.Graph,
    seeds: Iterable[int] = LOUVAIN_STABILITY_SEEDS,
) -> pd.DataFrame:
    """Executa Louvain e registra modularidade e quantidade de comunidades."""
    rows = []
    for seed in seeds:
        communities = nx.community.louvain_communities(
            graph,
            weight="weight",
            seed=seed,
        )
        rows.append(
            {
                "seed": int(seed),
                "modularity": float(
                    nx.community.modularity(graph, communities, weight="weight")
                ),
                "communities_count": len(communities),
            }
        )
    return pd.DataFrame(rows)


def run_louvain_stability(
    edges: pd.DataFrame,
    seeds: Iterable[int] = LOUVAIN_STABILITY_SEEDS,
) -> pd.DataFrame:
    """Executa a verificacao para todos os subreddits presentes nas arestas."""
    required = {"source", "target", "subreddit", "weight"}
    missing = required - set(edges.columns)
    if missing:
        raise ValueError(
            "Colunas ausentes para a estabilidade do Louvain: "
            + ", ".join(sorted(missing))
        )

    seed_values = tuple(int(seed) for seed in seeds)
    if not seed_values:
        raise ValueError("Ao menos uma semente deve ser informada.")

    results = []
    for subreddit in sorted(edges["subreddit"].dropna().astype(str).unique()):
        graph = build_subreddit_graph(edges, subreddit)
        if graph.number_of_nodes() == 0:
            raise ValueError(f"Rede vazia para o subreddit {subreddit}.")
        run = evaluate_louvain_seeds(graph, seed_values)
        run.insert(0, "subreddit", subreddit)
        results.append(run)
    if not results:
        raise ValueError("Nenhum subreddit disponivel para validar Louvain.")
    return pd.concat(results, ignore_index=True)


def summarize_louvain_stability(results: pd.DataFrame) -> dict:
    """Resume cobertura, intervalos e estabilidade da ordenacao por semente."""
    grouped = results.groupby("subreddit", sort=True)
    ranges = {
        subreddit: {
            "modularity_min": float(rows["modularity"].min()),
            "modularity_max": float(rows["modularity"].max()),
            "communities_min": int(rows["communities_count"].min()),
            "communities_max": int(rows["communities_count"].max()),
        }
        for subreddit, rows in grouped
    }

    rankings = []
    for _, rows in results.groupby("seed", sort=True):
        rankings.append(
            tuple(
                rows.sort_values(
                    ["modularity", "subreddit"],
                    ascending=[False, True],
                )["subreddit"]
            )
        )

    return {
        "seeds": sorted(int(seed) for seed in results["seed"].unique()),
        "subreddits": int(results["subreddit"].nunique()),
        "executions": int(len(results)),
        "ranking_stable": len(set(rankings)) == 1,
        "ranges": ranges,
    }
