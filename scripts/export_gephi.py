"""Publica os GEXF existentes com nomes canonicos no run_id atual."""

from _bootstrap import ROOT  # noqa: F401
import sys

from tcc_reddit.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["publish", *sys.argv[1:]]))
