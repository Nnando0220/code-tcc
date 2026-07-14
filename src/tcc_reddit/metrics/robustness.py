"""Comparacao observacional, balanceada e historica."""

from ..reporting.analysis import build_variant_comparison
from .comparison import (
    build_coverage_comparison,
    build_global_comparison,
    build_structural_comparison,
)

__all__ = [
    "build_coverage_comparison",
    "build_global_comparison",
    "build_structural_comparison",
    "build_variant_comparison",
]
