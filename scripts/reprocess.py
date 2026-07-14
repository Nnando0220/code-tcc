from _bootstrap import ROOT  # noqa: F401
import sys

from tcc_reddit.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["reprocess", *sys.argv[1:]]))
