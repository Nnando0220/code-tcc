"""Testes dos contratos da arquitetura por execucao."""

from pathlib import Path

import pandas as pd
import pytest

from ._bootstrap import ROOT  # noqa: F401
from tcc_reddit.cli import build_parser
from tcc_reddit.paths import RunPaths
from tcc_reddit.reporting.artifacts import (
    GEPHI_NAMES,
    NETWORK_NAMES,
    cleanup_legacy_layout,
    copy_immutable,
)
from tcc_reddit.settings import load_config
from tcc_reddit.validation.privacy import validate_processed_privacy


def test_project_configuration_is_valid():
    config = load_config()

    assert config.run_id == "run_2026_07_year_v2"
    assert len(config.subreddits) == 8
    assert config.posts_per_subreddit == 150
    assert config.random_seed == 42


def test_run_paths_separate_raw_and_results():
    paths = RunPaths.from_config(load_config())

    assert paths.raw != paths.results
    assert paths.results.resolve() not in paths.raw.resolve().parents
    assert paths.run_id in str(paths.raw)
    assert paths.run_id in str(paths.results)


def test_cli_has_specialized_commands():
    parser = build_parser()
    expected_commands = {"collect", "reprocess", "analyze", "publish", "validate"}
    for command in expected_commands:
        assert parser.parse_args([command]).command == command
    command_action = next(
        action for action in parser._actions if action.dest == "command"
    )
    assert set(command_action.choices) == expected_commands


@pytest.mark.parametrize(
    "name",
    list(NETWORK_NAMES.values()) + list(GEPHI_NAMES.values()),
)
def test_canonical_names_have_no_version_suffixes(name):
    assert "complete" not in name
    assert "corrected" not in name
    assert "final" not in name


def test_raw_copy_rejects_changes(tmp_path: Path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "raw" / "source.bin"
    source.write_bytes(b"original")
    copy_immutable(source, destination)
    source.write_bytes(b"changed")

    with pytest.raises(ValueError, match="dado bruto imutavel"):
        copy_immutable(source, destination)


def test_processed_privacy_rejects_username(tmp_path: Path):
    path = tmp_path / "posts.parquet"
    pd.DataFrame(
        {"author": ["usuario"], "author_hash": ["a" * 64]}
    ).to_parquet(path, index=False)

    with pytest.raises(ValueError, match="Identificadores diretos"):
        validate_processed_privacy(path)


def test_legacy_cleanup_requires_valid_canonical_run(tmp_path: Path):
    config = load_config()
    paths = RunPaths(
        project_root=tmp_path,
        run_id=config.run_id,
        raw=tmp_path / "data" / "raw" / config.run_id,
        interim=tmp_path / "data" / "interim" / config.run_id,
        processed_observational=tmp_path / "data" / "processed" / config.run_id / "observational",
        processed_balanced=tmp_path / "data" / "processed" / config.run_id / "balanced",
        results=tmp_path / "results" / config.run_id,
        observational=tmp_path / "results" / config.run_id / "observational",
        balanced=tmp_path / "results" / config.run_id / "balanced",
        comparison=tmp_path / "results" / config.run_id / "comparison",
        reports=tmp_path / "results" / config.run_id / "reports",
        logs=tmp_path / "logs" / config.run_id,
    )
    legacy = tmp_path / "data" / "graphs"
    legacy.mkdir(parents=True)
    (legacy / "old.gexf").write_text("old", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="Limpeza legada bloqueada"):
        cleanup_legacy_layout(paths)

    assert legacy.exists()
