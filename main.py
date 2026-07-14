"""Ponto de entrada compativel; a implementacao vive em src/tcc_reddit."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tcc_reddit.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
