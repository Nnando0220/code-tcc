"""Publicacao nao destrutiva dos artefatos no layout canonico."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil

import pandas as pd

from ..paths import RunPaths
from ..settings import PipelineConfig


RAW_FILES = (
    "posts_raw.parquet",
    "comments_raw.parquet",
    "post_collections.parquet",
)

NETWORK_NAMES = {
    "edges_user_user_detailed.csv": "user_user_edges_detailed.csv",
    "edges_user_user_directed.csv": "user_user_edges_directed.csv",
    "edges_user_user_undirected.csv": "user_user_edges_undirected.csv",
    "edges_user_subreddit.csv": "user_subreddit_edges.csv",
    "edges_subreddit_subreddit.csv": "subreddit_subreddit_edges.csv",
}

GEPHI_NAMES = {
    "gephi_user_user_complete_corrected.gexf": "user_user_directed.gexf",
    "gephi_user_user_undirected_corrected.gexf": "user_user_undirected.gexf",
    "gephi_user_user_filtered.gexf": "user_user_visualization.gexf",
    "gephi_subreddit_subreddit.gexf": "subreddit_subreddit.gexf",
    "gephi_edges_user_user_complete.csv": "user_user_directed_edges.csv",
    "gephi_edges_user_user_undirected.csv": "user_user_undirected_edges.csv",
    "gephi_edges_user_user_filtered.csv": "user_user_visualization_edges.csv",
    "gephi_edges_subreddit_subreddit.csv": "subreddit_subreddit_edges.csv",
    "gephi_nodes_user_user_complete.csv": "user_user_nodes.csv",
    "gephi_nodes_user_user_filtered.csv": "user_user_visualization_nodes.csv",
    "gephi_nodes_subreddit_subreddit.csv": "subreddit_subreddit_nodes.csv",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_immutable(source: Path, destination: Path) -> None:
    """Copia um bruto uma vez e rejeita alteracoes posteriores no mesmo run_id."""
    if not source.exists():
        raise FileNotFoundError(f"Dado bruto ausente: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if file_sha256(source) != file_sha256(destination):
            raise ValueError(
                f"Tentativa de alterar dado bruto imutavel: {destination}"
            )
        return
    shutil.copy2(source, destination)


def copy_result(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _publish_variant(
    graph_source: Path,
    metrics_source: Path,
    destination: Path,
) -> None:
    for source_name, destination_name in NETWORK_NAMES.items():
        copy_result(
            graph_source / source_name,
            destination / "networks" / destination_name,
        )
    for source_name, destination_name in GEPHI_NAMES.items():
        copy_result(
            graph_source / source_name,
            destination / "gephi" / destination_name,
        )
    for metric in metrics_source.glob("*.csv"):
        copy_result(metric, destination / "metrics" / metric.name)

    by_subreddit = graph_source / "by_subreddit"
    if by_subreddit.exists():
        for artifact in by_subreddit.iterdir():
            if artifact.is_file():
                copy_result(
                    artifact,
                    destination / "gephi" / "by_subreddit" / artifact.name,
                )


def _raw_manifest(config: PipelineConfig, paths: RunPaths) -> dict:
    files = []
    for path in sorted(paths.raw.iterdir()):
        if path.is_file() and path.name != "manifest.json":
            files.append(
                {
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
    return {
        "run_id": config.run_id,
        "immutable": True,
        "contains_personal_identifiers": True,
        "public_distribution": False,
        "files": files,
    }


def register_raw_run(config: PipelineConfig, paths: RunPaths) -> Path:
    """Registra uma copia imutavel dos brutos antes de publicar derivados."""
    paths.create()
    legacy_data = paths.project_root / "data"

    for name in RAW_FILES:
        copy_immutable(legacy_data / "raw" / name, paths.raw / name)
    raw_manifest = _raw_manifest(config, paths)
    (paths.raw / "manifest.json").write_text(
        json.dumps(raw_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return paths.raw / "manifest.json"


def publish_current_run(config: PipelineConfig, paths: RunPaths) -> Path:
    """Publica o layout legado atual sem apagar ou renomear suas fontes."""
    paths.create()
    register_raw_run(config, paths)
    legacy_data = paths.project_root / "data"

    copy_result(
        legacy_data / "processed" / "posts_clean.parquet",
        paths.processed_observational / "posts.parquet",
    )
    copy_result(
        legacy_data / "processed" / "comments_clean.parquet",
        paths.processed_observational / "comments.parquet",
    )
    copy_result(
        legacy_data / "balanced" / "processed" / "posts_balanced_clean.parquet",
        paths.processed_balanced / "posts.parquet",
    )
    copy_result(
        legacy_data / "balanced" / "processed" / "comments_balanced_clean.parquet",
        paths.processed_balanced / "comments.parquet",
    )
    copy_result(
        legacy_data / "balanced" / "processed" / "sampling_manifest.csv",
        paths.processed_balanced / "sampling_manifest.csv",
    )

    _publish_variant(
        legacy_data / "graphs",
        legacy_data / "metrics",
        paths.observational,
    )
    _publish_variant(
        legacy_data / "balanced" / "graphs",
        legacy_data / "balanced" / "metrics",
        paths.balanced,
    )

    analysis_source = legacy_data / "analysis"
    if analysis_source.exists():
        for artifact in analysis_source.iterdir():
            if not artifact.is_file():
                continue
            destination = (
                paths.reports / artifact.name
                if artifact.suffix.lower() == ".md"
                else paths.comparison / artifact.name
            )
            copy_result(artifact, destination)

    posts = pd.read_parquet(paths.processed_observational / "posts.parquet")
    comments = pd.read_parquet(paths.processed_observational / "comments.parquet")
    manifest = {
        "run_id": config.run_id,
        "pipeline_version": config.pipeline_version,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "window_start": config.window_start,
        "window_end": config.window_end,
        "subreddits": list(config.subreddits),
        "posts": int(len(posts)),
        "comments": int(len(comments)),
        "variants": ["observational", "balanced"],
        "random_seed": config.random_seed,
        "raw_manifest": str((paths.raw / "manifest.json").relative_to(paths.project_root)),
    }
    manifest_path = paths.results / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path
