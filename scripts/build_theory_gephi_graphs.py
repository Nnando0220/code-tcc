"""Gera os grafos didáticos da fundamentação teórica para uso no Gephi."""

from __future__ import annotations

import csv
from itertools import combinations
from pathlib import Path
from xml.etree import ElementTree

import networkx as nx


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "tcc_overleaf" / "gephi" / "representacoes-estruturas-rede"

USER_COLOR = "#2563EB"
USER_COLORS = {
    "U1": "#2563EB",
    "U2": "#F59E0B",
    "U3": "#16A34A",
}
SUBREDDIT_COLORS = {
    "brasil": "#009C3B",
    "brasilivre": "#FFB703",
    "worldnews": "#00B4D8",
    "news": "#6C757D",
    "politics": "#8338EC",
}
EDGE_COLOR = "#64748B"

NODE_CSV_COLUMNS = (
    "Id",
    "Label",
    "node_type",
    "panel",
    "subreddit",
    "x",
    "y",
    "z",
    "color",
    "size",
    "label_size",
)
EDGE_CSV_COLUMNS = (
    "Source",
    "Target",
    "Type",
    "Weight",
    "Label",
    "relation_type",
    "weight_semantics",
    "shared_users",
    "shared_user_count",
    "response_count",
    "color",
    "thickness",
    "label_size",
)


def _rgb(color: str) -> dict[str, int | float]:
    value = color.removeprefix("#")
    return {
        "r": int(value[0:2], 16),
        "g": int(value[2:4], 16),
        "b": int(value[4:6], 16),
        "a": 1.0,
    }


def _add_node(
    graph: nx.Graph,
    node_id: str,
    *,
    label: str,
    node_type: str,
    panel: str,
    position: tuple[float, float],
    color: str,
    size: float,
    label_size: float = 18.0,
    subreddit: str = "",
) -> None:
    x, y = position
    graph.add_node(
        node_id,
        label=label,
        node_type=node_type,
        panel=panel,
        subreddit=subreddit,
        x=float(x),
        y=float(y),
        z=0.0,
        display_label=label,
        label_size=float(label_size),
        visual_color=color,
        visual_size=float(size),
        viz={
            "color": _rgb(color),
            "size": float(size),
            "position": {"x": float(x), "y": float(y), "z": 0.0},
            "shape": "disc",
        },
    )


def _edge_width(weight: float) -> float:
    return round(0.65 + float(weight) * 0.35, 2)


def _edge_viz(weight: float) -> dict:
    return {
        "color": _rgb(EDGE_COLOR),
        "thickness": _edge_width(weight),
    }


def build_user_user() -> nx.DiGraph:
    graph = nx.DiGraph(name="(a) Rede usuário-usuário")
    positions = {"U1": (-130, -90), "U2": (130, -90), "U3": (0, 110)}
    for user, position in positions.items():
        _add_node(
            graph,
            user,
            label=user,
            node_type="user",
            panel="a_usuario_usuario",
            position=position,
            color=USER_COLORS[user],
            size=52,
            label_size=22,
        )
    for source, target, weight in (("U1", "U2", 3), ("U1", "U3", 2), ("U2", "U3", 1)):
        edge_label = f"{weight} resposta" if weight == 1 else f"{weight} respostas"
        graph.add_edge(
            source,
            target,
            weight=float(weight),
            label=edge_label,
            display_label=edge_label,
            label_size=16.0,
            response_count=weight,
            relation_type="reply",
            weight_semantics="numero_de_respostas_observadas",
            visual_color=EDGE_COLOR,
            visual_width=_edge_width(weight),
            viz=_edge_viz(weight),
        )
    return graph


