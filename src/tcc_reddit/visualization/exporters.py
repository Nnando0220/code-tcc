"""Exportacao GEXF, manifestos, legendas e previews SVG autocontidos."""

from __future__ import annotations

import html
import json
import math
from pathlib import Path

import networkx as nx
import pandas as pd

from .palettes import (
    BLOCK_COLORS,
    NEUTRAL_EDGE,
    ROLE_COLORS,
    SUBREDDIT_COLORS,
    color_for_node,
    community_color,
    hex_to_rgb,
)


def generate_display_mapping(user_ids) -> dict[str, str]:
    return {
        str(user_hash): f"U{index:04d}"
        for index, user_hash in enumerate(sorted(set(map(str, user_ids))), start=1)
    }


def _scaled(value: float, values: list[float], minimum: float, maximum: float) -> float:
    transformed = math.log1p(max(float(value), 0.0))
    transformed_values = [math.log1p(max(float(item), 0.0)) for item in values]
    low, high = min(transformed_values, default=0.0), max(transformed_values, default=0.0)
    if high <= low:
        return (minimum + maximum) / 2
    return minimum + (transformed - low) * (maximum - minimum) / (high - low)


def prepare_graph_for_export(
    graph: nx.Graph,
    *,
    display_mapping: dict[str, str],
    positions: dict[str, tuple[float, float, float]],
    color_mode: str,
    node_size_config: dict,
    edge_width_config: dict,
    neutral_edges: bool = False,
) -> nx.Graph:
    result = graph.copy()
    node_values = [
        float(data.get(node_size_config["attribute"], data.get("weighted_degree_full", 0)))
        for _, data in result.nodes(data=True)
    ]
    edge_values = [
        float(data.get(edge_width_config["attribute"], data.get("total_weight", 0)))
        for _, _, data in result.edges(data=True)
    ]
    for node, data in result.nodes(data=True):
        if data.get("node_type") == "subreddit":
            label = data.get("label", str(node))
        else:
            label = display_mapping[str(node)]
        color = color_for_node(data, color_mode)
        size = _scaled(
            data.get(node_size_config["attribute"], data.get("weighted_degree_full", 0)),
            node_values,
            float(node_size_config["minimum"]),
            float(node_size_config["maximum"]),
        )
        x, y, z = positions.get(str(node), (0.0, 0.0, 0.0))
        data["label"] = str(label)
        data["x"], data["y"], data["z"] = float(x), float(y), float(z)
        data["visual_color"] = color
        data["visual_size"] = float(size)
        data["viz"] = {
            "color": hex_to_rgb(color),
            "size": float(size),
            "position": {"x": float(x), "y": float(y), "z": float(z)},
        }
    for _, _, data in result.edges(data=True):
        color = NEUTRAL_EDGE if neutral_edges else SUBREDDIT_COLORS.get(
            str(data.get("dominant_subreddit")), NEUTRAL_EDGE
        )
        width = _scaled(
            data.get(edge_width_config["attribute"], data.get("total_weight", 0)),
            edge_values,
            float(edge_width_config["minimum"]),
            float(edge_width_config["maximum"]),
        )
        data["weight"] = float(data.get("total_weight", 1.0))
        data["visual_color"] = color
        data["visual_width"] = float(width)
        data["viz"] = {"color": hex_to_rgb(color), "thickness": float(width)}
    public_ids = {
        node: display_mapping[str(node)]
        for node, data in result.nodes(data=True)
        if data.get("node_type") == "user"
    }
    return nx.relabel_nodes(result, public_ids, copy=True)


