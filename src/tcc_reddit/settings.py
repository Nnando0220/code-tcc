"""Carregamento e validacao da configuracao externa do pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


@dataclass(frozen=True)
class PipelineConfig:
    run_id: str
    pipeline_version: str
    subreddits: tuple[str, ...]
    brazilian_subreddits: tuple[str, ...]
    international_subreddits: tuple[str, ...]
    sorts: tuple[str, ...]
    window_start: str
    window_end: str
    time_filter: str
    window_days: int
    candidates_per_sort: int
    posts_per_subreddit: int
    exclude_stickied: bool
    replace_more_limit: int | None
    balanced_comments_per_post: int
    preserve_ancestors: bool
    random_seed: int
    gephi_minimum_weight: int
    gephi_minimum_degree: int
    gephi_keep_largest_component: bool
    gephi_visualization_max_nodes: int
    export_by_subreddit: bool
    betweenness_sample_size: int


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de configuracao ausente: {path}")
    with path.open("r", encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Configuracao invalida em {path}: objeto YAML esperado.")
    return payload


def load_config(config_dir: str | Path | None = None) -> PipelineConfig:
    directory = Path(config_dir) if config_dir else PROJECT_ROOT / "config"
    collection = _read_yaml(directory / "collection.yaml")
    sampling = _read_yaml(directory / "sampling.yaml")
    networks = _read_yaml(directory / "networks.yaml")

    run_id = str(collection.get("run_id", "")).strip()
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(
            "run_id deve conter somente letras, numeros, hifen e sublinhado."
        )

    groups = collection.get("subreddits", {})
    brazil = tuple(groups.get("brazil", []))
    international = tuple(groups.get("international", []))
    subreddits = brazil + international
    if not subreddits or len(set(subreddits)) != len(subreddits):
        raise ValueError("A lista de subreddits esta vazia ou contem duplicatas.")

    collection_options = collection.get("collection", {})
    window = collection.get("window", {})
    balanced = sampling.get("balanced", {})
    gephi = networks.get("gephi", {})
    centrality = networks.get("centrality", {})

    return PipelineConfig(
        run_id=run_id,
        pipeline_version=str(collection.get("pipeline_version", "2.0.0")),
        subreddits=subreddits,
        brazilian_subreddits=brazil,
        international_subreddits=international,
        sorts=tuple(collection.get("sorts", [])),
        window_start=str(window["start"]),
        window_end=str(window["end"]),
        time_filter=str(window.get("time_filter", "year")),
        window_days=int(window.get("days", 365)),
        candidates_per_sort=int(collection_options.get("candidates_per_sort", 100)),
        posts_per_subreddit=int(collection_options.get("posts_per_subreddit", 150)),
        exclude_stickied=bool(collection_options.get("exclude_stickied", True)),
        replace_more_limit=collection_options.get("replace_more_limit"),
        balanced_comments_per_post=int(balanced.get("comments_per_post", 300)),
        preserve_ancestors=bool(balanced.get("preserve_ancestors", True)),
        random_seed=int(balanced.get("random_seed", 42)),
        gephi_minimum_weight=int(gephi.get("minimum_weight", 2)),
        gephi_minimum_degree=int(gephi.get("minimum_degree", 2)),
        gephi_keep_largest_component=bool(gephi.get("keep_largest_component", True)),
        gephi_visualization_max_nodes=int(gephi.get("visualization_max_nodes", 400)),
        export_by_subreddit=bool(gephi.get("export_by_subreddit", True)),
        betweenness_sample_size=int(centrality.get("betweenness_sample_size", 100)),
    )


def validate_environment(*, require_reddit: bool) -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    required = ["TCC_HASH_SALT"]
    if require_reddit:
        required.extend(
            ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT"]
        )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError("Variaveis ausentes no .env: " + ", ".join(missing))
