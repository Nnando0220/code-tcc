"""Validacao cruzada entre CSVs agregados e arquivos GEXF."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import pandas as pd


def count_gexf(path: Path) -> tuple[int, int]:
    nodes = 0
    edges = 0
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag.endswith("}node"):
            nodes += 1
        elif element.tag.endswith("}edge"):
            edges += 1
        element.clear()
    return nodes, edges


def validate_gexf_edge_count(csv_path: Path, gexf_path: Path) -> dict:
    if not csv_path.exists() or not gexf_path.exists():
        raise FileNotFoundError(
            f"Par CSV/GEXF incompleto: {csv_path} | {gexf_path}"
        )
    csv_edges = len(pd.read_csv(csv_path, low_memory=False))
    nodes, gexf_edges = count_gexf(gexf_path)
    if csv_edges != gexf_edges:
        raise ValueError(
            f"GEXF divergente: {gexf_edges} arestas para {csv_edges} linhas em {csv_path}."
        )
    return {"nodes": nodes, "edges": gexf_edges}