def _svg_preview(graph: nx.Graph, path: Path, title: str, color_mode: str) -> None:
    width, height = 1600, 1100
    plot_left, plot_top, plot_width, plot_height = 80, 120, 1160, 900
    positions = {
        str(node): (float(data.get("x", 0)), float(data.get("y", 0)))
        for node, data in graph.nodes(data=True)
    }
    xs = [value[0] for value in positions.values()] or [0]
    ys = [value[1] for value in positions.values()] or [0]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    def project(node):
        x, y = positions[str(node)]
        px = plot_left + (x - min_x) / max(max_x - min_x, 1) * plot_width
        py = plot_top + (max_y - y) / max(max_y - min_y, 1) * plot_height
        return px, py

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        f'<text x="80" y="58" font-family="Arial, sans-serif" font-size="30" font-weight="700" fill="#1F2937">{html.escape(title)}</text>',
        f'<text x="80" y="88" font-family="Arial, sans-serif" font-size="15" fill="#6B7280">{graph.number_of_nodes():,} nós · {graph.number_of_edges():,} arestas · layout reproduzível</text>',
        '<g id="edges">',
    ]
    for source, target, data in graph.edges(data=True):
        x1, y1 = project(source)
        x2, y2 = project(target)
        opacity = min(0.12 + float(data.get("visual_width", 0.2)) / 8, 0.55)
        lines.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{data.get("visual_color", NEUTRAL_EDGE)}" stroke-width="{data.get("visual_width", 0.5):.2f}" stroke-opacity="{opacity:.3f}"/>'
        )
    lines.append("</g><g id=\"nodes\">")
    ranked = sorted(
        graph.nodes(data=True),
        key=lambda item: float(item[1].get("weighted_degree_full", 0)),
        reverse=True,
    )
    labels = {node for node, _ in ranked[:18]}
    labels.update(
        node for node, data in graph.nodes(data=True) if data.get("node_type") == "subreddit"
    )
    for node, data in sorted(
        graph.nodes(data=True), key=lambda item: float(item[1].get("visual_size", 0))
    ):
        x, y = project(node)
        radius = max(2.2, float(data.get("visual_size", 6)) * 0.46)
        stroke = "#111827" if data.get("is_cross_block_bridge") else "#FFFFFF"
        stroke_width = 1.6 if data.get("is_cross_block_bridge") else 0.8
        lines.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{data.get("visual_color", "#ADB5BD")}" fill-opacity="0.92" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
        if node in labels:
            label = html.escape(str(data.get("label", node)))
            lines.append(
                f'<text x="{x + radius + 3:.2f}" y="{y + 4:.2f}" font-family="Arial, sans-serif" font-size="11" fill="#374151">{label}</text>'
            )
    lines.append("</g>")
    if color_mode == "block":
        legend = BLOCK_COLORS
    elif color_mode == "role":
        legend = ROLE_COLORS
    elif color_mode == "community":
        communities = sorted(
            {
                int(data.get("community_full", -1))
                for _, data in graph.nodes(data=True)
                if data.get("node_type") == "user"
            }
        )
        legend = {
            f"Comunidade {community}": community_color(community)
            for community in communities[:12]
        }
    else:
        legend = SUBREDDIT_COLORS
    lines.append('<g id="legend"><text x="1280" y="150" font-family="Arial, sans-serif" font-size="18" font-weight="700" fill="#1F2937">Legenda</text>')
    for index, (label, color) in enumerate(legend.items()):
        y = 185 + index * 34
        lines.append(f'<circle cx="1292" cy="{y}" r="7" fill="{color}"/>')
        lines.append(f'<text x="1310" y="{y + 5}" font-family="Arial, sans-serif" font-size="14" fill="#374151">{html.escape(str(label))}</text>')
    lines.append(
        '<text x="1280" y="510" font-family="Arial, sans-serif" font-size="13" fill="#6B7280">Tamanho: grau ponderado completo</text>'
    )
    lines.append(
        '<text x="1280" y="535" font-family="Arial, sans-serif" font-size="13" fill="#6B7280">Contorno escuro: ponte entre blocos</text>'
    )
    lines.append("</g></svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def export_graph(
    graph: nx.Graph,
    output_path: Path,
    *,
    preview_path: Path | None = None,
    title: str,
    color_mode: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(graph, output_path, encoding="utf-8", prettyprint=True)
    checked = nx.read_gexf(output_path)
    if checked.number_of_nodes() != graph.number_of_nodes() or checked.number_of_edges() != graph.number_of_edges():
        raise ValueError(f"GEXF incompleto apos exportacao: {output_path}")
    for node, data in checked.nodes(data=True):
        if data.get("node_type") != "user":
            continue
        if len(str(node)) >= 48 or len(str(data.get("label", ""))) >= 48:
            raise ValueError(f"Identificador privado exposto no GEXF: {output_path}")
    if preview_path is not None:
        _svg_preview(graph, preview_path, title, color_mode)


def write_selection_manifest(
    selected_attributes: pd.DataFrame,
    display_mapping: dict[str, str],
    output_path: Path,
) -> None:
    manifest = selected_attributes.copy()
    manifest.insert(1, "display_id", manifest["user_hash"].map(display_mapping))
    manifest = manifest.rename(columns={"user_hash": "node_id"})
    columns = [
        "node_id", "display_id", "primary_subreddit", "block", "subreddit_count",
        "is_bridge", "is_cross_block_bridge", "weighted_degree_full",
        "betweenness_full", "selection_reason",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest[columns].to_csv(output_path, index=False)


def write_mapping(mapping: dict[str, str], output_path: Path) -> None:
    pd.DataFrame(
        sorted(mapping.items()), columns=["user_hash", "display_id"]
    ).to_csv(output_path, index=False)


def write_style_legend(output_path: Path) -> None:
    rows = [
        {"dimension": "primary_subreddit", "value": key, "color": value}
        for key, value in SUBREDDIT_COLORS.items()
    ] + [
        {"dimension": "block", "value": key, "color": value}
        for key, value in BLOCK_COLORS.items()
    ] + [
        {"dimension": "node_role", "value": key, "color": value}
        for key, value in ROLE_COLORS.items()
    ]
    pd.DataFrame(rows).to_csv(output_path, index=False)


def write_json(payload: dict, output_path: Path) -> None:
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
