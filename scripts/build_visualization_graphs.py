"""Gera subgrafos e previews destinados às figuras do TCC."""

from _bootstrap import ROOT  # noqa: F401

import argparse
import json
from pathlib import Path

from tcc_reddit.visualization import build_visualization_graphs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gera a camada visual sem alterar as redes analiticas completas."
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--config", type=Path, default=None)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all-variants", action="store_true")
    group.add_argument(
        "--variant", choices=("observational", "balanced"), default=None
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    variants = (args.variant,) if args.variant else ("observational", "balanced")
    summary = build_visualization_graphs(
        run_id=args.run_id,
        variants=variants,
        config_path=args.config,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
