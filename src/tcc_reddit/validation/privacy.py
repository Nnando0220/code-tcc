"""Regras para impedir identificadores diretos nos dados publicaveis."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


FORBIDDEN_COLUMNS = {"author", "username", "user_name", "reddit_username"}


def validate_processed_privacy(path: Path) -> None:
    frame = pd.read_parquet(path)
    forbidden = FORBIDDEN_COLUMNS & set(map(str.lower, frame.columns))
    if forbidden:
        raise ValueError(
            f"Identificadores diretos em {path}: {sorted(forbidden)}"
        )
    if "author_hash" not in frame.columns:
        raise ValueError(f"Coluna author_hash ausente em {path}.")


def validate_raw_is_not_under_results(raw_path: Path, results_path: Path) -> None:
    raw_resolved = raw_path.resolve()
    results_resolved = results_path.resolve()
    if raw_resolved == results_resolved or results_resolved in raw_resolved.parents:
        raise ValueError("Dados brutos nao podem ficar dentro de results/.")