def render_user_user_preview(graph: nx.DiGraph, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    positions = {
        node: (float(data["x"]), float(data["y"]))
        for node, data in graph.nodes(data=True)
    }
    node_colors = [data["visual_color"] for _, data in graph.nodes(data=True)]
    edge_widths = [1.2 + float(data["visual_width"]) for *_, data in graph.edges(data=True)]
    edge_labels = {
        (source, target): data["label"]
        for source, target, data in graph.edges(data=True)
    }

    figure, axis = plt.subplots(figsize=(10.8, 9.09), dpi=100)
    figure.patch.set_facecolor("white")
    axis.set_facecolor("white")
    nx.draw_networkx_nodes(
        graph,
        positions,
        ax=axis,
        node_color=node_colors,
        node_size=4400,
        edgecolors="#1F2937",
        linewidths=3.0,
    )
    nx.draw_networkx_edges(
        graph,
        positions,
        ax=axis,
        edge_color=EDGE_COLOR,
        width=edge_widths,
        arrows=True,
        arrowsize=28,
        node_size=4400,
        min_source_margin=8,
        min_target_margin=8,
        connectionstyle="arc3,rad=0.015",
    )
    for node, (x, y) in positions.items():
        axis.text(
            x,
            y,
            node,
            ha="center",
            va="center",
            fontsize=20,
            fontweight="bold",
            color="#111827" if node == "U2" else "white",
            zorder=5,
        )
    nx.draw_networkx_edge_labels(
        graph,
        positions,
        edge_labels=edge_labels,
        ax=axis,
        font_size=14,
        font_weight="bold",
        font_color="#111827",
        label_pos=0.5,
        rotate=False,
        bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "#CBD5E1", "alpha": 0.96},
    )
    axis.set_xlim(-190, 190)
    axis.set_ylim(-145, 165)
    axis.axis("off")
    figure.subplots_adjust(left=0.03, right=0.97, top=0.97, bottom=0.03)
    figure.savefig(path, dpi=100, facecolor="white")
    plt.close(figure)


def build_user_subreddit() -> nx.Graph:
    graph = nx.Graph(name="(b) Rede usuário-subreddit")
    user_positions = {
        "U1": (-150, 120),
        "U2": (-150, 40),
        "U3": (-150, -40),
        "U4": (-150, -120),
    }
    subreddit_positions = {
        "brasilivre": (150, 160),
        "brasil": (150, 80),
        "worldnews": (150, 0),
        "news": (150, -80),
        "politics": (150, -160),
    }
    for user, position in user_positions.items():
        _add_node(
            graph,
            user,
            label=user,
            node_type="user",
            panel="b_usuario_subreddit",
            position=position,
            color=USER_COLOR,
            size=38,
        )
    for subreddit, position in subreddit_positions.items():
        _add_node(
            graph,
            f"subreddit:{subreddit}",
            label=f"r/{subreddit}",
            node_type="subreddit",
            panel="b_usuario_subreddit",
            position=position,
            color=SUBREDDIT_COLORS[subreddit],
            size=42,
            subreddit=subreddit,
        )
    participations = {
        "U1": ("brasil", "brasilivre"),
        "U2": ("brasil", "worldnews"),
        "U3": ("worldnews", "news"),
        "U4": ("news", "politics"),
    }
    for user, subreddits in participations.items():
        for subreddit in subreddits:
            graph.add_edge(
                user,
                f"subreddit:{subreddit}",
                weight=1.0,
                label="participação observada",
                relation_type="participation",
                weight_semantics="existencia_de_participacao_observada",
                visual_color=EDGE_COLOR,
                visual_width=_edge_width(1),
                viz=_edge_viz(1),
            )
    return graph


def build_subreddit_subreddit(bipartite: nx.Graph) -> nx.Graph:
    graph = nx.Graph(name="(c) Rede subreddit-subreddit")
    positions = {
        "brasil": (-130, 100),
        "brasilivre": (130, 100),
        "worldnews": (-130, -30),
        "news": (130, -30),
        "politics": (130, -160),
    }
    for subreddit, position in positions.items():
        _add_node(
            graph,
            f"subreddit:{subreddit}",
            label=f"r/{subreddit}",
            node_type="subreddit",
            panel="c_subreddit_subreddit",
            position=position,
            color=SUBREDDIT_COLORS[subreddit],
            size=44,
            subreddit=subreddit,
        )

    users_by_subreddit = {
        subreddit: set(bipartite.neighbors(f"subreddit:{subreddit}"))
        for subreddit in positions
    }
    for left, right in combinations(positions, 2):
        shared_users = sorted(users_by_subreddit[left] & users_by_subreddit[right])
        if not shared_users:
            continue
        weight = len(shared_users)
        graph.add_edge(
            f"subreddit:{left}",
            f"subreddit:{right}",
            weight=float(weight),
            label=f"{weight} usuário compartilhado",
            relation_type="shared_users_projection",
            shared_users=",".join(shared_users),
            shared_user_count=weight,
            weight_semantics="quantidade_absoluta_de_usuarios_compartilhados",
            visual_color=EDGE_COLOR,
            visual_width=_edge_width(weight),
            viz=_edge_viz(weight),
        )
    return graph


