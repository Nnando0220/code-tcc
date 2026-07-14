"""Caminhos canonicos de dados e resultados para uma execucao."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .settings import PROJECT_ROOT, PipelineConfig


@dataclass(frozen=True)
class RunPaths:
    project_root: Path
    run_id: str
    raw: Path
    interim: Path
    processed_observational: Path
    processed_balanced: Path
    results: Path
    observational: Path
    balanced: Path
    comparison: Path
    reports: Path
    logs: Path

    @classmethod
    def from_config(cls, config: PipelineConfig) -> "RunPaths":
        results = PROJECT_ROOT / "results" / config.run_id
        return cls(
            project_root=PROJECT_ROOT,
            run_id=config.run_id,
            raw=PROJECT_ROOT / "data" / "raw" / config.run_id,
            interim=PROJECT_ROOT / "data" / "interim" / config.run_id,
            processed_observational=(
                PROJECT_ROOT / "data" / "processed" / config.run_id / "observational"
            ),
            processed_balanced=(
                PROJECT_ROOT / "data" / "processed" / config.run_id / "balanced"
            ),
            results=results,
            observational=results / "observational",
            balanced=results / "balanced",
            comparison=results / "comparison",
            reports=results / "reports",
            logs=PROJECT_ROOT / "logs" / config.run_id,
        )

    def create(self) -> None:
        directories = [
            self.raw,
            self.interim,
            self.processed_observational,
            self.processed_balanced,
            self.comparison,
            self.reports,
            self.logs,
        ]
        for variant in (self.observational, self.balanced):
            directories.extend(
                variant / name
                for name in ("networks", "metrics", "gephi", "tables", "figures")
            )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
