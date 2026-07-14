"""Interface de linha de comando canonica do projeto."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .paths import RunPaths
from .reporting.artifacts import cleanup_legacy_layout, publish_current_run
from .settings import load_config, validate_environment
from .validation.validate_all import validate_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tcc-reddit",
        description="Pipeline reproduzivel de redes do Reddit",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Diretorio com collection.yaml, sampling.yaml e networks.yaml.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="Executa uma nova coleta e todo o pipeline.")
    commands.add_parser(
        "reprocess",
        help="Reconstroi todos os derivados sem acessar o Reddit.",
    )
    commands.add_parser("analyze", help="Recalcula relatorios e comparacoes.")
    commands.add_parser("publish", help="Publica o layout canonico do run_id.")
    commands.add_parser("validate", help="Valida dados, privacidade, CSVs e GEXF.")
    return parser


def _run_pipeline(config, reprocess_existing: bool) -> None:
    from . import legacy_pipeline

    legacy_pipeline.configure(config)
    legacy_pipeline.main(reprocess_existing=reprocess_existing)


def _run_analysis() -> None:
    from .metrics.comparison import main as compare_main
    from .reporting.analysis import run_analysis

    run_analysis(export=True)
    compare_main()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--reprocess-existing" in arguments:
        arguments = [item for item in arguments if item != "--reprocess-existing"]
        arguments.append("reprocess")
    elif not arguments:
        arguments = ["collect"]

    args = build_parser().parse_args(arguments)
    config = load_config(args.config_dir)
    paths = RunPaths.from_config(config)

    if args.command == "collect":
        validate_environment(require_reddit=True)
        _run_pipeline(config, reprocess_existing=False)
        manifest = publish_current_run(config, paths)
        _run_analysis()
        validation = validate_run(config, paths)
        cleanup_legacy_layout(paths)
        print(f"Manifest: {manifest}")
        print(json.dumps(validation, indent=2))
    elif args.command == "reprocess":
        validate_environment(require_reddit=False)
        _run_pipeline(config, reprocess_existing=True)
        manifest = publish_current_run(config, paths)
        _run_analysis()
        validation = validate_run(config, paths)
        cleanup_legacy_layout(paths)
        print(f"Manifest: {manifest}")
        print(json.dumps(validation, indent=2))
    elif args.command == "analyze":
        _run_analysis()
        print(publish_current_run(config, paths))
    elif args.command == "publish":
        print(publish_current_run(config, paths))
    elif args.command == "validate":
        print(json.dumps(validate_run(config, paths), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