def render_subreddit_subreddit_preview(graph: nx.Graph, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    positions = {
        node: (float(data["x"]), float(data["y"]))
        for node, data in graph.nodes(data=True)
    }
    node_colors = [data["visual_color"] for _, data in graph.nodes(data=True)]
    node_labels = {node: data["label"] for node, data in graph.nodes(data=True)}
    edge_labels = {
        (source, target): data["shared_users"]
        for source, target, data in graph.edges(data=True)
    }

    figure, axis = plt.subplots(figsize=(10.8, 9.09), dpi=100)
    figure.patch.set_facecolor("white")
    axis.set_facecolor("white")
    nx.draw_networkx_nodes(
        graph,
        positions,
        ax=axis,
        node_color=node_colors,
        node_size=4400,
        edgecolors="#1F2937",
        linewidths=3.0,
    )
    nx.draw_networkx_edges(
        graph,
        positions,
        ax=axis,
        edge_color=EDGE_COLOR,
        width=2.8,
        node_size=4400,
    )
    nx.draw_networkx_labels(
        graph,
        positions,
        labels=node_labels,
        ax=axis,
        font_size=16,
        font_weight="bold",
        font_color="#111827",
    )
    nx.draw_networkx_edge_labels(
        graph,
        positions,
        edge_labels=edge_labels,
        ax=axis,
        font_size=14,
        font_weight="bold",
        font_color="#111827",
        rotate=False,
        bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "#CBD5E1", "alpha": 0.96},
    )
    axis.set_xlim(-190, 190)
    axis.set_ylim(-215, 160)
    axis.axis("off")
    figure.subplots_adjust(left=0.03, right=0.97, top=0.97, bottom=0.03)
    figure.savefig(path, dpi=100, facecolor="white")
    plt.close(figure)


def _copy_into_combined(
    combined: nx.MultiDiGraph,
    graph: nx.Graph,
    *,
    prefix: str,
    x_offset: float,
    edge_type: str,
) -> None:
    for node, data in graph.nodes(data=True):
        copied = dict(data)
        copied["x"] = float(data["x"]) + x_offset
        copied["viz"] = dict(data["viz"])
        copied["viz"]["position"] = dict(data["viz"]["position"])
        copied["viz"]["position"]["x"] = copied["x"]
        combined.add_node(f"{prefix}:{node}", **copied)
    for source, target, data in graph.edges(data=True):
        combined.add_edge(
            f"{prefix}:{source}",
            f"{prefix}:{target}",
            type=edge_type,
            **dict(data),
        )


def build_combined(
    user_user: nx.DiGraph,
    user_subreddit: nx.Graph,
    subreddit_subreddit: nx.Graph,
) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(name="Representações das estruturas de rede")
    _copy_into_combined(graph, user_user, prefix="a", x_offset=-520, edge_type="directed")
    _copy_into_combined(graph, user_subreddit, prefix="b", x_offset=0, edge_type="undirected")
    _copy_into_combined(
        graph,
        subreddit_subreddit,
        prefix="c",
        x_offset=520,
        edge_type="undirected",
    )
    return graph


def _write_and_validate(
    graph: nx.Graph,
    path: Path,
    nodes: int,
    edges: int,
    *,
    mixed: bool = False,
) -> None:
    nx.write_gexf(graph, path, encoding="utf-8", prettyprint=True, version="1.2draft")
    if mixed:
        namespace = {"g": "http://www.gexf.net/1.2draft"}
        root = ElementTree.parse(path).getroot()
        xml_nodes = root.findall(".//g:nodes/g:node", namespace)
        xml_edges = root.findall(".//g:edges/g:edge", namespace)
        edge_types = [edge.attrib.get("type") for edge in xml_edges]
        if len(xml_nodes) != nodes or len(xml_edges) != edges:
            raise RuntimeError(
                f"GEXF misto inválido em {path}: "
                f"{len(xml_nodes)} nós e {len(xml_edges)} arestas"
            )
        if edge_types.count("directed") != 3 or edge_types.count("undirected") != 12:
            raise RuntimeError(f"Tipos de aresta divergentes em {path}: {edge_types}")
        return
    loaded = nx.read_gexf(path)
    if loaded.number_of_nodes() != nodes or loaded.number_of_edges() != edges:
        raise RuntimeError(
            f"GEXF inválido em {path}: "
            f"{loaded.number_of_nodes()} nós e {loaded.number_of_edges()} arestas"
        )


