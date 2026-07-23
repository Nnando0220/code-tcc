"""Orquestracao da camada de visualizacao separada dos artefatos analiticos."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd
import yaml

from ..settings import PROJECT_ROOT, load_config
from .edge_attributes import calculate_edge_context_attributes
from .exporters import (
    export_graph,
    generate_display_mapping,
    prepare_graph_for_export,
    write_json,
    write_mapping,
    write_selection_manifest,
    write_style_legend,
)
from .graph_builders import (
    build_bridge_bipartite_graph,
    build_subreddit_overlap_graph,
    build_user_graph,
    filter_components,
    graph_summary,
)
from .layouts import (
    calculate_bipartite_layout,
    calculate_layout,
    calculate_shared_layout,
)
from .node_attributes import (
    calculate_full_communities,
    calculate_participation_type_counts,
    calculate_user_membership_attributes,
    enrich_with_full_network_metrics,
)
from .sampling import (
    build_matched_attributes,
    select_bridge_users,
    select_stratified_users,
)
from .validation import validate_matched_graphs, validate_visualization_graph


@dataclass
class VariantContext:
    name: str
    output_directory: Path
    full_edges: pd.DataFrame
    detailed_edges: pd.DataFrame
    memberships: pd.DataFrame
    subreddit_edges: pd.DataFrame
    node_attributes: pd.DataFrame
    enriched_edges: pd.DataFrame
    full_graph: nx.Graph


def load_visualization_config(path: str | Path | None = None) -> dict:
    config_path = Path(path) if path else PROJECT_ROOT / "config" / "visualization.yaml"
    with config_path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}
    required = {"selection", "components", "node_size", "edge_width", "layout", "outputs"}
    if missing := required - set(payload):
        raise ValueError(f"Secoes ausentes em {config_path}: {sorted(missing)}")
    return payload


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Artefato analitico ausente: {path}")
    return pd.read_csv(path)


def _full_graph(full_edges: pd.DataFrame) -> nx.Graph:
    renamed = full_edges.rename(columns={"weight": "total_weight"})
    return nx.from_pandas_edgelist(
        renamed,
        source="node_a",
        target="node_b",
        edge_attr="total_weight",
        create_using=nx.Graph(),
    )


def _load_variant(
    run_id: str,
    variant: str,
    pipeline_config,
    visualization_config: dict,
) -> VariantContext:
    result_directory = PROJECT_ROOT / "results" / run_id / variant
    network_directory = result_directory / "networks"
    processed_directory = PROJECT_ROOT / "data" / "processed" / run_id / variant
    full_edges = _read_csv(network_directory / "user_user_edges_undirected.csv")
    detailed = _read_csv(network_directory / "user_user_edges_detailed.csv")
    memberships = _read_csv(network_directory / "user_subreddit_edges.csv")
    subreddit_edges = _read_csv(network_directory / "subreddit_subreddit_edges.csv")
    centrality = _read_csv(result_directory / "metrics" / "centrality_users.csv")
    participation_counts = calculate_participation_type_counts(
        processed_directory / "posts.parquet",
        processed_directory / "comments.parquet",
    )
    membership_attributes = calculate_user_membership_attributes(
        memberships,
        pipeline_config.brazilian_subreddits,
        pipeline_config.international_subreddits,
        participation_counts,
    )
    communities = calculate_full_communities(
        full_edges, seed=int(visualization_config["layout"]["seed"])
    )
    node_attributes = enrich_with_full_network_metrics(
        membership_attributes, centrality, communities
    )
    enriched_edges = calculate_edge_context_attributes(detailed, node_attributes)
    output_directory = result_directory / "visualization"
    output_directory.mkdir(parents=True, exist_ok=True)
    return VariantContext(
        name=variant,
        output_directory=output_directory,
        full_edges=full_edges,
        detailed_edges=detailed,
        memberships=memberships,
        subreddit_edges=subreddit_edges,
        node_attributes=node_attributes,
        enriched_edges=enriched_edges,
        full_graph=_full_graph(full_edges),
    )


def _build_variant_graphs(
    context: VariantContext,
    pipeline_config,
    config: dict,
) -> tuple[dict[str, nx.Graph], pd.DataFrame, dict[str, Any]]:
    subreddits = list(pipeline_config.subreddits)
    selected = select_stratified_users(
        context.node_attributes, config["selection"], subreddits
    )
    base = build_user_graph(context.enriched_edges, selected)
    base, component_stats = filter_components(base, config["components"])
    selected = selected[selected["user_hash"].isin(base.nodes())].copy()
    graphs: dict[str, nx.Graph] = {
        "user_user_segmented": base.copy(),
        "user_user_blocks": base.copy(),
        "user_user_communities": base.copy(),
    }

    bridge_nodes = int(config["selection"].get("bridge_bipartite_nodes", 200))
    bridge_attributes = select_bridge_users(context.node_attributes, bridge_nodes)
    graphs["bridge_users_bipartite"] = build_bridge_bipartite_graph(
        context.memberships, bridge_attributes, subreddits
    )
    cross_attributes = context.node_attributes[
        context.node_attributes["is_cross_block_bridge"]
    ].copy()
    graphs["cross_block_bridges"] = build_bridge_bipartite_graph(
        context.memberships, cross_attributes, subreddits
    )
    graphs["subreddit_overlap_enriched"] = build_subreddit_overlap_graph(
        context.memberships,
        context.subreddit_edges,
        context.node_attributes,
        pipeline_config.brazilian_subreddits,
        pipeline_config.international_subreddits,
    )

    subreddit_stats = {}
    maximum = int(config["selection"].get("subreddit_maximum_nodes", 400))
    for subreddit in subreddits:
        memberships = set(
            context.memberships.loc[
                context.memberships["target"] == subreddit, "source"
            ].astype(str)
        )
        candidates = (
            context.node_attributes[
                context.node_attributes["user_hash"].isin(memberships)
            ]
            .sort_values(
                ["weighted_degree_full", "betweenness_full", "user_hash"],
                ascending=[False, False, True],
            )
            .head(maximum)
            .copy()
        )
        subreddit_detailed = context.detailed_edges[
            context.detailed_edges["subreddit"] == subreddit
        ]
        subreddit_enriched = calculate_edge_context_attributes(
            subreddit_detailed, context.node_attributes
        )
        graph = build_user_graph(subreddit_enriched, candidates)
        graph, stats = filter_components(graph, config["components"])
        graphs[f"subreddits/{subreddit}"] = graph
        subreddit_stats[subreddit] = {**graph_summary(graph), **stats}

    metadata = {
        "variant": context.name,
        "stratified_selection": {**graph_summary(base), **component_stats},
        "subreddit_graphs": subreddit_stats,
        "graphs": {name: graph_summary(graph) for name, graph in graphs.items()},
    }
    return graphs, selected, metadata


def _all_user_ids(graphs: dict[str, nx.Graph]) -> set[str]:
    return {
        str(node)
        for graph in graphs.values()
        for node, data in graph.nodes(data=True)
        if data.get("node_type") == "user"
    }


def _export_variant(
    context: VariantContext,
    graphs: dict[str, nx.Graph],
    selected: pd.DataFrame,
    metadata: dict,
    mapping: dict[str, str],
    pipeline_config,
    config: dict,
) -> None:
    output = context.output_directory
    seed = int(config["layout"]["seed"])
    common_layout = calculate_layout(graphs["user_user_segmented"], seed)
    modes = {
        "user_user_segmented": ("primary", False, "Rede usuário–usuário segmentada"),
        "user_user_blocks": ("block", True, "Separação entre blocos"),
        "user_user_communities": ("community", True, "Comunidades estruturais (Louvain completo)"),
    }
    exported: dict[str, nx.Graph] = {}
    for name, (mode, neutral, title) in modes.items():
        graph = prepare_graph_for_export(
            graphs[name],
            display_mapping=mapping,
            positions=common_layout,
            color_mode=mode,
            node_size_config=config["node_size"],
            edge_width_config=config["edge_width"],
            neutral_edges=neutral,
        )
        validate_visualization_graph(
            graph,
            context.full_graph,
            maximum_nodes=int(config["selection"]["maximum_nodes"]),
            expected_subreddits=pipeline_config.subreddits,
        )
        export_graph(
            graph,
            output / f"{name}.gexf",
            preview_path=output / "previews" / f"{name}.svg",
            title=title,
            color_mode=mode,
        )
        exported[name] = graph

    categorical_layout = calculate_bipartite_layout(
        graphs["bridge_users_bipartite"],
        pipeline_config.brazilian_subreddits,
        pipeline_config.international_subreddits,
    )
    cross_layout = calculate_bipartite_layout(
        graphs["cross_block_bridges"],
        pipeline_config.brazilian_subreddits,
        pipeline_config.international_subreddits,
    )
    for name, layout, title in (
        ("bridge_users_bipartite", categorical_layout, "Usuários-ponte entre comunidades"),
        ("cross_block_bridges", cross_layout, "Pontes entre Brasil e internacional"),
    ):
        graph = prepare_graph_for_export(
            graphs[name], display_mapping=mapping, positions=layout,
            color_mode="primary", node_size_config=config["node_size"],
            edge_width_config=config["edge_width"], neutral_edges=False,
        )
        export_graph(
            graph, output / f"{name}.gexf",
            preview_path=output / "previews" / f"{name}.svg",
            title=title, color_mode="primary",
        )
        exported[name] = graph

    overlap_layout = calculate_layout(graphs["subreddit_overlap_enriched"], seed)
    overlap = prepare_graph_for_export(
        graphs["subreddit_overlap_enriched"], display_mapping=mapping,
        positions=overlap_layout, color_mode="primary",
        node_size_config={**config["node_size"], "attribute": "weighted_degree_full"},
        edge_width_config=config["edge_width"], neutral_edges=True,
    )
    export_graph(
        overlap, output / "subreddit_overlap_enriched.gexf",
        preview_path=output / "previews" / "subreddit_overlap.svg",
        title="Sobreposição entre subreddits", color_mode="primary",
    )
    exported["subreddit_overlap_enriched"] = overlap

    for name, raw_graph in graphs.items():
        if not name.startswith("subreddits/"):
            continue
        layout = calculate_layout(raw_graph, seed)
        graph = prepare_graph_for_export(
            raw_graph, display_mapping=mapping, positions=layout,
            color_mode="community", node_size_config=config["node_size"],
            edge_width_config=config["edge_width"], neutral_edges=True,
        )
        validate_visualization_graph(
            graph, context.full_graph,
            maximum_nodes=int(config["selection"].get("subreddit_maximum_nodes", 400)),
            exact_edge_weights=False,
        )
        export_graph(
            graph, output / f"{name}.gexf", preview_path=None,
            title=f"Rede de r/{name.split('/', 1)[1]}", color_mode="community",
        )

    write_selection_manifest(selected, mapping, output / "selection_manifest.csv")
    write_mapping(
        {user: mapping[user] for user in sorted(_all_user_ids(graphs))},
        output / "visualization_node_mapping.csv",
    )
    write_style_legend(output / "style_legend.csv")
    metadata["layout"] = {
        "algorithm_requested": config["layout"].get("algorithm", "forceatlas2"),
        "seed": seed,
        "coordinates_exported": True,
        "note": "ForceAtlas2 quando disponível; spring layout determinístico como fallback compatível.",
    }
    write_json(metadata, output / "visualization_manifest.json")


def _build_and_export_comparison(
    observational: VariantContext,
    balanced: VariantContext,
    mapping: dict[str, str],
    pipeline_config,
    config: dict,
) -> dict:
    common_attributes = build_matched_attributes(
        observational.node_attributes, balanced.node_attributes
    )
    selected = select_stratified_users(
        common_attributes, config["selection"], pipeline_config.subreddits
    )
    obs_graph = build_user_graph(observational.enriched_edges, selected)
    bal_graph = build_user_graph(balanced.enriched_edges, selected)
    union = nx.compose(obs_graph, bal_graph)
    union, component_stats = filter_components(union, config["components"])
    common_nodes = set(union.nodes())
    obs_graph = obs_graph.subgraph(common_nodes).copy()
    bal_graph = bal_graph.subgraph(common_nodes).copy()
    validate_matched_graphs(obs_graph, bal_graph)
    positions = calculate_shared_layout(
        obs_graph, bal_graph, int(config["layout"]["seed"])
    )
    output = PROJECT_ROOT / "results" / config["run_id"] / "comparison" / "visualization"
    output.mkdir(parents=True, exist_ok=True)
    prepared = {}
    for name, graph, full in (
        ("observational_matched", obs_graph, observational.full_graph),
        ("balanced_matched", bal_graph, balanced.full_graph),
    ):
        current = prepare_graph_for_export(
            graph, display_mapping=mapping, positions=positions,
            color_mode="primary", node_size_config=config["node_size"],
            edge_width_config=config["edge_width"], neutral_edges=False,
        )
        validate_visualization_graph(
            current, full, maximum_nodes=int(config["selection"]["maximum_nodes"]),
            expected_subreddits=pipeline_config.subreddits,
        )
        export_graph(
            current, output / f"{name}.gexf",
            preview_path=output / "previews" / f"{name}.svg",
            title=f"Comparação pareada — {name.replace('_matched', '')}",
            color_mode="primary",
        )
        prepared[name] = current
    validate_matched_graphs(*prepared.values())
    matched_selected = selected[selected["user_hash"].isin(common_nodes)].copy()
    write_selection_manifest(matched_selected, mapping, output / "selection_manifest.csv")
    write_mapping(
        {user: mapping[user] for user in sorted(common_nodes)},
        output / "visualization_node_mapping.csv",
    )
    write_style_legend(output / "style_legend.csv")
    manifest = {
        "selection": graph_summary(union),
        "component_filter": component_stats,
        "same_node_set": set(obs_graph) == set(bal_graph),
        "shared_coordinates": True,
        "seed": int(config["layout"]["seed"]),
        "observational": graph_summary(obs_graph),
        "balanced": graph_summary(bal_graph),
    }
    write_json(manifest, output / "visualization_manifest.json")
    return manifest


def build_visualization_graphs(
    *,
    run_id: str | None = None,
    variants: tuple[str, ...] = ("observational", "balanced"),
    config_path: str | Path | None = None,
) -> dict:
    """Gera todos os artefatos visuais e retorna um resumo auditavel."""
    pipeline_config = load_config()
    config = load_visualization_config(config_path)
    effective_run_id = run_id or str(config.get("run_id") or pipeline_config.run_id)
    config["run_id"] = effective_run_id
    invalid = set(variants) - {"observational", "balanced"}
    if invalid:
        raise ValueError(f"Variantes invalidas: {sorted(invalid)}")

    contexts = {
        variant: _load_variant(
            effective_run_id, variant, pipeline_config, config
        )
        for variant in variants
    }
    built = {
        name: _build_variant_graphs(context, pipeline_config, config)
        for name, context in contexts.items()
    }
    all_users = set().union(
        *(_all_user_ids(graphs) for graphs, _, _ in built.values())
    )
    if len(contexts) == 2:
        matched_candidates = select_stratified_users(
            build_matched_attributes(
                contexts["observational"].node_attributes,
                contexts["balanced"].node_attributes,
            ),
            config["selection"],
            pipeline_config.subreddits,
        )
        all_users.update(matched_candidates["user_hash"].astype(str))
    mapping = generate_display_mapping(all_users)
    for name, context in contexts.items():
        graphs, selected, metadata = built[name]
        _export_variant(
            context, graphs, selected, metadata, mapping, pipeline_config, config
        )

    summary = {name: metadata for name, (_, _, metadata) in built.items()}
    if set(contexts) == {"observational", "balanced"}:
        summary["comparison"] = _build_and_export_comparison(
            contexts["observational"], contexts["balanced"], mapping,
            pipeline_config, config,
        )
    return summary