def _write_csv_tables(
    graph: nx.Graph,
    directory: Path,
    *,
    nodes: int,
    edges: int,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    nodes_path = directory / "nodes.csv"
    edges_path = directory / "edges.csv"

    with nodes_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=NODE_CSV_COLUMNS)
        writer.writeheader()
        for node_id, data in graph.nodes(data=True):
            writer.writerow(
                {
                    "Id": node_id,
                    "Label": data["label"],
                    "node_type": data["node_type"],
                    "panel": data["panel"],
                    "subreddit": data.get("subreddit", ""),
                    "x": data["x"],
                    "y": data["y"],
                    "z": data["z"],
                    "color": data["visual_color"],
                    "size": data["visual_size"],
                    "label_size": data["label_size"],
                }
            )

    with edges_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=EDGE_CSV_COLUMNS)
        writer.writeheader()
        for source, target, data in graph.edges(data=True):
            edge_type = data.get("type")
            if edge_type is None:
                edge_type = "directed" if graph.is_directed() else "undirected"
            writer.writerow(
                {
                    "Source": source,
                    "Target": target,
                    "Type": str(edge_type).title(),
                    "Weight": data.get("weight", 1.0),
                    "Label": data.get("label", ""),
                    "relation_type": data.get("relation_type", ""),
                    "weight_semantics": data.get("weight_semantics", ""),
                    "shared_users": data.get("shared_users", ""),
                    "shared_user_count": data.get("shared_user_count", ""),
                    "response_count": data.get("response_count", ""),
                    "color": data.get("visual_color", EDGE_COLOR),
                    "thickness": data.get("visual_width", _edge_width(1)),
                    "label_size": data.get("label_size", ""),
                }
            )

    with nodes_path.open(encoding="utf-8", newline="") as csv_file:
        node_rows = list(csv.DictReader(csv_file))
    with edges_path.open(encoding="utf-8", newline="") as csv_file:
        edge_rows = list(csv.DictReader(csv_file))

    node_ids = {row["Id"] for row in node_rows}
    invalid_edges = [
        row
        for row in edge_rows
        if row["Source"] not in node_ids or row["Target"] not in node_ids
    ]
    if len(node_rows) != nodes or len(edge_rows) != edges or invalid_edges:
        raise RuntimeError(
            f"CSV inválido em {directory}: {len(node_rows)} nós, "
            f"{len(edge_rows)} arestas e {len(invalid_edges)} referências inválidas"
        )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    user_user = build_user_user()
    user_subreddit = build_user_subreddit()
    subreddit_subreddit = build_subreddit_subreddit(user_subreddit)
    combined = build_combined(user_user, user_subreddit, subreddit_subreddit)

    expected_projection = {
        frozenset(("subreddit:brasil", "subreddit:brasilivre")): "U1",
        frozenset(("subreddit:brasil", "subreddit:worldnews")): "U2",
        frozenset(("subreddit:worldnews", "subreddit:news")): "U3",
        frozenset(("subreddit:news", "subreddit:politics")): "U4",
    }
    actual_projection = {
        frozenset((source, target)): data["shared_users"]
        for source, target, data in subreddit_subreddit.edges(data=True)
    }
    if actual_projection != expected_projection:
        raise RuntimeError(f"Projeção bipartida divergente: {actual_projection}")

    render_user_user_preview(
        user_user,
        OUTPUT_DIR / "01_rede_usuario_usuario" / "usuario_usuario.png",
    )
    render_subreddit_subreddit_preview(
        subreddit_subreddit,
        OUTPUT_DIR / "03_rede_subreddit_subreddit" / "subreddit_subreddit.png",
    )

    outputs = (
        (user_user, "01_rede_usuario_usuario.gexf", 3, 3, False),
        (user_subreddit, "02_rede_usuario_subreddit.gexf", 9, 8, False),
        (subreddit_subreddit, "03_rede_subreddit_subreddit.gexf", 5, 4, False),
        (combined, "00_paineis_combinados.gexf", 17, 15, True),
    )
    for graph, filename, nodes, edges, mixed in outputs:
        path = OUTPUT_DIR / filename
        _write_and_validate(graph, path, nodes, edges, mixed=mixed)
        bundle_dir = OUTPUT_DIR / filename.removesuffix(".gexf")
        bundle_gexf = bundle_dir / "graph.gexf"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        _write_and_validate(graph, bundle_gexf, nodes, edges, mixed=mixed)
        _write_csv_tables(graph, bundle_dir, nodes=nodes, edges=edges)
        print(
            f"{bundle_dir.relative_to(ROOT)}: "
            f"nodes.csv ({nodes}), edges.csv ({edges}) e graph.gexf"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
